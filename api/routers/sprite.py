"""
Resolve item sprites for inline chat rendering ([sprite:Item Name] tokens).

The frontend proxies /api/sprite -> /sprite here. We scrape the item's
RealmEye wiki page once, cache the sprite URL in Redis, then redirect.

GET /sprite/crop returns a standalone PNG cell from a RealmEye sheet so the
browser tab icon can show a pet without a CORS-tainted canvas.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Annotated

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, Response
from loguru import logger

from ..config import Settings, get_settings
from ..dependencies import enforce_lookup_rate_limit, get_redis
from ..services.scraper import scrape_item, ScraperError
from ..services.sprite_crop import SpriteCropError, fetch_and_crop_sprite
from ..services.validation import sanitize_lookup_name
from ..services.rotmg_hub import hub_sprite_url
from ..services.wiki_scaling import (
    is_item_marked_missing,
    mark_item_missing,
    read_cached_item,
    write_cached_item,
)

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
        # See items.py's get_item for why this exists: a real item can have
        # no RealmEye wiki page yet, and without this every sprite request
        # for it re-pays the full scrape timeout instead of failing fast.
        if await is_item_marked_missing(redis, name):
            hub_url = await hub_sprite_url(redis, name)
            if hub_url:
                ttl = settings.pet_sprite_ttl_days * 86400
                await redis.setex(cache_key, ttl, hub_url)
                return RedirectResponse(hub_url, status_code=302)
            raise HTTPException(
                status_code=404, detail=f"{name} has no RealmEye wiki page yet"
            )
        try:
            item = await scrape_item(name)
        except ScraperError as e:
            hub_url = await hub_sprite_url(redis, name)
            if hub_url:
                ttl = settings.pet_sprite_ttl_days * 86400
                await redis.setex(cache_key, ttl, hub_url)
                return RedirectResponse(hub_url, status_code=302)
            await mark_item_missing(redis, name, settings.missing_item_ttl_seconds)
            raise HTTPException(status_code=404, detail=str(e)) from e
        await write_cached_item(redis, item, settings.wiki_ttl_seconds, name)

    if not item.sprite_url:
        hub_url = await hub_sprite_url(redis, name)
        if hub_url:
            ttl = settings.pet_sprite_ttl_days * 86400
            await redis.setex(cache_key, ttl, hub_url)
            return RedirectResponse(hub_url, status_code=302)
        raise HTTPException(status_code=404, detail=f"No sprite found for '{name}'")

    ttl = settings.pet_sprite_ttl_days * 86400
    await redis.setex(cache_key, ttl, item.sprite_url)
    logger.bind(item_name=name).debug("Cached item sprite URL")
    return RedirectResponse(item.sprite_url, status_code=302)


@router.get("/sprite/crop")
async def crop_sheet_sprite(
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    sheet: Annotated[str, Query(min_length=12, max_length=400)],
    x: Annotated[int, Query(ge=0, le=4096)],
    y: Annotated[int, Query(ge=0, le=4096)],
    size: Annotated[int, Query(ge=1, le=256)],
) -> Response:
    """Standalone PNG of one sheet cell for the browser tab icon."""
    digest = hashlib.sha256(f"{sheet}|{x}|{y}|{size}".encode()).hexdigest()
    cache_key = f"sprite:crop:{digest}"
    cached = await redis.get(cache_key)
    if cached:
        try:
            return Response(
                content=base64.b64decode(cached),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"},
            )
        except Exception:
            pass

    try:
        png = await fetch_and_crop_sprite(sheet, x, y, size)
    except SpriteCropError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail="could not fetch sprite sheet") from e

    ttl = settings.pet_sprite_ttl_days * 86400
    await redis.setex(cache_key, ttl, base64.b64encode(png).decode("ascii"))
    logger.bind(x=x, y=y, size=size).debug("Cropped sprite sheet cell")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
