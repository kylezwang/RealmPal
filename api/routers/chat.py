"""
Chat streaming endpoint with rate limiting and paywall.

Rate limiting design:
- Daily in-depth quota: guests 3, signed-in free 5. Stored answers skip this.
- After the daily in-depth cap: 402 on Claude turns. Stored answers still serve.
- Burst cap on every /chat/stream turn (stored included): 20/min guest, 60/min signed-in. 429 when exceeded.
- After limit: return 402 with {"upgrade": true, "checkout_url": ...}

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
    MAX_ATTACHMENTS,
    ChatAttachment,
    ChatRequest,
    FeedbackRequest,
    FeedbackResponse,
    PaywallResponse,
    SiteFeedbackRequest,
    UsageResponse,
)
from ..models.build import CLASS_ABILITY_HUB
from ..services.rag import build_system_prompt, rag_exclude_slugs, retrieve_context
from ..services.realmshark import parse_query, retrieve_build_knowledge
from ..services.dungeon_guide import extract_dungeon_query
from ..services.biomes import extract_biome_query
from ..services.rotmg_hub import extract_hub_query, retrieve_rotmg_hub
from ..services.enchanting import is_enchant_query
from ..services.forging import is_forge_query
from ..services.item_scaling import is_item_scaling_query
from ..services.dps_specialist import is_dps_query, is_stat_number_query
from ..services.item_aliases import (
    is_set_followup,
    is_set_visualize_query,
    is_stat_class_shiny_divine_query,
)
from ..services.player_lookup import extract_player_ign
from ..services.skin_visualizer import (
    is_skin_visualize_query,
    outfit_history_from_messages,
    visual_history_from_messages,
)
from ..services.dev_access import is_debug_unlimited
from ..services.admin_access import is_admin
from ..services.rate_limit import (
    USER_SCOPE,
    Quota,
    chat_burst_quota_for,
    consume,
    consume_windowed,
    hash_identifier,
    peek,
    peek_ttl,
    product_feedback_quota_for,
    quota_for,
)
from ..services.budget import cost_micros, disabled_reason, record_llm_failure, record_usage
from ..services.llm import build_chat_client
from ..services.model_route import pick_chat_model
from ..services import admin_events
from ..services import entitlements
from ..services import product_feedback
from ..services.claude_billing import consume_claude_reply, peek_claude_usage
from ..services import daily_quests
from ..services.stored_answers import maybe_mint_brief, try_stored_reply
from ..services.validation import sanitize_ign
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


def _validate_attachment(att: ChatAttachment) -> None:
    """Reject oversized or unsupported files before they burn a rate-limit slot."""
    try:
        raw = base64.b64decode(att.data, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid attachment encoding") from exc
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=400, detail="Attachment too large (max 4MB)")
    media = (att.media_type or "").lower()
    if media not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported attachment type")


def _request_attachments(body: ChatRequest) -> list[ChatAttachment]:
    """Legacy `attachment` plus `attachments`, capped at MAX_ATTACHMENTS."""
    atts: list[ChatAttachment] = []
    if body.attachment is not None:
        atts.append(body.attachment)
    atts.extend(body.attachments)
    if len(atts) > MAX_ATTACHMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"At most {MAX_ATTACHMENTS} images per message",
        )
    return atts


def _user_content(body: ChatRequest, attachments: list[ChatAttachment]) -> str | list[dict]:
    """Plain text, or Claude vision blocks when images are attached."""
    text = body.message.strip()
    if not attachments:
        return text

    blocks: list[dict] = []
    for att in attachments:
        media = att.media_type.lower()
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media, "data": att.data},
        })
    caption = text or (
        "The user attached RotMG screenshot(s). Read the character, gear, vault, "
        "or inventory in the image(s) and help with their question."
    )
    blocks.append({"type": "text", "text": caption})
    return blocks


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
    # Checkout - the webhook / confirm path writes entitlements, not a
    # new token. Always trust the store for a signed-in email.
    return await entitlements.is_active(email, settings)


def _quest_subject(user: Optional[AuthenticatedUser], quota: Quota) -> str:
    if user and user.email:
        return user.email
    if user:
        return user.subject
    return quota.key


async def _enforce_chat_burst(
    user: Optional[AuthenticatedUser],
    request: Request,
    redis: aioredis.Redis,
    settings: Settings,
) -> None:
    """Cap every chat turn, including stored answers, so the daily in-depth
    skip cannot be used as an unthrottled flood."""
    if await is_debug_unlimited(user, settings):
        return
    burst = chat_burst_quota_for(user, request, settings)
    try:
        count = await consume_windowed(redis, burst)
    except Exception:
        logger.exception("Could not enforce chat burst limit")
        raise HTTPException(
            status_code=503,
            detail="Too many questions. Try again in a minute.",
        ) from None
    if count <= burst.limit:
        return
    logger.bind(bucket=burst.label, used=count, limit=burst.limit).info(
        "Chat burst limit exceeded"
    )
    raise HTTPException(
        status_code=429,
        detail="Too many questions. Try again in a minute.",
        headers={"Retry-After": str(burst.window_seconds)},
    )


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

    try:
        count = await consume(redis, quota)
        bonus = await daily_quests.peek_free_bonus(
            redis, _quest_subject(user, quota), settings
        )
    except Exception:
        logger.exception("Could not enforce chat quota")
        raise HTTPException(status_code=503, detail="Usage unavailable") from None
    if count <= quota.limit + bonus:
        return

    resets_in = await peek_ttl(redis, quota)
    # Anonymous callers have a free way out | sign in. Only prompt for money
    # once someone signed in has actually used up their allowance. Before an
    # identity provider is configured there's nothing to sign into, so fall
    # back to the checkout prompt rather than a dead end.
    if quota.is_anonymous and settings.auth_configured:
        message = (
            f"You've used your {quota.limit} free in-depth responses. "
            "Sign in to keep going."
        )
        checkout_url = None
    else:
        message = (
            f"You've used your {quota.limit} free in-depth responses. "
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
            reason="free_quota",
            resets_in_seconds=resets_in,
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
    try:
        count = await consume(redis, quota)
    except Exception:
        logger.exception("Could not enforce paid chat ceiling")
        raise HTTPException(status_code=503, detail="Usage unavailable") from None
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
            payment_method_types=["card", "link"],
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


async def _stream_stored(text: str) -> AsyncGenerator[str, None]:
    chunk = json.dumps({"content": text, "done": False, "stored": True})
    yield f"data: {chunk}\n\n"
    yield f"data: {json.dumps({'content': '', 'done': True, 'stored': True})}\n\n"


async def _stream_response(
    messages: list[dict],
    system_prompt: str,
    settings: Settings,
    redis: aioredis.Redis,
    mint=None,
    model: str = "",
    *,
    chat_tier: str = "guest",
    chat_email: Optional[str] = None,
    chat_ign: Optional[str] = None,
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
    collected: list[str] = []

    try:
        model_id = model or settings.claude_model
        async with client.messages.stream(
            model=model_id,
            max_tokens=settings.max_response_tokens,
            system=system_prompt,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                collected.append(text)
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
                    model=model_id,
                )
                micros = cost_micros(
                    settings,
                    final.usage.input_tokens,
                    final.usage.output_tokens,
                    model=model_id,
                )
                await admin_events.record_chat_turn(
                    settings,
                    tier=chat_tier,
                    cost_usd=round(micros / 1_000_000, 6),
                    email=chat_email,
                    ign=chat_ign,
                )
            except Exception:
                logger.exception("Could not record spend for a completed stream")

        if mint is not None:
            try:
                await mint("".join(collected))
            except Exception:
                logger.exception("Could not mint a stored brief after Claude")

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
    admin = await is_admin(user, settings)
    if await is_debug_unlimited(user, settings):
        return UsageResponse(
            used=0,
            limit=settings.paid_message_limit,
            remaining=settings.paid_message_limit,
            scope="user",
            tier="paid",
            claude_limit=settings.paid_claude_included,
            claude_remaining=settings.paid_claude_included,
            is_admin=admin,
        )
    if user and user.email and await entitlements.is_active(user.email, settings):
        claude = await peek_claude_usage(redis, user.email, settings)
        return UsageResponse(
            used=claude.used,
            limit=claude.included,
            remaining=claude.remaining,
            scope="user",
            tier="paid",
            claude_used=claude.used,
            claude_limit=claude.included,
            claude_remaining=claude.remaining,
            spend_cap_usd=claude.spend_cap_usd,
            on_demand_spent_usd=claude.on_demand_spent_usd,
            is_admin=admin,
        )
    try:
        used = await peek(redis, quota)
        resets_in = await peek_ttl(redis, quota)
        bonus = await daily_quests.peek_free_bonus(
            redis, _quest_subject(user, quota), settings
        )
    except Exception:
        logger.exception("Failed to read chat usage")
        raise HTTPException(status_code=503, detail="Usage unavailable")
    limit = quota.limit + bonus
    return UsageResponse(
        used=used,
        limit=limit,
        remaining=max(0, limit - used),
        scope=quota.scope,
        tier="free" if quota.scope == USER_SCOPE else "guest",
        resets_in_seconds=resets_in,
        is_admin=admin,
    )


@router.get("/quests/art")
async def quest_art(
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    shift: int = 0,
) -> dict:
    """Today's dungeon portal and a cached shiny sprite for the quests modal."""
    art = await daily_quests.todays_quest_art(redis, settings, shift=max(0, shift))
    return {
        "dungeon_name": art.dungeon_name,
        "dungeon_prompt": art.dungeon_prompt,
        "dungeon_portal_url": art.dungeon_portal_url,
        "shiny_name": art.shiny_name,
        "shiny_sprite_url": art.shiny_sprite_url,
    }


