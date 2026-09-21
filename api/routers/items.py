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
from ..services.item_aliases import (
    MAX_PLAUSIBLE_ITEM_NAME_WORDS,
    resolve_item_query,
    resolve_item_query_with_trim,
    suggest_terms,
)
from ..services.scraper import scrape_item, ScraperError
from ..services.ingestion import ingest_item
from ..services.validation import sanitize_lookup_name
from ..services.class_gear import class_can_wear_item
from ..services.enchanting import awakened_enchant_text
from ..services.rotmg_hub import HUB_UPDATES_URL, hub_sprite_url
from ..services.wiki_scaling import (
    is_item_marked_missing,
    mark_item_missing,
    read_cached_item,
    write_cached_item,
)

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/suggest")
async def suggest_items(
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    q: str = Query("", min_length=0, max_length=80),
) -> list[dict[str, str]]:
    """Tab-complete warmed item and dungeon names as the user types."""
    return await suggest_terms(redis, q)


async def _with_wearable(
    redis: aioredis.Redis,
    item: ItemProfile,
    class_name: Optional[str],
    *,
    ttl_seconds: int = 0,
) -> ItemProfile:
    updates: dict = {}
    if class_name:
        updates["wearable"] = await class_can_wear_item(redis, class_name, item.name)
    if ttl_seconds:
        try:
            awakened = await awakened_enchant_text(
                redis, item.name, ttl_seconds=ttl_seconds
            )
        except Exception:
            awakened = None
        if awakened:
            updates["awakened_enchant"] = awakened
    if not updates:
        return item
    return item.model_copy(update=updates)


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
        return await _with_wearable(redis, cached, class_name, ttl_seconds=ttl)

    lookup = name
    resolved: Optional[str] = None
    try:
        resolved = await resolve_item_query(
            redis,
            name,
            ttl_seconds=ttl,
            class_name=class_name,
            allow_scrape=False,
        )
        if not resolved:
            # Durable fix (found live Sep 14, repeatedly): a caller can hand
            # this endpoint free text glued around a real item name (a chat
            # reply's regex-based item extraction, or a stray follow-up
            # question caught by the same pattern) rather than a clean typed
            # name. resolve_item_query alone requires the *whole* string to
            # match, so "snake eye ring is the awakened enchantment good"
            # (a real, catalog-known ring plus an unrelated trailing
            # question with no clean punctuation boundary) resolved to
            # nothing and fell straight through to scrape_item() with that
            # entire string as a literal wiki slug - guaranteed 404 after a
            # ~30s two-attempt timeout, on every single repeat of the same
            # broken message. Retrying against progressively shorter
            # prefixes finds the real item inside without needing to know in
            # advance which trailing words were never part of the name. See
            # resolve_item_query_with_trim's docstring for the full
            # reasoning.
            resolved = await resolve_item_query_with_trim(
                redis, name, ttl_seconds=ttl, class_name=class_name
            )
        if resolved:
            lookup = resolved
            cached_resolved = await read_cached_item(redis, resolved)
            if cached_resolved:
                await write_cached_item(redis, cached_resolved, ttl, name)
                return await _with_wearable(
                    redis, cached_resolved, class_name, ttl_seconds=ttl
                )
    except Exception as e:
        logger.bind(item_name=name, error=str(e)).warning(
            "Item nickname resolve failed; trying the typed name"
        )

    if not resolved and len(name.split()) > MAX_PLAUSIBLE_ITEM_NAME_WORDS:
        # Too long to plausibly be a real item name (see
        # MAX_PLAUSIBLE_ITEM_NAME_WORDS) and nothing in the known item
        # catalog matches any prefix of it either - this is free text that
        # was never an item name, not a not-yet-cataloged one. Reject
        # immediately: no lookup quota charge, no scrape attempt, no ~30s
        # wait for a page that could never have existed.
        raise HTTPException(status_code=404, detail="Not an item name")

    # Some real, correctly-named items (a fresh RealmShark leaderboard entry,
    # e.g. Rift Rippers) genuinely have no RealmEye wiki page yet. Without
    # this, every lookup paid a full two-attempt Playwright timeout (~30s)
    # even though the previous lookup already learned the page doesn't
    # exist. Checked (and charged no lookup quota) before the scrape below;
    # short TTL means it starts resolving again once RealmEye publishes it.
    if await is_item_marked_missing(redis, lookup):
        hub_url = await hub_sprite_url(redis, lookup)
        if hub_url:
            stub = ItemProfile(name=lookup, sprite_url=hub_url, wiki_url=HUB_UPDATES_URL)
            return await _with_wearable(redis, stub, class_name, ttl_seconds=ttl)
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
                hub_url = await hub_sprite_url(redis, lookup)
                if hub_url:
                    stub = ItemProfile(
                        name=lookup, sprite_url=hub_url, wiki_url=HUB_UPDATES_URL
                    )
                    return await _with_wearable(
                        redis, stub, class_name, ttl_seconds=ttl
                    )
                await mark_item_missing(redis, lookup, settings.missing_item_ttl_seconds)
                await mark_item_missing(redis, name, settings.missing_item_ttl_seconds)
                raise HTTPException(status_code=404, detail=str(e)) from e
        else:
            hub_url = await hub_sprite_url(redis, name)
            if hub_url:
                stub = ItemProfile(name=name, sprite_url=hub_url, wiki_url=HUB_UPDATES_URL)
                return await _with_wearable(redis, stub, class_name, ttl_seconds=ttl)
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
    return await _with_wearable(redis, item, class_name, ttl_seconds=ttl)
