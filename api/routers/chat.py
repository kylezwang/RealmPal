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
import uuid
from datetime import datetime, timezone
from typing import Annotated, AsyncGenerator, Optional

import stripe
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from qdrant_client import AsyncQdrantClient

import redis.asyncio as aioredis

from ..config import Settings, get_settings
from ..dependencies import get_redis, get_qdrant
from ..models.chat import (
    ChatAttachment,
    ChatRequest,
    FeedbackRequest,
    FeedbackResponse,
    PaywallResponse,
    UsageResponse,
)
from ..models.build import CLASS_ABILITY_HUB, STAT_RING_HUB
from ..services.rag import build_system_prompt, retrieve_context
from ..services.scraper import scrape_player_profile, ScraperError
from ..services.ingestion import ingest_player
from ..services.realmshark import parse_query, retrieve_build_knowledge
from ..auth import decode_jwt

router = APIRouter(prefix="/chat", tags=["chat"])

RATE_LIMIT_TTL = 60 * 60 * 24  # 24 hours
FEEDBACK_LOG_MAX = 10_000
RESPONSE_CAP = 20_000
TEXT_CAP = 4_000
MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024
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


def _rate_limit_key(session_id: str) -> str:
    return f"ratelimit:{session_id}"


async def _used_count(redis: aioredis.Redis, session_id: str) -> int:
    raw = await redis.get(_rate_limit_key(session_id))
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


async def _check_rate_limit(
    session_id: str,
    redis: aioredis.Redis,
    settings: Settings,
    auth_header: Optional[str],
) -> None:
    """
    Raise HTTP 402 if the session has exceeded the free message limit.
    Paid users (valid JWT in Authorization header) bypass the check.
    """
    # Paid users bypass rate limit
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
        try:
            decode_jwt(token, settings.jwt_secret, settings.jwt_algorithm)
            return  # Valid paid user | no limit
        except Exception:
            pass  # Invalid token | fall through to rate limit

    key = _rate_limit_key(session_id)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, RATE_LIMIT_TTL)

    if count > settings.free_message_limit:
        # Create Stripe checkout URL if configured
        checkout_url = None
        if settings.stripe_secret_key and settings.stripe_price_id:
            try:
                stripe.api_key = settings.stripe_secret_key
                session = stripe.checkout.Session.create(
                    mode="subscription",
                    payment_method_types=["card"],
                    line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
                    success_url=f"{settings.app_url}?upgraded=true",
                    cancel_url=settings.app_url,
                    metadata={"session_id": session_id},
                )
                checkout_url = session.url
            except Exception:
                logger.exception("Failed to create Stripe checkout session")

        limit = settings.free_message_limit
        remaining = max(0, limit - count)
        raise HTTPException(
            status_code=402,
            detail=PaywallResponse(
                checkout_url=checkout_url,
                used=min(count, limit),
                limit=limit,
                remaining=remaining,
            ).model_dump(),
        )


async def _stream_response(
    messages: list[dict],
    system_prompt: str,
    settings: Settings,
) -> AsyncGenerator[str, None]:
    """
    Stream Claude response as SSE chunks.
    Yields: `data: {"content": "...", "done": false}\n\n`
    Final: `data: {"content": "", "done": true}\n\n`
    """
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        async with client.messages.stream(
            model=settings.claude_model,
            max_tokens=8192,
            system=system_prompt,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                chunk = json.dumps({"content": text, "done": False})
                yield f"data: {chunk}\n\n"

        yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"

    except Exception as e:
        logger.bind(error=str(e)).error("Error during Claude streaming")
        error_chunk = json.dumps({"error": "Claude stream failed", "done": True})
        yield f"data: {error_chunk}\n\n"


@router.get("/usage")
async def chat_usage(
    session_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> UsageResponse:
    """How many free messages this guest session has used / has left."""
    if not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id is required")
    try:
        used = await _used_count(redis, session_id)
    except Exception:
        logger.exception("Failed to read chat usage")
        raise HTTPException(status_code=503, detail="Usage unavailable")
    limit = settings.free_message_limit
    return UsageResponse(used=used, limit=limit, remaining=max(0, limit - used))


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
    authorization: Annotated[Optional[str], Header()] = None,
) -> StreamingResponse:
    """Stream a chat response. Enforces rate limit for non-paid sessions."""

    if not body.message.strip() and body.attachment is None:
        raise HTTPException(status_code=400, detail="Message is empty")
    if body.attachment is not None:
        _validate_attachment(body.attachment)

    await _check_rate_limit(body.session_id, redis, settings, authorization)

    # Auto-scrape player if IGN provided and not in Qdrant
    if body.ign:
        ign_key = f"scraped:player:{body.ign.lower()}"
        if not await redis.exists(ign_key):
            try:
                profile = await scrape_player_profile(body.ign)
                await ingest_player(qdrant, profile)
                await redis.setex(ign_key, settings.scrape_ttl_hours * 3600, "1")
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
    try:
        query_text = body.message.strip()
        if not query_text and body.attachment is not None:
            query_text = body.attachment.filename
        class_name, stat, _ = parse_query(query_text, history=user_history)
        rag_query = " ".join(
            part
            for part in (
                class_name,
                stat,
                user_history[-1] if user_history else "",
                query_text,
            )
            if part
        )
        exclude_rings = [
            slug
            for other, slug in STAT_RING_HUB.items()
            if stat and other != stat
        ]
        context = await retrieve_context(
            qdrant, rag_query, exclude_url_substrings=exclude_rings
        )
        if class_name:
            hub = CLASS_ABILITY_HUB.get(class_name, "")
            extra_q = " ".join(
                part for part in (class_name, hub, stat, "ability scaling") if part
            )
            extra = await retrieve_context(
                qdrant, extra_q, exclude_url_substrings=exclude_rings
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
            ttl_seconds=settings.scrape_ttl_hours * 3600,
            history=history_texts,
        )
        if build_ctx:
            citation = "Source: https://tracker.realmshark.cc/dps-leaderboards"
            block = f"{citation}\n{build_ctx}"
            context = f"{context}\n\n---\n\n{block}" if context else block
    except Exception as e:
        logger.bind(error=str(e)).warning("RealmShark build knowledge unavailable")

    system_prompt = build_system_prompt(context, ign=body.ign)

    # Build message history for Claude
    messages = [
        {"role": msg.role, "content": msg.content}
        for msg in body.history[-10:]  # last 10 messages for context window
    ] + [{"role": "user", "content": body.message}]

    logger.bind(
        session_id=body.session_id[:8],
        ign=body.ign,
        context_chunks=context.count("---") + 1 if context else 0,
    ).info("Chat stream started")

    return StreamingResponse(
        _stream_response(messages, system_prompt, settings),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
