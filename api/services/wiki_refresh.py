"""
Weekly RealmEye wiki refresh.

Hubs and item/dungeon pages barely change. Specialists should read the
Qdrant/Redis corpus instead of launching Chromium on every chat turn.
This job re-scrapes the seeded hubs and stamps Redis so you can see when
the last pass ran. It never scrapes player profiles — those stay on the
live on-request path with a short TTL.
"""
from __future__ import annotations

import time

import redis.asyncio as aioredis
from qdrant_client import AsyncQdrantClient

from ..config import Settings
from .ingestion import seed_wiki_hubs
from .specialist_warm import warm_all_specialists
from .stored_answers import invalidate_briefs

LAST_REFRESH_KEY = "wiki:last_refresh"


async def refresh_wiki_corpus(
    client: AsyncQdrantClient,
    redis: aioredis.Redis,
    settings: Settings,
    slugs: tuple[str, ...] | None = None,
) -> dict:
    counts = await seed_wiki_hubs(client, slugs) if slugs else await seed_wiki_hubs(client)
    specialists = await warm_all_specialists(
        redis, ttl_seconds=settings.wiki_ttl_seconds, force=True
    )
    await invalidate_briefs(redis)
    now = int(time.time())
    await redis.set(LAST_REFRESH_KEY, str(now))
    return {
        "hubs": counts,
        "specialists": specialists,
        "refreshed_at": now,
        "next_due_at": now + settings.wiki_ttl_seconds,
    }


async def wiki_refresh_due(redis: aioredis.Redis, settings: Settings) -> bool:
    raw = await redis.get(LAST_REFRESH_KEY)
    if not raw:
        return True
    try:
        last = int(raw)
    except (TypeError, ValueError):
        return True
    return time.time() - last >= settings.wiki_ttl_seconds
