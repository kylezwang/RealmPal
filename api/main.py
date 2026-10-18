"""
Realm Pal | FastAPI application factory.

Intentionally small (~50 lines). All logic lives in routers and services.
Learned from Certio: never build a 4000-line main.py God file.
"""
import asyncio
import os
import sys
from contextlib import asynccontextmanager

# Windows-only fix: Playwright (used by the scraper) spawns Chromium as a
# subprocess, which asyncio can only do on Windows via ProactorEventLoop.
# uvicorn's --reload supervisor leaves the worker process on
# SelectorEventLoop, which raises NotImplementedError the moment Playwright
# tries to launch a browser. Must be set before uvicorn creates its loop, so
# this has to run at module import time, at the very top of the entrypoint.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from .config import get_settings
from .routers import admin, auth, chat, chat_sessions, players, payments, sprite, items, dungeons, skins, uploads

# loguru's logger.info(msg, key=value) does NOT attach key/value as structured
# fields | those kwargs are only used for str.format() substitution in the
# message, so they were being silently dropped everywhere in this codebase.
# Real structured data must be attached with logger.bind(...), and the sink's
# format string must actually render `{extra}` for it to show up at all.
logger.remove()
logger.add(
    sys.stderr,
    format=(
        "<green>{time:HH:mm:ss}</green> <level>{level: <8}</level> "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        " <dim>{extra}</dim>"
    ),
    colorize=True,
)


def _warn_on_unsafe_proxy_config(settings) -> None:
    """
    Uvicorn rewrites request.client.host from X-Forwarded-For by default,
    which silently overrides the proxy trust decision in
    api/services/rate_limit.py and lets callers pick their own quota bucket.
    Every launch path we ship passes --no-proxy-headers; this catches the case
    where someone re-enabled it out of band.
    """
    allow_ips = os.environ.get("FORWARDED_ALLOW_IPS")
    if allow_ips and not settings.trust_forwarded_for:
        logger.bind(forwarded_allow_ips=allow_ips).warning(
            "FORWARDED_ALLOW_IPS is set but TRUST_FORWARDED_FOR is off. If uvicorn "
            "is running without --no-proxy-headers, clients can spoof their IP and "
            "reset their own rate limit."
        )
    if settings.trust_forwarded_for:
        logger.bind(hops=settings.forwarded_proxy_hops).info(
            "Trusting X-Forwarded-For for client IP"
        )


async def _ensure_qdrant_collection(settings) -> None:
    """
    Create this deployment's collection if it's missing.

    Without this, a newly namespaced deployment has no collection, and every
    request logs a retrieval failure and answers with no context until a seed
    script happens to run. Failure here is non-fatal: chat still works, just
    without retrieval.
    """
    from .dependencies import _get_qdrant
    from .services.ingestion import ensure_collection

    try:
        client = _get_qdrant(settings.qdrant_url, settings.qdrant_api_key)
        await ensure_collection(client)
        logger.bind(collection=settings.qdrant_collection_name).info(
            "Qdrant collection ready"
        )
    except Exception as exc:
        logger.bind(
            collection=settings.qdrant_collection_name, error=str(exc)
        ).warning("Could not prepare Qdrant collection; retrieval may be degraded")


def _warn_on_default_secrets(settings) -> None:
    """
    Loud rather than silent about secrets that were never rotated.

    JWT_SECRET signs magic-link sessions and, via PII_HASH_SECRET's fallback,
    keys every rate-limit hash. Shipping the placeholder means both are
    guessable from this repo's public history, not just weak.
    """
    if settings.debug:
        return
    if settings.uses_default_jwt_secret:
        logger.warning(
            "JWT_SECRET is still the shipped placeholder. Sessions, magic links, "
            "and (via its fallback) hashed rate-limit keys are only as strong as "
            "this secret - rotate it before this deployment is publicly reachable."
        )
    if not settings.pii_hash_secret:
        logger.warning(
            "PII_HASH_SECRET is unset; quota hashing falls back to JWT_SECRET. Set "
            "it explicitly so rotating one secret doesn't silently change the other."
        )
    if settings.magic_link_secret_is_shared:
        logger.warning(
            "MAGIC_LINK_SECRET is unset; magic links are signed with JWT_SECRET, the "
            "same secret that signs every session token. A link leaked from one "
            "channel (email logs, a referrer header) then forges a session too. "
            "Set MAGIC_LINK_SECRET explicitly."
        )


def _warn_on_llm_config(settings) -> None:
    """
    Production should not call Anthropic with a key sitting in .env, and
    Foundry should use Entra rather than a Foundry API key. Local fallback
    is intentional; this only shouts when DEBUG is off.
    """
    if settings.debug:
        return
    if settings.llm_provider == "anthropic":
        logger.warning(
            "Chat is calling Anthropic directly. Production should use Foundry "
            "with FOUNDRY_USE_ENTRA so no Anthropic or Foundry key lives in the environment."
        )
        return
    if settings.foundry_auth == "api_key":
        logger.warning(
            "Foundry is authenticating with an API key. Prefer FOUNDRY_USE_ENTRA "
            "so managed identity holds the credential instead."
        )


