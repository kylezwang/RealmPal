"""
Resolve item sprites for inline chat rendering ([sprite:Item Name] tokens).

The frontend proxies /api/sprite -> /sprite here. We scrape the item's
RealmEye wiki page once, cache the sprite URL in Redis, then redirect.
"""
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from loguru import logger

from ..config import Settings, get_settings
from ..dependencies import enforce_lookup_rate_limit, get_redis
from ..services.scraper import scrape_item, ScraperError
from ..services.validation import sanitize_lookup_name
from ..services.wiki_scaling import read_cached_item, write_cached_item

router = APIRouter(tags=["sprite"])


@router.get("/sprite", dependencies=[Depends(enforce_lookup_rate_limit)])
async def get_item_sprite(
    name: str,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> RedirectResponse:
    """Redirect to the RealmEye wiki sprite for an item by name."""
    name = sanitize_lookup_name(name, field="name")
    cache_key = f"sprite:{name.lower()}"
    cached = await redis.get(cache_key)
    if cached:
        return RedirectResponse(cached, status_code=302)

    item = await read_cached_item(redis, name)
    if item is None or not item.sprite_url:
        try:
            item = await scrape_item(name)
        except ScraperError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        await write_cached_item(redis, item, settings.wiki_ttl_seconds, name)

    if not item.sprite_url:
        raise HTTPException(status_code=404, detail=f"No sprite found for '{name}'")

    ttl = settings.pet_sprite_ttl_days * 86400
    await redis.setex(cache_key, ttl, item.sprite_url)
    logger.bind(item_name=name).debug("Cached item sprite URL")
    return RedirectResponse(item.sprite_url, status_code=302)
