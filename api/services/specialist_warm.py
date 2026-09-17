"""Warm every wiki/DPS specialist store the same way class abilities are.

Chat only reads Redis. This module fills empty keys on deploy and the
weekly refresh force-scrapes them. Player profiles are never warmed.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

import redis.asyncio as aioredis
from loguru import logger

from ..models.build import CLASS_ABILITY_HUB, CLASS_ARMOR_HUB, STAT_RING_HUB
from .dungeon_guide import INDEX_CACHE_KEY, PAGE_CACHE_PREFIX, get_or_scrape_index, get_or_scrape_wiki
from .biomes import biome_index_entries
from .enchanting import enchanting_store_status, warm_enchanting_store
from .ingestion import WIKI_HUB_SLUGS
from .item_aliases import load_item_catalog
from .realmshark import GRAPH_CACHE_KEY, load_graph, load_top_loadouts
from .skin_visualizer import CATALOG_KEY, load_outfit_catalog
from .wiki_scaling import (
    CACHE_PREFIX,
    HUB_PREFIX,
    ITEM_CACHE_PREFIX,
    LEGACY_ITEM_CACHE_PREFIX,
    RINGS_HUB,
    _SKIP_NAME,
    _hub_index,
    _profiles_for_names,
    _tier_bucket,
    item_name_keys,
    retrieve_umi_bis,
    specialist_store_status,
    warm_all_class_scaling,
    UMI_BIS_PREFIX,
)

UMI_PREFIX = UMI_BIS_PREFIX
LOADOUT_PREFIX = "dps:top:"
ITEM_CHUNK = 25
# Category pages, not item tables. Warm the index; do not scrape every link.
INDEX_HUB_SLUGS = frozenset({"weapons", "ability-items", "armor", "enchanting"})
# Wiki pages that never render `.wiki-page`. Counting them as missing
# restarts a scrape on every boot.
DEAD_WIKI_ITEMS = frozenset({"babel blocks"})
_REHEARSAL = re.compile(r"\(rehearsal\)", re.I)
_DOTTED_ACRONYM = re.compile(r"(?:[A-Za-z]\.){2,}")

REQUIRED_HUB_SLUGS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            *WIKI_HUB_SLUGS,
            *STAT_RING_HUB.values(),
            *CLASS_ABILITY_HUB.values(),
            *CLASS_ARMOR_HUB.values(),
            RINGS_HUB,
        )
    )
)


def _count_json_list(raw: Optional[bytes | str]) -> int:
    if not raw:
        return 0
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return len(data.get("abilities") or data.get("classes") or data.get("edges") or [])
    return 0


async def hub_store_status(redis: aioredis.Redis) -> list[dict]:
    rows: list[dict] = []
    for slug in REQUIRED_HUB_SLUGS:
        key = f"{HUB_PREFIX}:{slug}"
        raw = await redis.get(key)
        ttl = await redis.ttl(key)
        rows.append(
            {
                "slug": slug,
                "items": _count_json_list(raw),
                "ttl_seconds": max(0, int(ttl or 0)),
            }
        )
    return rows


async def warm_hub_indexes(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    force: bool = False,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for slug in REQUIRED_HUB_SLUGS:
        try:
            rows = await _hub_index(redis, slug, ttl_seconds, force=force)
            counts[slug] = len(rows)
        except Exception as e:
            logger.bind(slug=slug, error=str(e)).warning("Could not warm wiki hub")
            counts[slug] = 0
    return counts


def should_warm_item(row: dict) -> bool:
    """T7 / ST / UT only. Skip T0–T6, rehearsal clones, and dotted acronyms."""
    name = (row.get("name") or "").strip()
    if not name or _SKIP_NAME.search(name):
        return False
    if name.lower() in DEAD_WIKI_ITEMS:
        return False
    if _REHEARSAL.search(name) or _DOTTED_ACRONYM.search(name):
        return False
    bucket = _tier_bucket(row)
    if bucket in {"t7", "st", "ut"}:
        return True
    # Blank-tier UTs (Chrysalis) have no T-number on the hub row.
    return not (row.get("tier") or "").strip()


async def _hub_item_names(redis: aioredis.Redis) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for slug in REQUIRED_HUB_SLUGS:
        if slug in INDEX_HUB_SLUGS:
            continue
        raw = await redis.get(f"{HUB_PREFIX}:{slug}")
        if not raw:
            continue
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for row in rows:
            name = (row.get("name") or "").strip()
            key = name.lower()
            if not name or key in seen or not should_warm_item(row):
                continue
            seen.add(key)
            names.append(name)
    return names


async def _item_profile_exists(redis: aioredis.Redis, name: str) -> bool:
    for key in item_name_keys(name):
        if await redis.exists(f"{ITEM_CACHE_PREFIX}:{key}"):
            return True
        if await redis.exists(f"{LEGACY_ITEM_CACHE_PREFIX}:{key}"):
            return True
    return False


async def item_store_status(redis: aioredis.Redis) -> dict[str, int]:
    names = await _hub_item_names(redis)
    cached = 0
    for name in names:
        if await _item_profile_exists(redis, name):
            cached += 1
    return {"cached": cached, "total": len(names)}


async def warm_item_profiles(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    force: bool = False,
) -> dict[str, int]:
    names = await _hub_item_names(redis)
    stored = 0
    for i in range(0, len(names), ITEM_CHUNK):
        chunk = names[i : i + ITEM_CHUNK]
        try:
            profiles = await _profiles_for_names(
                redis, chunk, ttl_seconds, force=force
            )
            stored += len(profiles)
        except Exception as e:
            logger.bind(error=str(e), offset=i).warning("Item profile warm chunk failed")
            if "connection closed" in str(e).lower():
                logger.warning("Playwright died; leaving remaining item pages for the next warm")
                break
    return {"cached": stored, "total": len(names)}


async def dungeon_store_status(redis: aioredis.Redis) -> dict[str, int]:
    raw = await redis.get(INDEX_CACHE_KEY)
    entries = []
    if raw:
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError:
            entries = []
    slugs = {(entry.get("slug") or "") for entry in entries if entry.get("slug")}
    cached = 0
    for slug in slugs:
        if await redis.exists(f"{PAGE_CACHE_PREFIX}{slug}"):
            cached += 1
    return {"cached": cached, "total": len(slugs), "index": 1 if entries else 0}


async def warm_dungeon_guides(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    force: bool = False,
) -> dict[str, int]:
    try:
        entries = await get_or_scrape_index(
            redis, ttl_seconds=ttl_seconds, force=force
        )
    except Exception as e:
        logger.bind(error=str(e)).warning("Could not warm dungeon index")
        return {"cached": 0, "total": 0, "index": 0}
    slugs = []
    seen: set[str] = set()
    for entry in entries:
        slug = (entry.get("slug") or "").strip()
        if slug and slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    cached = 0
    for slug in slugs:
        try:
            page = await get_or_scrape_wiki(
                redis, slug, ttl_seconds=ttl_seconds, force=force
            )
            if page:
                cached += 1
        except Exception as e:
            logger.bind(slug=slug, error=str(e)).warning("Could not warm dungeon page")
    return {"cached": cached, "total": len(slugs), "index": 1}


async def warm_biome_pages(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    force: bool = False,
) -> dict[str, int]:
    """Five veteran biome wiki pages. Always cheap enough to fill on boot."""
    cached = 0
    rows = biome_index_entries()
    for entry in rows:
        try:
            page = await get_or_scrape_wiki(
                redis,
                entry["slug"],
                ttl_seconds=ttl_seconds,
                force=force,
            )
            if page:
                cached += 1
        except Exception as e:
            logger.bind(slug=entry.get("slug"), error=str(e)).warning(
                "Could not warm biome page"
            )
    return {"cached": cached, "total": len(rows)}


async def dps_store_status(redis: aioredis.Redis) -> dict[str, int]:
    raw = await redis.get(GRAPH_CACHE_KEY)
    edges = 0
    if raw:
        try:
            payload = json.loads(raw)
            edges = len(payload.get("edges") or [])
        except json.JSONDecodeError:
            edges = 0
    cached = 0
    async for _key in redis.scan_iter(match=f"{LOADOUT_PREFIX}*", count=100):
        cached += 1
    return {"graph": 1 if raw else 0, "loadouts": cached, "edges": edges}


async def warm_dps_boards(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    force: bool = False,
) -> dict[str, int]:
    graph = await load_graph(redis, ttl_seconds, force=force)
    loadouts = 0
    for edge in graph.edges:
        try:
            rows = await load_top_loadouts(
                redis, edge, season=graph.season, ttl_seconds=ttl_seconds, force=force
            )
            if rows:
                loadouts += 1
        except Exception as e:
            logger.bind(build=edge.build_id, error=str(e)).warning(
                "Could not warm DPS loadout"
            )
    return {"graph": 1 if graph.edges or graph.season else 0, "loadouts": loadouts, "edges": len(graph.edges)}


async def umi_store_status(redis: aioredis.Redis) -> list[dict]:
    rows: list[dict] = []
    for class_name in CLASS_ABILITY_HUB:
        key = f"{UMI_PREFIX}{class_name.lower()}"
        raw = await redis.get(key)
        ttl = await redis.ttl(key)
        rows.append(
            {
                "class_name": class_name,
                "stored": 1 if raw else 0,
                "ttl_seconds": max(0, int(ttl or 0)),
            }
        )
    return rows


async def warm_umi_bis(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    force: bool = False,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for class_name in CLASS_ABILITY_HUB:
        key = f"{UMI_PREFIX}{class_name.lower()}"
        if not force and await redis.get(key):
            counts[class_name] = 1
            continue
        try:
            text = await retrieve_umi_bis(
                redis, class_name, ttl_seconds=ttl_seconds, cache_only=False
            )
            counts[class_name] = 1 if text else 0
        except Exception as e:
            logger.bind(class_name=class_name, error=str(e)).warning(
                "Could not warm Umi BIS"
            )
            counts[class_name] = 0
    return counts


async def skin_catalog_status(redis: aioredis.Redis) -> dict[str, int]:
    raw = await redis.get(CATALOG_KEY)
    classes = 0
    if raw:
        try:
            classes = len(json.loads(raw).get("classes") or [])
        except json.JSONDecodeError:
            classes = 0
    ttl = await redis.ttl(CATALOG_KEY)
    return {
        "stored": 1 if classes else 0,
        "classes": classes,
        "ttl_seconds": max(0, int(ttl or 0)),
    }


async def warm_skin_catalog(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    force: bool = False,
) -> dict[str, int]:
    if force:
        await redis.delete(CATALOG_KEY)
    catalog = await load_outfit_catalog(
        redis, ttl_seconds=ttl_seconds, cache_only=False
    )
    classes = len(catalog.get("classes") or [])
    return {"stored": 1 if classes else 0, "classes": classes}


async def warm_set_catalog(
    redis: aioredis.Redis, *, ttl_seconds: int
) -> dict[str, int]:
    catalog = await load_item_catalog(
        redis, ttl_seconds=ttl_seconds, class_name=None, allow_scrape=False
    )
    return {"items": len(catalog)}


async def specialist_snapshot(redis: aioredis.Redis) -> dict[str, Any]:
    abilities = await specialist_store_status(redis)
    hubs = await hub_store_status(redis)
    items = await item_store_status(redis)
    dungeons = await dungeon_store_status(redis)
    dps = await dps_store_status(redis)
    umi = await umi_store_status(redis)
    skins = await skin_catalog_status(redis)
    enchanting = await enchanting_store_status(redis)
    return {
        "abilities": abilities,
        "hubs": hubs,
        "items": items,
        "dungeons": dungeons,
        "dps": dps,
        "umi": umi,
        "skins": skins,
        "enchanting": enchanting,
    }


def _store_mostly_full(cached: int, total: int, *, min_cached: int = 1) -> bool:
    """True when a few dead wiki pages are the only gaps.

    Category hubs and one timeout (Babel Blocks, a guide page) must not
    restart a full warm on every API boot.
    """
    if total <= 0 or cached < min_cached:
        return False
    missing = total - cached
    if missing <= 0:
        return True
    return missing <= max(3, int(total * 0.05))


def missing_specialist_work(snapshot: dict[str, Any]) -> dict[str, Any]:
    """What a deploy-time warm should still fill. Never includes players."""
    abilities = [
        row["class_name"]
        for row in snapshot.get("abilities") or []
        if row.get("abilities", 0) <= 0
    ]
    hubs = [
        row["slug"]
        for row in snapshot.get("hubs") or []
        if row.get("items", 0) <= 0 and row.get("slug") not in INDEX_HUB_SLUGS
    ]
    items = snapshot.get("items") or {}
    dungeons = snapshot.get("dungeons") or {}
    dps = snapshot.get("dps") or {}
    umi = [
        row["class_name"]
        for row in snapshot.get("umi") or []
        if row.get("stored", 0) <= 0
    ]
    skins = snapshot.get("skins") or {}
    enchanting = snapshot.get("enchanting") or {}
    item_cached = int(items.get("cached") or 0)
    item_total = int(items.get("total") or 0)
    dungeon_cached = int(dungeons.get("cached") or 0)
    dungeon_total = int(dungeons.get("total") or 0)
    loadouts = int(dps.get("loadouts") or 0)
    edges = int(dps.get("edges") or 0)
    return {
        "abilities": abilities,
        "hubs": hubs,
        "items": item_total > 0 and not _store_mostly_full(item_cached, item_total),
        "dungeons": not dungeons.get("index")
        or not _store_mostly_full(dungeon_cached, dungeon_total),
        "dps": not dps.get("graph")
        or (edges > 0 and not _store_mostly_full(loadouts, edges)),
        "umi": umi,
        "skins": not skins.get("stored"),
        "enchanting": not enchanting.get("stored"),
    }


def has_missing_work(work: dict[str, Any]) -> bool:
    return bool(
        work.get("abilities")
        or work.get("hubs")
        or work.get("items")
        or work.get("dungeons")
        or work.get("dps")
        or work.get("umi")
        or work.get("skins")
        or work.get("enchanting")
    )


async def warm_all_specialists(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    force: bool = False,
    classes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Fill specialist stores. `force` re-scrapes; otherwise skip filled keys.

    Player lookups are not part of this corpus.
    """
    snapshot = await specialist_snapshot(redis)
    work = missing_specialist_work(snapshot)
    result: dict[str, Any] = {}

    async def _phase(name: str, factory):
        try:
            result[name] = await factory()
        except Exception as e:
            logger.bind(error=str(e), phase=name).warning(
                "Specialist warm phase failed; continuing"
            )
            result[name] = {"error": str(e)}

    if force or work["hubs"]:
        await _phase(
            "hubs",
            lambda: warm_hub_indexes(redis, ttl_seconds=ttl_seconds, force=force),
        )
    else:
        result["hubs"] = {row["slug"]: row["items"] for row in snapshot["hubs"]}

    ability_classes = tuple(classes) if classes else (
        tuple(work["abilities"]) if not force else None
    )
    if force or work["abilities"] or classes:
        await _phase(
            "abilities",
            lambda: warm_all_class_scaling(
                redis, ttl_seconds=ttl_seconds, classes=ability_classes
            ),
        )
    else:
        result["abilities"] = {
            row["class_name"]: row["abilities"] for row in snapshot["abilities"]
        }

    if force or work["items"]:
        await _phase(
            "items",
            lambda: warm_item_profiles(
                redis, ttl_seconds=ttl_seconds, force=force
            ),
        )
    else:
        result["items"] = snapshot["items"]

    if force or work["umi"]:
        await _phase(
            "umi",
            lambda: warm_umi_bis(redis, ttl_seconds=ttl_seconds, force=force),
        )
    else:
        result["umi"] = {row["class_name"]: row["stored"] for row in snapshot["umi"]}

    if force or work["dps"]:
        await _phase(
            "dps",
            lambda: warm_dps_boards(redis, ttl_seconds=ttl_seconds, force=force),
        )
    else:
        result["dps"] = snapshot["dps"]

    if force or work["skins"]:
        await _phase(
            "skins",
            lambda: warm_skin_catalog(redis, ttl_seconds=ttl_seconds, force=force),
        )
    else:
        result["skins"] = snapshot["skins"]

    if force or work["enchanting"]:
        await _phase(
            "enchanting",
            lambda: warm_enchanting_store(redis, ttl_seconds=ttl_seconds, force=force),
        )
    else:
        result["enchanting"] = snapshot["enchanting"]

    if force or work["dungeons"]:
        await _phase(
            "dungeons",
            lambda: warm_dungeon_guides(
                redis, ttl_seconds=ttl_seconds, force=force
            ),
        )
    else:
        result["dungeons"] = snapshot["dungeons"]

    await _phase(
        "sets",
        lambda: warm_set_catalog(redis, ttl_seconds=ttl_seconds),
    )
    await _phase(
        "biomes",
        lambda: warm_biome_pages(
            redis, ttl_seconds=ttl_seconds, force=force
        ),
    )
    logger.bind(
        abilities=len(result.get("abilities") or {}),
        hubs=len(result.get("hubs") or {}),
        dungeons=(result.get("dungeons") or {}).get("cached"),
    ).info("Specialist stores warmed")
    return result