async def _ensure_entitlements_db(settings) -> None:
    """Create the durable entitlement DB/schema if missing. Non-fatal: chat
    still falls back to trusting the JWT's `paid` claim if this can't open."""
    from .services import entitlements

    try:
        await entitlements.init_db(settings)
    except Exception as exc:
        logger.bind(path=settings.entitlements_db_path, error=str(exc)).warning(
            "Could not open the entitlements DB; paid-status revocation is degraded"
        )


async def _ensure_accounts_db(settings) -> None:
    """Create the local email+password account store if missing. Non-fatal:
    /auth/signin and /auth/register will 500 on first use if this can't open,
    but the rest of the API stays up."""
    from .services import accounts

    try:
        await accounts.init_db(settings)
    except Exception as exc:
        logger.bind(path=settings.accounts_db_path, error=str(exc)).warning(
            "Could not open the accounts DB; email+password sign-in is unavailable"
        )


async def _ensure_specialist_stores(settings) -> None:
    """Fill empty wiki/DPS specialist stores in the background.

    Chat never scrapes. A new Redis (first deploy, new namespace) starts
    empty - warm those stores once. Already-filled keys are left alone
    until the weekly refresh job. Player profiles are never warmed.
    """
    from .dependencies import _get_redis
    from .redis_namespace import namespaced
    from .services.specialist_warm import (
        has_missing_work,
        missing_specialist_work,
        specialist_snapshot,
        warm_all_specialists,
    )

    redis = namespaced(_get_redis(settings.redis_url), settings.redis_key_prefix)
    try:
        work = missing_specialist_work(await specialist_snapshot(redis))
    except Exception as exc:
        logger.bind(error=str(exc)).warning("Could not check specialist wiki stores")
        return
    if not has_missing_work(work):
        logger.info("Specialist wiki stores ready")
        return

    async def _warm() -> None:
        try:
            counts = await warm_all_specialists(
                redis,
                ttl_seconds=settings.wiki_ttl_seconds,
                force=False,
            )
            logger.bind(counts=counts).info("Warmed empty specialist wiki stores")
        except Exception as exc:
            logger.bind(error=str(exc)).warning("Background specialist warm failed")

    logger.bind(missing=work).info(
        "Specialist wiki stores missing; warming in the background"
    )
    asyncio.create_task(_warm())


async def _ensure_admin_events_db(settings) -> None:
    """Create the admin chat-cost table if missing. Non-fatal: the bell
    still lists feedback/accounts/Stripe if this store cannot open."""
    from .services import admin_events

    try:
        await admin_events.init_db(settings)
    except Exception as exc:
        logger.bind(path=settings.admin_events_db_path, error=str(exc)).warning(
            "Could not open the admin events DB; Claude-turn costs will not land"
        )


async def _ensure_uploads_db(settings) -> None:
    from .services import uploads

    try:
        await uploads.init_db(settings)
    except Exception as exc:
        logger.bind(path=settings.uploads_db_path, error=str(exc)).warning(
            "Could not open the uploads DB; image attachments will not be stored"
        )


async def _ensure_chat_sessions_db(settings) -> None:
    """Create chat_sessions and widen leftover int32 timestamp columns.

    Found live Sep 18: POST /chat/sessions/sync 500ed because updated_at
    is a millisecond Date.now() value and Postgres INTEGER is int32.
    """
    from .services import chat_sessions

    try:
        await chat_sessions.init_db(settings)
    except Exception as exc:
        logger.bind(path=settings.chat_sessions_db_path, error=str(exc)).warning(
            "Could not open the chat sessions DB; signed-in history will not sync"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.bind(
        debug=settings.debug,
        model=settings.claude_model,
        llm_provider=settings.llm_provider,
        foundry_auth=settings.foundry_auth or "n/a",
        auth=settings.auth_provider or "anonymous",
        namespace=settings.namespace_slug or "none",
    ).info("Realm Pal API starting")
    _warn_on_unsafe_proxy_config(settings)
    _warn_on_llm_config(settings)
    _warn_on_default_secrets(settings)
    await _ensure_qdrant_collection(settings)
    await _ensure_entitlements_db(settings)
    await _ensure_accounts_db(settings)
    await _ensure_admin_events_db(settings)
    await _ensure_uploads_db(settings)
    await _ensure_chat_sessions_db(settings)
    await _ensure_specialist_stores(settings)
    yield
    logger.info("Realm Pal API shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Realm Pal API",
        description="RotMG AI companion | RAG pipeline powered by Claude via Microsoft Foundry",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(chat.router)
    app.include_router(chat_sessions.router)
    app.include_router(players.router)
    app.include_router(payments.router)
    app.include_router(sprite.router)
    app.include_router(items.router)
    app.include_router(dungeons.router)
    app.include_router(skins.router)
    app.include_router(uploads.router)

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "model": settings.claude_model,
            "provider": settings.llm_provider,
        }

    return app


app = create_app()
