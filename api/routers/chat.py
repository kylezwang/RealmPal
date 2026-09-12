"""
Chat streaming endpoint with rate limiting and paywall.

Rate limiting design:
- Redis key: `ratelimit:{session_id}` -> integer count
- 3 free messages per session (TTL 24h from first message)
- After limit: return 402 with {"upgrade": true, "checkout_url": ...}
- Paid users: JWT token in Authorization header bypasses limit

Streaming design (learned from Certio improvements):
- Uses FastAPI StreamingResponse with proper disconnect handling
- AbortController on frontend cancels the stream cleanly
- Loguru structured logging throughout
"""
import base64
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, AsyncGenerator, Optional

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from qdrant_client import AsyncQdrantClient

import redis.asyncio as aioredis

from ..config import Settings, get_settings
from ..dependencies import get_optional_user, get_redis, get_qdrant
from ..identity import AuthenticatedUser, bearer_token
from ..models.chat import (
    ChatAttachment,
    ChatRequest,
    FeedbackRequest,
    FeedbackResponse,
    PaywallResponse,
    UsageResponse,
)
from ..models.build import CLASS_ABILITY_HUB
from ..services.rag import build_system_prompt, rag_exclude_slugs, retrieve_context
from ..services.scraper import ScraperError
from ..services.ingestion import ingest_player
from ..services.player_lookup import PLAYER_CACHE_PREFIX, get_or_scrape_player
from ..services.realmshark import parse_query, retrieve_build_knowledge
from ..services.dungeon_guide import extract_dungeon_query
from ..services.item_aliases import is_set_visualize_query
from ..services.player_lookup import extract_player_ign
from ..services.skin_visualizer import is_skin_visualize_query
from ..services.dev_access import is_debug_unlimited
from ..services.rate_limit import (
    USER_SCOPE,
    Quota,
    consume,
    hash_identifier,
    peek,
    quota_for,
)
from ..services.budget import disabled_reason, record_llm_failure, record_usage
from ..services.llm import build_chat_client
from ..services import entitlements
from ..auth import decode_jwt, email_from_session_header

router = APIRouter(prefix="/chat", tags=["chat"])
FEEDBACK_LOG_MAX = 10_000
RESPONSE_CAP = 20_000
TEXT_CAP = 4_000
MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024
# Prior turns are replayed on every request, so an unbounded history makes
# each message in a long conversation progressively more expensive.
HISTORY_CONTENT_CAP = 4_000
ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
ALLOWED_DOCUMENT_TYPES = frozenset({"application/pdf"})


def _validate_attachment(att: ChatAttachment) -> None:
    """Reject oversized or unsupported files before they burn a rate-limit slot."""
    try:
        raw = base64.b64decode(att.data, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid attachment encoding") from exc
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=400, detail="Attachment too large (max 4MB)")
    media = (att.media_type or "").lower()
    if media not in ALLOWED_IMAGE_TYPES and media not in ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported attachment type")


def _user_content(body: ChatRequest) -> str | list[dict]:
    """Plain text, or Claude vision/document blocks when a file is attached."""
    text = body.message.strip()
    att = body.attachment
    if att is None:
        return text

    media = att.media_type.lower()
    if media in ALLOWED_IMAGE_TYPES:
        file_block: dict = {
            "type": "image",
            "source": {"type": "base64", "media_type": media, "data": att.data},
        }
    else:
        file_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": media, "data": att.data},
        }
    caption = text or (
        f"The user attached a file named {att.filename}. "
        "Look at it and help with their RotMG question."
    )
    return [file_block, {"type": "text", "text": caption}]


async def _has_legacy_paid_token(auth_header: Optional[str], settings: Settings) -> bool:
    """
    True for a still-valid magic-link JWT from the pre-identity-provider flow,
    *and* a durable entitlement that hasn't been revoked.

    Signature and expiry alone used to be the whole check | a cancelled or
    refunded plan kept working until the token expired (up to
    JWT_EXPIRY_DAYS). api/services/entitlements.py now holds what Stripe's
    webhooks actually know: only an email with an active/trialing row
    passes. Since `/auth/request-link` hands out a magic link to anyone,
    signature and expiry alone are satisfied by every free sign-in too, so
    an unknown or inactive email fails here even with a validly signed,
    unexpired token.
    """
    token = bearer_token(auth_header)
    if not token:
        return False
    try:
        claims = decode_jwt(token, settings.jwt_secret, settings.jwt_algorithm)
    except Exception:
        return False
    email = str(claims.get("email") or "").strip()
    if not email:
        return bool(claims.get("paid"))
    # The JWT `paid` claim is stale the moment someone finishes Stripe
    # Checkout — the webhook / confirm path writes entitlements, not a
    # new token. Always trust the store for a signed-in email.
    return await entitlements.is_active(email, settings)


