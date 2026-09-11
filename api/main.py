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
from .routers import chat, players, payments, sprite, items, dungeons, skins

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.bind(
        debug=settings.debug,
        model=settings.claude_model,
        auth=settings.auth_provider or "anonymous",
        namespace=settings.namespace_slug or "none",
    ).info("Realm Pal API starting")
    _warn_on_unsafe_proxy_config(settings)
    await _ensure_qdrant_collection(settings)
    yield
    logger.info("Realm Pal API shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Realm Pal API",
        description="RotMG AI companion | RAG pipeline powered by Claude",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.app_url, "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(chat.router)
    app.include_router(players.router)
    app.include_router(payments.router)
    app.include_router(sprite.router)
    app.include_router(items.router)
    app.include_router(dungeons.router)
    app.include_router(skins.router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "model": settings.claude_model}

    return app


app = create_app()
