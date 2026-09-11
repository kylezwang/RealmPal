"""
Item lookup endpoint.

GET /items/{name}
  - Redis-cached scrape of the item's RealmEye wiki page
  - Also ingested into Qdrant so later chat answers have the real stats
"""
from typing import Annotated, Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from qdrant_client import AsyncQdrantClient

from ..config import Settings, get_settings
from ..dependencies import get_redis, get_qdrant
from ..models.item import ItemProfile
from ..services.item_aliases import resolve_item_query
from ..services.scraper import scrape_item, ScraperError
from ..services.ingestion import ingest_item

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/{name}", response_model=ItemProfile)
async def get_item(
    name: str,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    qdrant: Annotated[AsyncQdrantClient, Depends(get_qdrant)],
    class_name: Optional[str] = Query(None),
) -> ItemProfile:
    """Look up an item by wiki name or nickname. Scrapes on demand with TTL caching."""
    if "/" in name or "realmeye.com" in name.lower() or name.lower().startswith("http"):
        raise HTTPException(status_code=404, detail="Not an item name")
    ttl = settings.scrape_ttl_hours * 3600
    cache_key = f"item:profile:v2:{name.lower()}"
    cached_json = await redis.get(cache_key)
    if cached_json:
        return ItemProfile.model_validate_json(cached_json)

    lookup = name
    try:
        resolved = await resolve_item_query(
            redis,
            name,
            ttl_seconds=ttl,
            class_name=class_name,
            allow_scrape=True,
        )
        if resolved:
            lookup = resolved
            resolved_key = f"item:profile:v2:{resolved.lower()}"
            cached_resolved = await redis.get(resolved_key)
            if cached_resolved:
                item = ItemProfile.model_validate_json(cached_resolved)
                await redis.setex(cache_key, ttl, cached_resolved)
                return item
    except Exception as e:
        logger.bind(item_name=name, error=str(e)).warning(
            "Item nickname resolve failed; trying the typed name"
        )

    try:
        item = await scrape_item(lookup)
    except ScraperError as e:
        if lookup.lower() != name.lower():
            try:
                item = await scrape_item(name)
            except ScraperError:
                raise HTTPException(status_code=404, detail=str(e)) from e
        else:
            raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        await ingest_item(qdrant, item)
    except Exception as e:
        logger.bind(item_name=name, error=str(e)).warning(
            "Could not ingest item profile into RAG store"
        )

    payload = item.model_dump_json()
    await redis.setex(cache_key, ttl, payload)
    if item.name.lower() != name.lower():
        await redis.setex(f"item:profile:v2:{item.name.lower()}", ttl, payload)
    logger.bind(item_name=item.name, query=name).info("Item profile fetched and cached")
    return item