async def _enforce_quota(
    quota: Quota,
    redis: aioredis.Redis,
    settings: Settings,
    auth_header: Optional[str],
    user: Optional[AuthenticatedUser] = None,
) -> None:
    """Count this request against its quota, or raise 402 once it's spent."""
    if await is_debug_unlimited(user, settings):
        return
    if await _has_legacy_paid_token(auth_header, settings):
        # Still metered, just far more generously. An unlimited bypass meant
        # one leaked token could spend without bound.
        await _enforce_paid_ceiling(auth_header, redis, settings)
        return

    count = await consume(redis, quota)
    if count <= quota.limit:
        return

    # Anonymous callers have a free way out | sign in. Only prompt for money
    # once someone signed in has actually used up their allowance. Before an
    # identity provider is configured there's nothing to sign into, so fall
    # back to the checkout prompt rather than a dead end.
    if quota.is_anonymous and settings.auth_configured:
        message = (
            f"You've used your {quota.limit} free messages. "
            "Sign in to keep going."
        )
        checkout_url = None
    else:
        message = (
            f"You've used your {quota.limit} free messages. "
            "Join Realm Pal for $7/month to continue."
        )
        checkout_url = _checkout_url_for(quota, settings, auth_header)

    logger.bind(scope=quota.scope, bucket=quota.label, used=count, limit=quota.limit).info(
        "Quota exhausted"
    )
    raise HTTPException(
        status_code=402,
        detail=PaywallResponse(
            message=message,
            checkout_url=checkout_url,
            scope=quota.scope,
            used=min(count, quota.limit),
            limit=quota.limit,
            remaining=0,
        ).model_dump(),
    )


async def _enforce_paid_ceiling(
    auth_header: Optional[str],
    redis: aioredis.Redis,
    settings: Settings,
) -> None:
    """
    Apply a generous daily ceiling to legacy subscribers.

    Keyed on a hash of the token's subject rather than the token itself, so
    the counter survives a re-issue and the key isn't a credential.
    """
    token = bearer_token(auth_header) or ""
    try:
        claims = decode_jwt(token, settings.jwt_secret, settings.jwt_algorithm)
    except Exception:
        return
    subject = str(claims.get("email") or claims.get("sub") or "").strip().lower()
    if not subject:
        return

    quota = Quota(
        scope=USER_SCOPE,
        key=f"ratelimit:paid:{hash_identifier(subject, settings)}",
        limit=settings.paid_message_limit,
        label="paid",
    )
    count = await consume(redis, quota)
    if count <= quota.limit:
        return

    logger.bind(used=count, limit=quota.limit).warning("Paid daily ceiling reached")
    raise HTTPException(
        status_code=429,
        detail=(
            f"You've reached the daily limit of {quota.limit} messages. "
            "It resets tomorrow."
        ),
    )


def _checkout_url_for(
    quota: Quota, settings: Settings, auth_header: Optional[str]
) -> Optional[str]:
    if not settings.stripe_configured:
        return None
    email = email_from_session_header(auth_header, settings)
    try:
        stripe.api_key = settings.stripe_secret_key
        extra: dict = {}
        if email:
            extra["customer_email"] = email
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
            success_url=f"{settings.app_url}?upgraded=true&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=settings.app_url,
            metadata={"quota_scope": quota.scope, "email": email or ""},
            **extra,
        )
        return session.url
    except Exception:
        logger.exception("Failed to create Stripe checkout session")
        return None