@router.post("/quests/claim")
async def claim_daily_quests(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    user: Annotated[Optional[AuthenticatedUser], Depends(get_optional_user)] = None,
    authorization: str | None = Header(default=None),
) -> dict:
    """Grant +1 message after today's quests. Free and paid.

    Idempotent per rolling quota window (free/guest) or per claim-to-claim
    day (paid, feeds the monthly Claude pool). See daily_quests.py.
    """
    quota = quota_for(user, request, settings)
    paid = bool(user and user.email and await entitlements.is_active(user.email, settings))
    if not paid:
        paid = await _has_legacy_paid_token(authorization, settings)
    subject = _quest_subject(user, quota)
    # Sync the claim/bonus lifetime to the caller's actual quota reset so a
    # UTC-midnight calendar flip can't grant (or drop) a bonus out of step
    # with the quota it boosts. Paid claims feed a monthly pool instead, so
    # they don't need the live quota TTL.
    quota_ttl = 0 if paid else await peek_ttl(redis, quota)
    granted = await daily_quests.claim_daily_bonus(
        redis, subject, settings, paid=paid, quota_ttl_seconds=quota_ttl
    )
    bonus = (
        await daily_quests.peek_paid_bonus(redis, subject, settings)
        if paid
        else await daily_quests.peek_free_bonus(redis, subject, settings)
    )
    return {"granted": granted, "bonus": bonus}


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


