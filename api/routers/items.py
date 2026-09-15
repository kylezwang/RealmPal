"""
Item lookup endpoint.

GET /items/{name}
  - Redis-cached scrape of the item's RealmEye wiki page
  - Also ingested into Qdrant so later chat answers have the real stats
"""
from typing import Annotated, Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from qdrant_client import AsyncQdrantClient

from ..config import Settings, get_settings
from ..dependencies import consume_lookup_quota, get_optional_user, get_redis, get_qdrant
from ..identity import AuthenticatedUser
from ..models.item import ItemProfile
from ..services.item_aliases import resolve_item_query
from ..services.scraper import scrape_item, ScraperError
from ..services.ingestion import ingest_item
from ..services.validation import sanitize_lookup_name
from ..services.class_gear import class_can_wear_item
from ..services.wiki_scaling import (
    is_item_marked_missing,
    mark_item_missing,
    read_cached_item,
    write_cached_item,
)

router = APIRouter(prefix="/items", tags=["items"])


async def _with_wearable(
    redis: aioredis.Redis,
    item: ItemProfile,
    class_name: Optional[str],
) -> ItemProfile:
    if not class_name:
        return item
    ok = await class_can_wear_item(redis, class_name, item.name)
    return item.model_copy(update={"wearable": ok})


@router.get("/{name}", response_model=ItemProfile)
async def get_item(
    name: str,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    qdrant: Annotated[AsyncQdrantClient, Depends(get_qdrant)],
    request: Request,
    class_name: Optional[str] = Query(None),
    user: Annotated[Optional[AuthenticatedUser], Depends(get_optional_user)] = None,
) -> ItemProfile:
    """Look up an item by wiki name or nickname. Scrapes on demand with TTL caching."""
    name = sanitize_lookup_name(name, field="name")
    if not isinstance(class_name, str):
        class_name = None
    if "realmeye.com" in name.lower() or name.lower().startswith("http"):
        raise HTTPException(status_code=404, detail="Not an item name")
    ttl = settings.wiki_ttl_seconds
    cached = await read_cached_item(redis, name)
    if cached:
        return await _with_wearable(redis, cached, class_name)

    lookup = name
    try:
        resolved = await resolve_item_query(
            redis,
            name,
            ttl_seconds=ttl,
            class_name=class_name,
            allow_scrape=False,
        )
        if resolved:
            lookup = resolved
            cached_resolved = await read_cached_item(redis, resolved)
            if cached_resolved:
                await write_cached_item(redis, cached_resolved, ttl, name)
                return await _with_wearable(redis, cached_resolved, class_name)
    except Exception as e:
        logger.bind(item_name=name, error=str(e)).warning(
            "Item nickname resolve failed; trying the typed name"
        )

    # Some real, correctly-named items (a fresh RealmShark leaderboard entry,
    # e.g. Rift Rippers) genuinely have no RealmEye wiki page yet. Without
    # this, every lookup paid a full two-attempt Playwright timeout (~30s)
    # even though the previous lookup already learned the page doesn't
    # exist. Checked (and charged no lookup quota) before the scrape below;
    # short TTL means it starts resolving again once RealmEye publishes it.
    if await is_item_marked_missing(redis, lookup):
        raise HTTPException(
            status_code=404, detail=f"{lookup} has no RealmEye wiki page yet"
        )

    await consume_lookup_quota(request, settings, redis, user)

    try:
        item = await scrape_item(lookup)
    except ScraperError as e:
        if lookup.lower() != name.lower():
            try:
                item = await scrape_item(name)
            except ScraperError:
                await mark_item_missing(redis, lookup, settings.missing_item_ttl_seconds)
                await mark_item_missing(redis, name, settings.missing_item_ttl_seconds)
                raise HTTPException(status_code=404, detail=str(e)) from e
        else:
            await mark_item_missing(redis, name, settings.missing_item_ttl_seconds)
            raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        await ingest_item(qdrant, item)
    except Exception as e:
        logger.bind(item_name=name, error=str(e)).warning(
            "Could not ingest item profile into RAG store"
        )

    await write_cached_item(redis, item, ttl, name, lookup)
    logger.bind(item_name=item.name, query=name).info("Item profile fetched and cached")
    return await _with_wearable(redis, item, class_name)