async def _stream_response(
    messages: list[dict],
    system_prompt: str,
    settings: Settings,
    redis: aioredis.Redis,
) -> AsyncGenerator[str, None]:
    """
    Stream Claude response as SSE chunks.
    Yields: `data: {"content": "...", "done": false}\n\n`
    Final: `data: {"content": "", "done": true}\n\n`

    Records what the call cost once it finishes, so the daily ceiling in
    api/services/budget.py reflects real token counts rather than estimates.
    Provider errors are counted separately for monitoring; exception text is
    not logged, because the SDK has previously rendered keys into the sink.
    """
    provider = settings.llm_provider
    client = build_chat_client(settings)
    started = time.perf_counter()

    try:
        async with client.messages.stream(
            model=settings.claude_model,
            max_tokens=settings.max_response_tokens,
            system=system_prompt,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                chunk = json.dumps({"content": text, "done": False})
                yield f"data: {chunk}\n\n"

            # Usage is only final once the stream completes. A client that
            # disconnects early leaves this unrecorded, which under-counts
            # rather than over-counts | acceptable, since the alternative is
            # billing people for tokens we can't measure.
            try:
                final = await stream.get_final_message()
                await record_usage(
                    redis,
                    settings,
                    input_tokens=final.usage.input_tokens,
                    output_tokens=final.usage.output_tokens,
                    provider=provider,
                )
            except Exception:
                logger.exception("Could not record spend for a completed stream")

        yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        logger.bind(
            provider=provider,
            error_type=type(exc).__name__,
            elapsed_ms=elapsed_ms,
        ).error("Error during Claude streaming")
        await record_llm_failure(redis, settings, provider=provider)
        error_chunk = json.dumps({"error": "Claude stream failed", "done": True})
        yield f"data: {error_chunk}\n\n"
    finally:
        try:
            await client.close()
        except Exception:
            logger.bind(provider=provider).warning("Could not close chat client")


@router.get("/usage")
async def chat_usage(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    user: Annotated[Optional[AuthenticatedUser], Depends(get_optional_user)] = None,
) -> UsageResponse:
    """
    Usage for whoever is calling: the signed-in account, or this IP.

    `session_id` is still accepted for backward compatibility but no longer
    affects the answer | it was client-supplied, so it could never be a
    reliable key.
    """
    quota = quota_for(user, request, settings)
    if await is_debug_unlimited(user, settings):
        return UsageResponse(
            used=0,
            limit=settings.paid_message_limit,
            remaining=settings.paid_message_limit,
            scope="user",
        )
    if user and user.email and await entitlements.is_active(user.email, settings):
        return UsageResponse(
            used=0,
            limit=settings.paid_message_limit,
            remaining=settings.paid_message_limit,
            scope="user",
        )
    try:
        used = await peek(redis, quota)
    except Exception:
        logger.exception("Failed to read chat usage")
        raise HTTPException(status_code=503, detail="Usage unavailable")
    return UsageResponse(
        used=used,
        limit=quota.limit,
        remaining=max(0, quota.limit - used),
        scope=quota.scope,
    )


@router.post("/feedback", response_model=FeedbackResponse)
async def chat_feedback(
    body: FeedbackRequest,
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> FeedbackResponse:
    """Record thumbs-up / thumbs-down on an assistant reply, plus optional notes."""
    session_id = body.session_id.strip()
    message_id = body.message_id.strip()
    if not session_id or not message_id:
        raise HTTPException(status_code=400, detail="session_id and message_id are required")

    event = {
        "id": str(uuid.uuid4()),
        "rating": body.rating,
        "message_id": message_id[:128],
        "session_id": session_id[:128],
        "response": (body.response or "")[:RESPONSE_CAP],
        "prompt": (body.prompt or "")[:TEXT_CAP] or None,
        "what_went_wrong": (body.what_went_wrong or "")[:TEXT_CAP] or None,
        "improvement": (body.improvement or "")[:TEXT_CAP] or None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.bind(
        rating=event["rating"],
        session_id=event["session_id"][:8],
        message_id=event["message_id"][:8],
        has_comment=bool(event["what_went_wrong"] or event["improvement"]),
    ).info("Chat feedback recorded")
    try:
        payload = json.dumps(event)
        await redis.set(f"feedback:item:{event['message_id']}", payload)
        await redis.lpush("feedback:log", payload)
        await redis.ltrim("feedback:log", 0, FEEDBACK_LOG_MAX - 1)
    except Exception:
        logger.exception("Failed to persist chat feedback")
        raise HTTPException(status_code=503, detail="Feedback unavailable")
    return FeedbackResponse()


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    qdrant: Annotated[AsyncQdrantClient, Depends(get_qdrant)],
    user: Annotated[Optional[AuthenticatedUser], Depends(get_optional_user)] = None,
    authorization: Annotated[Optional[str], Header()] = None,
) -> StreamingResponse:
    """Stream a chat response. Quota is keyed on the verified caller or their IP."""

    if not body.message.strip() and body.attachment is None:
        raise HTTPException(status_code=400, detail="Message is empty")
    if body.attachment is not None:
        _validate_attachment(body.attachment)

    # Checked before the quota so a shut-off deployment doesn't silently
    # consume someone's allowance on a request it won't answer.
    unavailable = await disabled_reason(redis, settings)
    if unavailable:
        raise HTTPException(status_code=503, detail=unavailable)

    quota = quota_for(user, request, settings)
    await _enforce_quota(quota, redis, settings, authorization, user)

    # Player profiles change constantly — scrape on lookup. The short TTL
    # only collapses sidebar + chat hitting RealmEye twice in one session.
    if body.ign:
        cache_key = f"{PLAYER_CACHE_PREFIX}{body.ign.lower()}"
        had_cached = settings.player_ttl_seconds > 0 and await redis.exists(cache_key)
        try:
            profile = await get_or_scrape_player(
                redis, body.ign, ttl_seconds=settings.player_ttl_seconds
            )
            if not had_cached:
                await ingest_player(qdrant, profile)
        except ScraperError as e:
            logger.bind(ign=body.ign, error=str(e)).warning("Could not scrape player on chat request")
        except Exception as e:
            # e.g. embeddings backend (Ollama) unreachable | don't block chat
            logger.bind(ign=body.ign, error=str(e)).warning(
                "Could not ingest scraped player profile on chat request"
            )

    # Retrieve RAG context. A degraded embeddings/vector backend (e.g. Ollama
    # not running locally) must never take down the whole chat feature |
    # fall back to answering with no retrieved context instead of 500ing.
    user_history = [
        msg.content for msg in body.history[-10:] if msg.role == "user"
    ]
    history_texts = user_history
    player_only = False
    try:
        query_text = body.message.strip()
        if not query_text and body.attachment is not None:
            query_text = body.attachment.filename
        class_name, stat, buildish = parse_query(query_text, history=user_history)
        this_class, _this_stat, _this_build = parse_query(query_text)
        dungeon_only = bool(
            extract_dungeon_query(query_text, history=user_history)
        ) and not buildish
        # This-turn IGN lookups stay off the wiki/DPS path even if an
        # earlier Bard/Huntress question would inherit as buildish.
        player_only = bool(extract_player_ign(query_text)) or (
            bool(extract_player_ign(query_text, history=user_history))
            and not this_class
        )
        # Specialists already inject the right chunk. Extra wiki RAG pads
        # the bill and, if we glue on the previous user turn, mixes topics
        # (player lookup + Bard attack → off-class bows).
        if (
            dungeon_only
            or player_only
            or is_skin_visualize_query(query_text)
            or is_set_visualize_query(query_text)
        ):
            context = ""
        else:
            rag_query = " ".join(
                part
                for part in (class_name, stat, query_text)
                if part
            )
            exclude_hubs = rag_exclude_slugs(class_name, stat)
            context = await retrieve_context(
                qdrant, rag_query, exclude_url_substrings=exclude_hubs
            )
            if class_name:
                hub = CLASS_ABILITY_HUB.get(class_name, "")
                extra_q = " ".join(
                    part for part in (class_name, hub, stat, "ability scaling") if part
                )
                extra = await retrieve_context(
                    qdrant, extra_q, exclude_url_substrings=exclude_hubs
                )
                if extra and extra not in context:
                    context = f"{context}\n\n---\n\n{extra}" if context else extra
    except Exception as e:
        logger.bind(error=str(e)).warning(
            "RAG context retrieval failed, answering without retrieved context"
        )
        context = ""

    # Stat-scaling graph + top-5 DPS loadouts from RealmShark. Injected as
    # structured context (not just a vector hit) so an "attack Bard" question
    # actually sees that The Triangle is the Attack-scaling lute.
    try:
        build_ctx = await retrieve_build_knowledge(
            redis,
            body.message,
            ttl_seconds=settings.wiki_ttl_seconds,
            player_ttl_seconds=settings.player_ttl_seconds,
            history=history_texts,
        )
        if build_ctx:
            if player_only:
                context = (
                    f"{context}\n\n---\n\n{build_ctx}" if context else build_ctx
                )
            else:
                citation = "Source: https://tracker.realmshark.cc/dps-leaderboards"
                block = f"{citation}\n{build_ctx}"
                context = f"{context}\n\n---\n\n{block}" if context else block
    except Exception as e:
        logger.bind(error=str(e)).warning("RealmShark build knowledge unavailable")

    system_prompt = build_system_prompt(context, ign=body.ign)

    # Build message history for Claude. Both the turn count and the size of
    # each turn are capped: input tokens are billed, and a long conversation
    # would otherwise grow the cost of every subsequent message.
    messages = [
        {"role": msg.role, "content": msg.content[:HISTORY_CONTENT_CAP]}
        for msg in body.history[-10:]
    ] + [{"role": "user", "content": body.message}]

    logger.bind(
        session_id=body.session_id[:8],
        ign=body.ign,
        provider=settings.llm_provider,
        context_chunks=context.count("---") + 1 if context else 0,
    ).info("Chat stream started")

    return StreamingResponse(
        _stream_response(messages, system_prompt, settings, redis),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
