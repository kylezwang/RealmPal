"""
Realm Pal | FastAPI application factory.

Intentionally small (~50 lines). All logic lives in routers and services.
Learned from Certio: never build a 4000-line main.py God file.
"""
import asyncio
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.bind(debug=settings.debug, model=settings.claude_model).info("Realm Pal API starting")
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