@router.post("/site-feedback", response_model=FeedbackResponse)
async def site_feedback(
    body: SiteFeedbackRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    user: Annotated[Optional[AuthenticatedUser], Depends(get_optional_user)] = None,
) -> FeedbackResponse:
    """Header Feedback modal. Rows land in product_feedback for Azure scans."""
    what_works = (body.what_works or "").strip()
    what_to_improve = (body.what_to_improve or "").strip()
    anything_else = (body.anything_else or "").strip()
    if not (what_works or what_to_improve or anything_else):
        raise HTTPException(
            status_code=400,
            detail="Tell us what works, what to fix, or anything else.",
        )

    bucket = product_feedback_quota_for(user, request, settings)
    try:
        count = await consume_windowed(redis, bucket)
    except Exception:
        logger.exception("Could not enforce site-feedback rate limit")
        raise HTTPException(status_code=503, detail="Feedback unavailable")
    if count > bucket.limit:
        raise HTTPException(
            status_code=429,
            detail="Thanks, we already have recent feedback from you.",
            headers={"Retry-After": str(bucket.window_seconds)},
        )

    try:
        await product_feedback.insert_feedback(
            settings,
            rating=body.rating,
            what_works=what_works,
            what_to_improve=what_to_improve,
            anything_else=anything_else,
            email=user.email if user else None,
            ign=body.ign,
        )
    except Exception:
        logger.exception("Failed to persist site feedback")
        raise HTTPException(status_code=503, detail="Feedback unavailable")
    logger.bind(
        rating=body.rating,
        signed_in=bool(user),
        has_text=True,
    ).info("Site feedback recorded")
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

    attachments = _request_attachments(body)
    if not body.message.strip() and not attachments:
        raise HTTPException(status_code=400, detail="Message is empty")
    for att in attachments:
        _validate_attachment(att)

    ign = sanitize_ign(body.ign)

    # Checked before the quota so a shut-off deployment doesn't silently
    # consume someone's allowance on a request it won't answer.
    unavailable = await disabled_reason(redis, settings)
    if unavailable:
        raise HTTPException(status_code=503, detail=unavailable)

    await _enforce_chat_burst(user, request, redis, settings)

    quota = quota_for(user, request, settings)

    user_history = [
        msg.content for msg in body.history[-10:] if msg.role == "user"
    ]
    outfit_history = outfit_history_from_messages(body.history[-10:])
    visual_history = visual_history_from_messages(body.history[-10:])
    paid = bool(
        user
        and user.email
        and await entitlements.is_active(user.email, settings)
    ) or await _has_legacy_paid_token(authorization, settings)

    stored = None
    try:
        stored = await try_stored_reply(
            redis,
            body.message,
            history=visual_history,
            ttl_seconds=settings.wiki_ttl_seconds,
            player_ttl_seconds=settings.player_ttl_seconds,
            has_attachment=bool(attachments),
        )
    except Exception:
        logger.exception("Stored-answer lookup failed; falling through to Claude")
        stored = None
    if stored:
        # No Claude call. Daily quota and the paid Claude meter stay put
        # for guests, free accounts, and Pro. Only a real model turn spends.
        logger.bind(
            session_id=body.session_id[:8],
            kind=stored.kind,
            stored_key=stored.key,
        ).info("Chat served from stored answer")
        return StreamingResponse(
            _stream_stored(stored.text),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    await _enforce_quota(quota, redis, settings, authorization, user)
    await consume_claude_reply(redis, user, settings, paid=paid)

    # Retrieve RAG context. A degraded embeddings/vector backend (e.g. Ollama
    # not running locally) must never take down the whole chat feature |
    # fall back to answering with no retrieved context instead of 500ing.
    history_texts = user_history
    dungeon_only = False
    player_only = False
    hub_only = False
    try:
        query_text = body.message.strip()
        if not query_text and attachments:
            query_text = attachments[0].filename
        class_name, stat, buildish = parse_query(query_text, history=user_history)
        this_class, _this_stat, _this_build = parse_query(query_text)
        hub_preview = ""
        if extract_hub_query(query_text, history=user_history) and not extract_player_ign(
            query_text
        ):
            try:
                hub_preview = await retrieve_rotmg_hub(
                    redis,
                    query_text,
                    cache_only=True,
                    history=user_history,
                )
            except Exception as e:
                logger.bind(error=str(e)).warning("RotMG Hub preview failed")
                hub_preview = ""
        # Skip wiki RAG only when Hub actually returned patch notes.
        # A new-item miss must still reach RealmEye.
        hub_only = bool((hub_preview or "").strip())
        dungeon_only = (
            bool(extract_dungeon_query(query_text, history=user_history))
            or bool(extract_biome_query(query_text))
        ) and not buildish
        item_scale_only = is_item_scaling_query(query_text, history=user_history)
        forge_only = is_forge_query(query_text) and not (class_name and stat)
        enchant_only = is_enchant_query(query_text) and not (class_name and stat)
        numbers_only = is_stat_number_query(query_text)
        dps_ask = is_dps_query(query_text)
        # This-turn IGN lookups stay off the wiki/DPS path even if an
        # earlier Bard/Huntress question would inherit as buildish.
        # A player's class DPS ask still has an IGN, but it is a numbers
        # turn: scrape the character inside the DPS specialist, do not
        # treat it as a fame/guild lookup.
        player_only = (not numbers_only and not dps_ask) and (
            bool(extract_player_ign(query_text))
            or (
                bool(extract_player_ign(query_text, history=user_history))
                and not this_class
            )
        )
        # Specialists already inject the right chunk. Extra wiki RAG pads
        # the bill and, if we glue on the previous user turn, mixes topics
        # (player lookup + Bard attack → off-class bows). Class+stat and
        # class-only build asks go through slot agents plus a compact
        # set-visualizer / RealmShark top-5 slice; skip the vector dump.
        if (
            dungeon_only
            or player_only
            or hub_only
            or item_scale_only
            or forge_only
            or enchant_only
            or numbers_only
            or is_skin_visualize_query(query_text, history=outfit_history)
            or is_set_visualize_query(query_text, history=visual_history)
            or is_set_followup(query_text)
            or is_stat_class_shiny_divine_query(query_text, class_name, stat)
            or (class_name and stat)
            or (buildish and class_name)
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
        set_or_skin = (
            is_skin_visualize_query(query_text, history=outfit_history)
            or is_set_visualize_query(query_text, history=visual_history)
            or is_set_followup(query_text)
            or is_stat_class_shiny_divine_query(query_text, class_name, stat)
        )
        if build_ctx:
            if (
                player_only
                or item_scale_only
                or forge_only
                or enchant_only
                or dungeon_only
                or hub_only
                or set_or_skin
            ):
                # Named sets, skins, dungeon guides, patch notes, player
                # lookups, and enchant briefs scrape RealmEye or the official
                # Hub. Stamping the RealmShark leaderboard citation on top
                # would misattribute the source.
                context = (
                    f"{context}\n\n---\n\n{build_ctx}" if context else build_ctx
                )
            else:
                citation = "Source: https://tracker.realmshark.cc/dps-leaderboards"
                block = f"{citation}\n{build_ctx}"
                context = f"{context}\n\n---\n\n{block}" if context else block
    except Exception as e:
        logger.bind(error=str(e)).warning("RealmShark build knowledge unavailable")

    system_prompt = build_system_prompt(context, ign=ign)

    # Build message history for Claude. Both the turn count and the size of
    # each turn are capped: input tokens are billed, and a long conversation
    # would otherwise grow the cost of every subsequent message.
    messages = [
        {"role": msg.role, "content": msg.content[:HISTORY_CONTENT_CAP]}
        for msg in body.history[-10:]
    ] + [{"role": "user", "content": _user_content(body, attachments)}]

    model = pick_chat_model(
        body.message,
        settings,
        history=user_history,
        context=context,
        dungeon_only=dungeon_only,
        player_only=player_only,
        has_attachment=bool(attachments),
    )
    logger.bind(
        session_id=body.session_id[:8],
        ign=ign,
        provider=settings.llm_provider,
        model=model,
        context_chunks=context.count("---") + 1 if context else 0,
    ).info("Chat stream started")

    async def _mint(reply: str) -> None:
        # Haiku used to be skipped. Found live Sep 16: "best druid
        # abilities" has enough wiki context to pick Haiku, so the first
        # essay never landed in the store and the repeat burned Claude.
        await maybe_mint_brief(
            redis,
            body.message,
            reply,
            history=user_history,
            ttl_seconds=settings.wiki_ttl_seconds,
        )

    return StreamingResponse(
        _stream_response(
            messages,
            system_prompt,
            settings,
            redis,
            mint=_mint,
            model=model,
            chat_tier="paid" if paid else ("free" if quota.scope == USER_SCOPE else "guest"),
            chat_email=(user.email if user else None),
            chat_ign=str((user.claims or {}).get("ign") or "").strip() if user else "",
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
