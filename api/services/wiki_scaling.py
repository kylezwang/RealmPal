"""
RealmEye wiki ability-scaling, for every class.

RealmShark DPS boards only list some class+stat combos. Unique abilities
often scale with a stat that has no board (Huntress traps + Dexterity,
etc.). This module reads the class's ability hub and each unique item's
infobox, then records which 8/8 stats actually appear in damage/effect
formulas. Results are cached per class so later questions reuse the same
graph — no per-item or per-stat special cases.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from ..models.build import (
    CLASS_ABILITY_HUB,
    CLASS_ARMOR_HUB,
    PLAYER_STATS,
    RINGS_HUB,
    STAT_RING_HUB,
    T7_RING_BONUS,
    T7_RING_NAME,
    weapon_family,
)
from ..models.item import ItemProfile
from .community_knowledge import (
    always_mention_rings_note,
    overlay_slot_picks,
    CLASS_STAT_SLOT_OVERRIDES,
    upgrade_notes_for,
)
from .scraper import (
    REALMEYE_BASE,
    scrape_ability_hub,
    scrape_class_max_stats,
    scrape_items_batch,
    scrape_umi_bis,
    ScraperError,
)

CACHE_PREFIX = "wiki:ability-scaling:v6"
HUB_PREFIX = "wiki:hub-index:v8"
ITEM_CACHE_PREFIX = "item:profile:v3"
LEGACY_ITEM_CACHE_PREFIX = "item:profile:v2"
CLASS_MAXSTATS_PREFIX = "wiki:class-maxstats:v1"
MAX_UT = 8

_SKIP_NAME = re.compile(
    r"\b(set|guide|class|reskin)\b"
    r"|^(hp|mp|att|def|spd|dex|vit|wis|attack|defense|speed|dexterity|"
    r"vitality|wisdom|mana)?[\s-]*(decrease|increase)$"
    r"|^amulet of (minor|greater|superior|paramount|exalted|unbound)\b",
    re.I,
)
_LE_CLONE = re.compile(
    r"^amulet of (minor|greater|superior|paramount|exalted|unbound)\b"
    r"|limited edition|\(le\)",
    re.I,
)
_ON_EQUIP = re.compile(r"^(on equip|stat bonus|feed power|xp bonus|dismantling|dust)", re.I)

# Tokens as they appear in wiki formulas: "per DEX", "per Attack", ...
_STAT_TOKEN: dict[str, re.Pattern[str]] = {
    "HP": re.compile(r"\b(?:hp|life|health)\b", re.I),
    "MP": re.compile(r"\b(?:mp|mana)\b", re.I),
    "Attack": re.compile(r"\b(?:att(?:ack)?|atk)\b", re.I),
    "Defense": re.compile(r"\b(?:def(?:en[cs]e)?)\b", re.I),
    "Speed": re.compile(r"\b(?:spd|speed)\b", re.I),
    "Dexterity": re.compile(r"\b(?:dex(?:terity)?)\b", re.I),
    "Vitality": re.compile(r"\b(?:vit(?:ality)?)\b", re.I),
    "Wisdom": re.compile(r"\b(?:wis(?:dom)?)\b", re.I),
}

_SCALING_HIT = re.compile(
    r"(?:per|/|for every)\s*(?:\d+\s+)?"
    r"(?:DEX|ATT|ATK|WIS|VIT|SPD|DEF|HP|MP|"
    r"Dexterity|Attack|Wisdom|Vitality|Speed|Defense|Mana|Life)"
    r"|scales?\s+with\s+(?:DEX|ATT|ATK|WIS|VIT|SPD|DEF|HP|MP|"
    r"Dexterity|Attack|Wisdom|Vitality|Speed|Defense)",
    re.I,
)


def scaling_from_item(item: ItemProfile) -> dict[str, str]:
    """Stat -> evidence string, from infobox rows that are real formulas.

    On Equip / +DEX bonuses do not count; '675 (+14 per DEX over 32)' does.
    """
    found: dict[str, list[str]] = {}
    for key, val in (item.stats or {}).items():
        if _ON_EQUIP.search(str(key)):
            continue
        text = f"{key}: {val}"
        if not _SCALING_HIT.search(str(val)) and not _SCALING_HIT.search(str(key)):
            continue
        for stat, pat in _STAT_TOKEN.items():
            if pat.search(str(val)) or pat.search(str(key)):
                found.setdefault(stat, []).append(text)
    return {stat: "; ".join(rows) for stat, rows in found.items()}


_NOTABLE_EFFECT = re.compile(
    r"berserk|healing|damaging|speedy|inspired|awakened|armor break|"
    r"exposed|curse|weak|slowed|paraly|invuln|quiet|stasis|on abilit",
    re.I,
)


def notable_effects(item: ItemProfile) -> str:
    """Effect(s), procs, and auras that change which item is actually best."""
    chunks: list[str] = []
    for key, val in (item.stats or {}).items():
        if re.search(r"effect|proc|aura|activate|awakened", str(key), re.I):
            chunks.append(f"{key}: {val}")
        elif _NOTABLE_EFFECT.search(str(val)):
            chunks.append(f"{key}: {val}")
    return "; ".join(chunks)


def _tier_bucket(row: dict) -> str:
    raw = (row.get("tier") or "").strip().upper()
    if raw in {"7", "T7"} or raw.startswith("T7"):
        return "t7"
    if raw == "ST":
        return "st"
    if raw.startswith("UT") or raw == "L":
        return "ut"
    return "other"


def _pick_ability_pages(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """T7 first (baseline scaling) + all ST, then every UT (caller pages
    through the UT list in batches — see `load_class_wiki_scaling`). Skip
    T0–T6.
    """
    cleaned = [
        row
        for row in items
        if row.get("name") and not _SKIP_NAME.search(row["name"])
    ]
    t7, st, ut = [], [], []
    seen: set[str] = set()
    for row in cleaned:
        key = row["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        bucket = _tier_bucket(row)
        if bucket == "t7":
            t7.append(row)
        elif bucket == "st":
            st.append(row)
        elif bucket == "ut":
            ut.append(row)
    first = t7[:1] + st
    return first, ut


_BONUS_PAT: dict[str, re.Pattern[str]] = {
    "HP": re.compile(r"\+(\d+)\s*(?:HP|Life)\b", re.I),
    "MP": re.compile(r"\+(\d+)\s*(?:MP|Mana)\b", re.I),
    "Attack": re.compile(r"\+(\d+)\s*(?:ATT|Attack|ATK)\b", re.I),
    "Defense": re.compile(r"\+(\d+)\s*(?:DEF|Defense)\b", re.I),
    "Speed": re.compile(r"\+(\d+)\s*(?:SPD|Speed)\b", re.I),
    "Dexterity": re.compile(r"\+(\d+)\s*(?:DEX|Dexterity)\b", re.I),
    "Vitality": re.compile(r"\+(\d+)\s*(?:VIT|Vitality)\b", re.I),
    "Wisdom": re.compile(r"\+(\d+)\s*(?:WIS|Wisdom)\b", re.I),
}


# Combat rings cap around +11 (T7). +140/+180 is HP or MP, never ATT.
_MAX_BONUS = {
    "HP": 220,
    "MP": 220,
    "Attack": 16,
    "Defense": 16,
    "Speed": 16,
    "Dexterity": 16,
    "Vitality": 16,
    "Wisdom": 16,
}
_LOW_TIER_RING = re.compile(
    r"^ring of (minor|greater|superior|paramount|exalted|unbound)\b",
    re.I,
)
_T1_RING = re.compile(
    r"^ring of (attack|defense|speed|dexterity|vitality|wisdom|health|magic)$",
    re.I,
)

# Always fetch these infoboxes so a thin hub table cannot hide them.
_FLAGSHIP_RINGS: dict[str, tuple[str, ...]] = {
    "Attack": (
        "Chrysalis of Eternity",
        "Overclocking Amulet",
        "The Forgotten Crown",
        "Magical Lodestone",
    ),
    "Dexterity": (
        "Chrysalis of Eternity",
        "Overclocking Amulet",
        "The Forgotten Crown",
        "Magical Lodestone",
    ),
    "Defense": ("Bracer", "Adventurer's Scarf"),
}


def _plausible(stat: str, value: int) -> bool:
    cap = _MAX_BONUS.get(stat, 16)
    return 0 < value <= cap


def _bonus_value(row: dict, stat: str) -> int:
    """Labeled On Equip text wins. Column maps can assign MP to Attack."""
    pat = _BONUS_PAT.get(stat)
    text = f"{row.get('bonus') or ''} {row.get('rowText') or ''}"
    if pat:
        hits = [int(n) for n in pat.findall(text) if _plausible(stat, int(n))]
        if hits:
            return max(hits)
    values = row.get("statValues") or row.get("stat_values") or {}
    if stat in values:
        try:
            n = int(values[stat])
            if _plausible(stat, n):
                return n
        except (TypeError, ValueError):
            pass
    return 0


def _is_low_tier_ring(row: dict) -> bool:
    """T0–T6 named rings only. Blank-tier UTs like Chrysalis must stay."""
    name = row.get("name") or ""
    if re.search(r"^ring of transcendent\b", name, re.I):
        return False
    if _LOW_TIER_RING.search(name) or _T1_RING.search(name):
        return True
    raw = (row.get("tier") or "").strip().upper()
    return bool(re.fullmatch(r"T?[0-6]", raw))


def _is_t7_ring(row: dict, stat: str) -> bool:
    name = (row.get("name") or "").lower()
    t7 = (T7_RING_NAME.get(stat) or "").lower()
    return bool(t7) and name == t7


def _t7_fallback(stat: str) -> dict:
    value, bonus = T7_RING_BONUS.get(stat, (0, ""))
    return {
        "name": T7_RING_NAME[stat],
        "tier": "T7",
        "bonus": bonus,
        "stat_value": value,
    }


def _offense_package(row: dict) -> tuple[int, int]:
    """ATT+DEX and HP — Attack/Dex UTs like Chrysalis beat a lone T6 ATT ring."""
    return (
        _bonus_value(row, "Attack") + _bonus_value(row, "Dexterity"),
        _bonus_value(row, "HP"),
    )


def _ring_sort_key(row: dict, stat: str) -> tuple:
    primary = int(row.get("stat_value") or _bonus_value(row, stat) or 0)
    if stat in {"Attack", "Dexterity"}:
        offense, hp = _offense_package(row)
        return (-offense, -hp, -primary, row.get("name") or "")
    return (-primary, 0, 0, row.get("name") or "")


def _top_stat_items(
    rows: list[dict],
    stat: str,
    *,
    limit: int = 5,
    include_t7: bool = False,
    rings: bool = False,
) -> list[dict]:
    scored = []
    seen: set[str] = set()
    for row in rows:
        name = row.get("name") or ""
        if not name or _SKIP_NAME.search(name) or name.lower() in seen:
            continue
        if rings and _is_limited_ring(name, row):
            continue
        if rings and _is_low_tier_ring(row) and not _is_t7_ring(row, stat):
            continue
        value = _bonus_value(row, stat)
        if value <= 0 and not (rings and name.lower() in {
            n.lower() for n in _FLAGSHIP_RINGS.get(stat, ())
        }):
            continue
        seen.add(name.lower())
        scored.append({**row, "stat_value": value})
    if rings:
        scored = [
            r for r in scored
            if _is_t7_ring(r, stat) or not _is_low_tier_ring(r)
        ]
        t7 = [r for r in scored if _is_t7_ring(r, stat)]
        if not t7 and include_t7 and stat in T7_RING_NAME:
            t7 = [_t7_fallback(stat)]
        uts = [r for r in scored if not _is_t7_ring(r, stat)]
        uts.sort(key=lambda r: _ring_sort_key(r, stat))
        return (t7[:1] + uts)[:limit]
    scored.sort(key=lambda r: (-r["stat_value"], r["name"]))
    pool = scored
    if include_t7:
        pool = [r for r in scored if _tier_bucket(r) in {"t7", "st", "ut"}] or scored
    top = pool[:limit]
    if include_t7:
        t7 = [row for row in scored if _tier_bucket(row) == "t7"]
        if t7:
            best_t7 = t7[0]
            names = {row["name"].lower() for row in top}
            if best_t7["name"].lower() not in names:
                if len(top) >= limit:
                    top = top[: limit - 1] + [best_t7]
                else:
                    top.append(best_t7)
                top.sort(key=lambda r: (-r["stat_value"], r["name"]))
    return top


def item_name_keys(name: str) -> list[str]:
    """Lookup keys for a typed name, including curly/straight apostrophes."""
    raw = (name or "").strip().lower()
    if not raw:
        return []
    variants = {raw, raw.replace("'", "’"), raw.replace("’", "'")}
    return list(variants)


async def read_cached_item(
    redis: aioredis.Redis, name: str
) -> Optional[ItemProfile]:
    """Read a warmed or live-scraped item profile. Prefers v3, then v2."""
    for prefix in (ITEM_CACHE_PREFIX, LEGACY_ITEM_CACHE_PREFIX):
        for key in item_name_keys(name):
            raw = await redis.get(f"{prefix}:{key}")
            if not raw:
                continue
            try:
                return ItemProfile.model_validate_json(raw)
            except Exception:
                continue
    return None


async def write_cached_item(
    redis: aioredis.Redis,
    item: ItemProfile,
    ttl: int,
    *aliases: str,
) -> None:
    payload = item.model_dump_json(exclude={"wearable"})
    names = {item.name, *[alias for alias in aliases if alias]}
    keys = []
    for name in names:
        keys.extend(item_name_keys(name))
    for key in dict.fromkeys(keys):
        await redis.setex(f"{ITEM_CACHE_PREFIX}:{key}", ttl, payload)


MISSING_ITEM_PREFIX = "item:missing:v1"


async def mark_item_missing(redis: aioredis.Redis, name: str, ttl: int) -> None:
    """Remember that `name` has no RealmEye wiki page right now.

    Some real, correctly-named items (a fresh RealmShark leaderboard entry)
    genuinely have no wiki page yet, and every lookup for one used to pay a
    full two-attempt Playwright timeout (~30s) with nothing cached to skip
    it next time. Short TTL so the item starts resolving on its own once
    RealmEye actually publishes the page - see Settings.missing_item_ttl_seconds.
    """
    for key in item_name_keys(name):
        await redis.setex(f"{MISSING_ITEM_PREFIX}:{key}", ttl, "1")


async def is_item_marked_missing(redis: aioredis.Redis, name: str) -> bool:
    for key in item_name_keys(name):
        if await redis.get(f"{MISSING_ITEM_PREFIX}:{key}"):
            return True
    return False


async def _cached_item(redis: aioredis.Redis, name: str) -> Optional[ItemProfile]:
    return await read_cached_item(redis, name)


async def _store_item(redis: aioredis.Redis, item: ItemProfile, ttl: int) -> None:
    await write_cached_item(redis, item, ttl)


async def _hub_index(
    redis: aioredis.Redis,
    slug: str,
    ttl: int,
    *,
    force: bool = False,
    cache_only: bool = False,
) -> list[dict]:
    key = f"{HUB_PREFIX}:{slug}"
    if not force:
        cached = await redis.get(key)
        if cached:
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                pass
        if cache_only:
            return []
    rows = await scrape_ability_hub(slug)
    await redis.setex(key, ttl, json.dumps(rows))
    return rows


async def cached_class_wiki_scaling(
    redis: aioredis.Redis, class_name: str
) -> Optional[dict]:
    """Return the stored wiki-scaling payload without scraping."""
    cached = await redis.get(f"{CACHE_PREFIX}:{class_name.lower()}")
    if not cached:
        return None
    try:
        return json.loads(cached)
    except json.JSONDecodeError:
        return None


async def specialist_store_status(redis: aioredis.Redis) -> list[dict]:
    """Read-only snapshot of every class store. Does not scrape."""
    rows: list[dict] = []
    for class_name in CLASS_ABILITY_HUB:
        key = f"{CACHE_PREFIX}:{class_name.lower()}"
        raw = await redis.get(key)
        ttl = await redis.ttl(key)
        abilities = 0
        if raw:
            try:
                abilities = len(json.loads(raw).get("abilities") or [])
            except json.JSONDecodeError:
                abilities = 0
        rows.append(
            {
                "class_name": class_name,
                "abilities": abilities,
                "ttl_seconds": max(0, int(ttl or 0)),
            }
        )
    return rows


async def load_class_wiki_scaling(
    redis: aioredis.Redis,
    class_name: str,
    *,
    ttl_seconds: int,
    stat: Optional[str] = None,
    force: bool = False,
) -> dict:
    """Every wiki-derived scaling edge for one class.

    Chat only reads the stored payload. `force=True` is the weekly
    refresh path: re-read the hub and every T7/ST/UT ability so later
    traps (Huntress DEX sit past the first page) stay in the store.
    """
    cache_key = f"{CACHE_PREFIX}:{class_name.lower()}"
    if not force:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

    lock_key = f"{cache_key}:lock"
    got_lock = await redis.set(lock_key, "1", nx=True, ex=600)
    if not got_lock and not force:
        for _ in range(30):
            await asyncio.sleep(1)
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

    slug = CLASS_ABILITY_HUB.get(class_name)
    hub_url = f"{REALMEYE_BASE}/wiki/{slug}" if slug else ""
    empty = {"class_name": class_name, "hub_url": hub_url, "abilities": []}
    if not slug:
        await redis.setex(cache_key, ttl_seconds, json.dumps(empty))
        return empty

    try:
        hub_rows = await _hub_index(redis, slug, ttl_seconds, force=force)
    except ScraperError as e:
        logger.bind(class_name=class_name, error=str(e)).warning(
            "RealmEye ability hub unavailable"
        )
        return empty

    first, ut_all = _pick_ability_pages(hub_rows)
    profiles = await _profiles_for_names(
        redis, [row["name"] for row in first], ttl_seconds, force=force
    )
    # Page the whole UT list. Stopping at the first matching stat used to
    # hide the second Huntress DEX trap; a first-8 cap hid Trap of the
    # Vile Spirit (UT #11) entirely.
    for i in range(0, len(ut_all), MAX_UT):
        batch = ut_all[i : i + MAX_UT]
        profiles.extend(
            await _profiles_for_names(
                redis, [row["name"] for row in batch], ttl_seconds, force=force
            )
        )

    abilities = []
    for item in profiles:
        if item.limited_edition or re.search(
            r"limited|\(le\)", item.tier or "", re.I
        ):
            continue
        scales = scaling_from_item(item)
        effects = notable_effects(item)
        if not scales and not effects:
            continue
        abilities.append(
            {
                "name": item.name,
                "wiki_url": item.wiki_url or f"{REALMEYE_BASE}/wiki/{slug}",
                "tier": item.tier,
                "scales": scales,
                "effects": effects,
            }
        )

    payload = {
        "class_name": class_name,
        "hub_url": hub_url,
        "abilities": abilities,
    }
    await redis.setex(cache_key, ttl_seconds, json.dumps(payload))
    await redis.delete(lock_key)
    logger.bind(class_name=class_name, abilities=len(abilities)).info(
        "Cached RealmEye wiki ability scaling"
    )
    return payload


async def _profiles_for_names(
    redis: aioredis.Redis,
    names: list[str],
    ttl: int,
    *,
    force: bool = False,
    cache_only: bool = False,
) -> list[ItemProfile]:
    profiles: list[ItemProfile] = []
    missing: list[str] = []
    for name in names:
        item = None if force else await _cached_item(redis, name)
        if item:
            profiles.append(item)
        else:
            missing.append(name)
    if not missing or cache_only:
        return profiles
    try:
        scraped = await scrape_items_batch(missing)
    except Exception as e:
        logger.bind(error=str(e)).warning("Batch item scrape failed")
        return profiles
    for item in scraped:
        profiles.append(item)
        await _store_item(redis, item, ttl)
    return profiles


def format_wiki_scaling(
    payload: dict,
    *,
    stat: Optional[str] = None,
) -> str:
    class_name = payload.get("class_name") or ""
    hub_url = payload.get("hub_url") or ""
    abilities = list(payload.get("abilities") or [])
    if stat:
        abilities = [a for a in abilities if stat in (a.get("scales") or {})]

    lines = [
        "RealmEye wiki ability scaling (infobox damage/effect formulas, "
        "not RealmShark DPS boards). An ability scales with a stat only when "
        "its formula uses that stat (e.g. '+14 per DEX over 32'). A +DEX On "
        "Equip bonus is not scaling. When RealmShark has no board for a "
        "class+stat, use this section — do not say the build does not exist "
        "if an ability is listed here. When several abilities scale, prefer "
        "the one whose Effect(s) on that same item help more. Do not invent "
        "or copy status effects from another item."
        + (
            " Lifebringing Lotus over Honeytomb Snare because Lotus also "
            "gives Berserk and Healing."
            if class_name == "Huntress"
            else ""
        ),
        f"Source: {hub_url}" if hub_url else "",
        "",
    ]
    if not abilities:
        lines.append(
            f"T7 / ST / UT {class_name} ability infoboxes did not list a "
            f"per-{stat or 'stat'} damage formula. Still recommend a "
            f"{stat or 'stat'} {class_name} build using armor and rings that "
            f"stack that stat, plus weapons from classes that share the same "
            f"weapon. Do not say the build does not exist."
        )
        return "\n".join(line for line in lines if line is not None).strip()

    by_stat: dict[str, list[tuple[str, str]]] = {}
    for ability in abilities:
        for scale_stat, evidence in (ability.get("scales") or {}).items():
            if stat and scale_stat != stat:
                continue
            by_stat.setdefault(scale_stat, []).append((ability["name"], evidence))

    lines.append(f"{class_name}:")
    order = [s for s in PLAYER_STATS if s in by_stat]
    for scale_stat in order:
        names = ", ".join(f"[item:{name}]" for name, _ in by_stat[scale_stat])
        lines.append(f"  {scale_stat} -> {names}")
        for name, evidence in by_stat[scale_stat]:
            extra = next(
                (a.get("effects") for a in abilities if a["name"] == name),
                "",
            )
            lines.append(f"    {name}: {evidence}")
            if extra:
                lines.append(f"      Effects: {extra}")
        t7_names = [
            a["name"]
            for a in (payload.get("abilities") or [])
            if scale_stat in (a.get("scales") or {})
            and str(a.get("tier") or "").upper() in {"7", "T7"}
        ]
        if t7_names:
            lines.append(
                "    Tiered T7 baseline (always mention): "
                + ", ".join(f"[item:{n}]" for n in t7_names)
            )
    return "\n".join(lines).strip()


def _on_equip_text(item: ItemProfile) -> str:
    for key, val in (item.stats or {}).items():
        if re.search(r"on equip", str(key), re.I):
            return str(val)
    return ""


def infer_item_base_stat(item: ItemProfile) -> Optional[str]:
    """The stat an item's own On Equip line favors, e.g. '+20 ATT' -> Attack.

    Used when a player asks for enchant/build advice on a named item without
    naming a stat ("what enchants on Cackling Straitjacket" implies Attack
    because that item's own base bonus is +20 Attack). Returns None on no
    bonus or a tie between two stats | the caller should not guess further.
    """
    on_equip = _on_equip_text(item)
    if not on_equip:
        return None
    # Not _bonus_value: its plausibility cap is tuned for T7 combat rings
    # (+11 max), but a robe/weapon's own On Equip bonus is often +16-30.
    scored: dict[str, int] = {}
    for stat, pat in _BONUS_PAT.items():
        hits = [int(n) for n in pat.findall(on_equip)]
        if hits:
            scored[stat] = max(hits)
    if not scored:
        return None
    best_value = max(scored.values())
    ties = [stat for stat, value in scored.items() if value == best_value]
    return ties[0] if len(ties) == 1 else None


def infer_class_primary_stat(payload: Optional[dict]) -> Optional[str]:
    """Which 8/8 stat most of a class's abilities scale with.

    Used for a whole-build ask with no stat named ("best kensei build"):
    enchant recommendations still need one stat to focus on, and DPS builds
    overwhelmingly chase whichever stat the class's own abilities scale
    with, same as the single-item inference above.
    """
    abilities = list((payload or {}).get("abilities") or [])
    counts: dict[str, int] = {}
    for ability in abilities:
        for stat in (ability.get("scales") or {}):
            counts[stat] = counts.get(stat, 0) + 1
    if not counts:
        return None
    top = max(counts.values())
    ties = [stat for stat, count in counts.items() if count == top]
    return ties[0] if len(ties) == 1 else None


def _is_limited_ring(name: str, row: dict | None = None, item: ItemProfile | None = None) -> bool:
    blob = f"{name} {(row or {}).get('rowText') or ''} {(row or {}).get('bonus') or ''}"
    if _LE_CLONE.search(name) or _LE_CLONE.search(blob):
        return True
    if item is not None and getattr(item, "limited_edition", False):
        return True
    return False


async def _verify_ring_infoboxes(
    redis: aioredis.Redis,
    rows: list[dict],
    ttl: int,
    *,
    stat: str,
    cache_only: bool = False,
) -> list[dict]:
    """Keep only infobox-confirmed, non-LE rings that actually grant this stat."""
    names = [r["name"] for r in rows if r.get("name")]
    profiles = await _profiles_for_names(
        redis, names, ttl, cache_only=cache_only
    )
    by_name = {p.name.lower(): p for p in profiles}
    verified = []
    for row in rows:
        key = (row.get("name") or "").lower()
        if _is_limited_ring(row.get("name") or "", row):
            continue
        item = by_name.get(key)
        if item is None:
            if _is_t7_ring(row, stat):
                verified.append({**row, "verified": False})
            continue
        if _is_limited_ring(item.name, row, item):
            continue
        on_equip = _on_equip_text(item)
        if not on_equip:
            continue
        patched = {
            **row,
            "name": item.name,
            "tier": item.tier or row.get("tier") or "UT",
            "bonus": on_equip,
            "verified": True,
        }
        if _bonus_value(patched, stat) <= 0 and not _is_t7_ring(patched, stat):
            continue
        verified.append(patched)
    return verified


_STAT_ABBR = {
    "HP": "HP",
    "MP": "MP",
    "Attack": "ATT",
    "Defense": "DEF",
    "Speed": "SPD",
    "Dexterity": "DEX",
    "Vitality": "VIT",
    "Wisdom": "WIS",
}


def _ring_why(row: dict, stat: str) -> str:
    if _is_t7_ring(row, stat):
        return f"T7 Transcendent — only tiered {stat} ring to list"
    bits: list[str] = []
    bonus = row.get("bonus") or ""
    for other, abbr in _STAT_ABBR.items():
        if other == stat:
            continue
        n = _bonus_value(row, other)
        if n:
            bits.append(f"+{n} {abbr}")
    if stat in {"Attack", "Dexterity"}:
        att = _bonus_value(row, "Attack")
        dex = _bonus_value(row, "Dexterity")
        if att and dex:
            bits.insert(0, "dual ATT/DEX")
    if bits:
        return ", ".join(bits)
    return bonus or "UT matching this stat"


def format_stat_gear(
    kind: str,
    hub_url: str,
    rows: list[dict],
    stat: str,
    *,
    brief: bool = False,
) -> str:
    if not rows:
        return ""
    t7 = T7_RING_NAME.get(stat, f"Ring of Transcendent {stat}")
    abbr = _STAT_ABBR.get(stat, stat)
    if kind == "rings":
        header = (
            f"RING AGENT — {stat} rings only (source {hub_url}). "
            f"The only tiered ring allowed is T7 [{t7}]. "
            "Never list Ring of Unbound / Exalted / Paramount / Superior / "
            "Greater — those are T6 and below. After T7, remaining slots are "
            "UT/ST only, ranked from each item's On Equip infobox. "
            "For Attack or Dexterity, dual-offensive UTs (Chrysalis of "
            "Eternity +7 ATT +7 DEX, Overclocking Amulet, Forgotten Crown) "
            "outrank a T6 ATT ring. "
            f"{stat} ring bonuses are never 100+; those are HP/MP. "
            "RealmShark equipped rings are what players wore, not this ranking. "
            "Limited Edition / LE amulets (Amulet of Superior Dexterity, "
            "Amulet of Superior Speed, etc.) are omitted on purpose — never "
            "add them. Only rows in this table are allowed. "
            f"Copy this markdown table. Columns must be Ring | {stat} | Why "
            f"({stat} uses {abbr} bonuses so they can be compared). Why stays "
            "the last column. You may tighten Why text; do not drop the "
            f"{stat} column or add T0–T6 rings.\n"
        )
        lines = [
            header,
            f"| Ring | {stat} | Why |",
            "| --- | --- | --- |",
        ]
        for row in rows:
            att = _bonus_value(row, stat) or row.get("stat_value") or 0
            lines.append(
                f"| [item:{row['name']}] | +{att} {abbr} | {_ring_why(row, stat)} |"
            )
        lines.append(always_mention_rings_note())
        return "\n".join(lines)
    header = (
        f"RealmEye hub On Equip ranks for {stat} {kind} from {hub_url} "
        "(last in the source list after RealmShark, the player overlay, and "
        "Umi). This class's armor type only; ignore Umi general-tab armor "
        "if it is for a different stat, e.g. Vesture of Duality is Attack. "
        "Armor alternatives come from the Umi general-tab chunk, not this "
        "hub list. Never list a T7 robe or armor as an alternative."
    )
    if brief:
        header += " Give 2-3 armor alternatives from Umi, not T7 filler."
    lines = [header]
    for row in rows:
        ranked = f"+{row.get('stat_value')} {stat}"
        extra = row.get("bonus") or ""
        shown = f"{ranked}" + (f" — On Equip {extra}" if extra and extra != ranked else "")
        lines.append(f"  [item:{row['name']}] ({row.get('tier') or '?'}) {shown}")
    return "\n".join(lines)


async def retrieve_universal_rings(
    redis: aioredis.Redis,
    stat: str,
    *,
    ttl_seconds: int,
    limit: int = 5,
    brief: bool = False,
    cache_only: bool = False,
) -> str:
    """Best matching rings from RealmEye list pages, confirmed on infoboxes."""
    slug = STAT_RING_HUB.get(stat, RINGS_HUB)
    rows: list[dict] = []
    try:
        rows = await _hub_index(
            redis, slug, ttl_seconds, cache_only=cache_only
        )
    except ScraperError as e:
        logger.bind(error=str(e), slug=slug).warning(
            "RealmEye per-stat rings page unavailable"
        )
    try:
        extra = await _hub_index(
            redis, RINGS_HUB, ttl_seconds, cache_only=cache_only
        )
        seen = {((r.get("name") or "").lower()) for r in rows}
        for row in extra:
            key = (row.get("name") or "").lower()
            if key and key not in seen:
                rows.append(row)
                seen.add(key)
    except ScraperError:
        pass
    seen = {((r.get("name") or "").lower()) for r in rows}
    for name in _FLAGSHIP_RINGS.get(stat, ()):
        if name.lower() not in seen:
            rows.append({"name": name, "tier": "UT", "bonus": ""})
            seen.add(name.lower())
    if not rows and stat not in T7_RING_NAME:
        return ""
    candidates = _top_stat_items(
        rows, stat, limit=max(limit, 10), include_t7=True, rings=True
    )
    have = {(r.get("name") or "").lower() for r in candidates}
    for row in rows:
        key = (row.get("name") or "").lower()
        if key in {(n.lower()) for n in _FLAGSHIP_RINGS.get(stat, ())} and key not in have:
            candidates.append(row)
            have.add(key)
    try:
        candidates = await _verify_ring_infoboxes(
            redis, candidates, ttl_seconds, stat=stat, cache_only=cache_only
        )
    except Exception as e:
        logger.bind(error=str(e)).warning("Ring infobox verification failed")
        # Unverified hub rows caused Limited Edition amulets with invented
        # ATT values. Fall back to the known-good T7 rather than guessing.
        candidates = [
            r for r in candidates
            if _is_t7_ring(r, stat) and not _is_limited_ring(r.get("name") or "", r)
        ] or ([_t7_fallback(stat)] if stat in T7_RING_NAME else [])
    top_rings = _top_stat_items(
        candidates, stat, limit=limit, include_t7=True, rings=True
    )
    return format_stat_gear(
        "rings",
        f"{REALMEYE_BASE}/wiki/{slug}",
        top_rings,
        stat,
        brief=brief,
    )


async def retrieve_armor_brief(
    redis: aioredis.Redis,
    class_name: str,
    stat: str,
    *,
    ttl_seconds: int,
    limit: int = 3,
    brief: bool = True,
    cache_only: bool = False,
) -> str:
    armor_slug = CLASS_ARMOR_HUB.get(class_name)
    if not armor_slug:
        return ""
    try:
        armor_rows = await _hub_index(
            redis, armor_slug, ttl_seconds, cache_only=cache_only
        )
    except ScraperError as e:
        logger.bind(class_name=class_name, error=str(e)).warning(
            "RealmEye armor hub unavailable"
        )
        return ""
    ranked = _top_stat_items(
        armor_rows, stat, limit=max(limit, 8), include_t7=False
    )
    top_armor = [row for row in ranked if _tier_bucket(row) != "t7"][:limit]
    text = format_stat_gear(
        "armors",
        f"{REALMEYE_BASE}/wiki/{armor_slug}",
        top_armor,
        stat,
        brief=brief,
    )
    overlay = CLASS_STAT_SLOT_OVERRIDES.get((class_name, stat), {})
    prefixes: list[str] = []
    if overlay.get("armor"):
        prefixes.append(
            f"Player overlay armor for {class_name} {stat}: "
            f"[item:{overlay['armor']}]. Prefer this over hub On Equip "
            "ranking below."
        )
    if stat == "Attack" and armor_slug == "robes":
        prefixes.append(
            "Attack robe cores: [item:Diplomatic Robe] and "
            "[item:Vesture of Duality], with [item:Flowering Kimono] as "
            "an honorable mention. If Diplomatic is the pick, Vesture is "
            "the first alternative. Never list a T7 robe as an alternative."
        )
    if prefixes and text:
        text = "\n".join(prefixes) + "\n" + text
    return text


async def retrieve_weapon_brief(
    redis: aioredis.Redis,
    class_name: str,
    stat: Optional[str],
    *,
    ttl_seconds: int,
    limit: int = 3,
    brief: bool = True,
    cache_only: bool = False,
) -> str:
    hubs, label = weapon_family(class_name)
    if not hubs:
        return ""
    rows: list[dict] = []
    for slug in hubs:
        try:
            rows.extend(
                await _hub_index(
                    redis, slug, ttl_seconds, cache_only=cache_only
                )
            )
        except ScraperError as e:
            logger.bind(slug=slug, error=str(e)).warning(
                "RealmEye weapon hub unavailable"
            )
    lines = [
        f"WEAPON AGENT — {class_name} can only use {label} "
        f"({', '.join(f'{REALMEYE_BASE}/wiki/{h}' for h in hubs)}). "
        "Never recommend a weapon from another family."
    ]
    overlay = CLASS_STAT_SLOT_OVERRIDES.get((class_name, stat or ""), {})
    if overlay.get("weapon"):
        lines.append(
            f"Player overlay weapon for {class_name} {stat}: "
            f"[item:{overlay['weapon']}]. Prefer this over hub On Equip "
            "ranking below."
        )
    named: list[str] = []
    if stat and rows:
        top = _top_stat_items(rows, stat, limit=limit, include_t7=True)
        if top:
            if brief:
                lines.append(
                    f"Give 2-3 {label} alternatives from the Umi general-tab "
                    f"chunk for a {stat} build, not extra hub T7s."
                )
            for row in top:
                ranked = f"+{row.get('stat_value')} {stat}"
                extra = row.get("bonus") or ""
                shown = ranked + (f" — {extra}" if extra else "")
                lines.append(
                    f"  [item:{row['name']}] ({row.get('tier') or '?'}) {shown}"
                )
                named.append(row["name"])
        else:
            t7 = [r for r in rows if _tier_bucket(r) == "t7"][:1]
            if t7:
                lines.append(
                    "No On Equip "
                    f"{stat} on these weapons. Still prefer high-tier {label} "
                    f"such as [item:{t7[0]['name']}]."
                )
                named.append(t7[0]["name"])
    notes = upgrade_notes_for(named)
    if notes:
        lines.append(notes)
    return "\n".join(lines)


async def retrieve_ability_brief(
    redis: aioredis.Redis,
    class_name: str,
    *,
    stat: Optional[str] = None,
    ttl_seconds: int,
    brief: bool = True,
    cache_only: bool = False,
) -> str:
    try:
        if cache_only:
            payload = await cached_class_wiki_scaling(redis, class_name)
            if not payload:
                return ""
        else:
            payload = await load_class_wiki_scaling(
                redis, class_name, ttl_seconds=ttl_seconds, stat=stat
            )
    except Exception as e:
        logger.bind(class_name=class_name, error=str(e)).warning(
            "RealmEye wiki scaling unavailable"
        )
        return ""
    text = format_wiki_scaling(payload, stat=stat)
    if not text:
        return ""
    prefix = "ABILITY AGENT — this slot only. "
    if brief:
        prefix += (
            "On a full build, name the scaling ability plus 2-3 "
            "alternatives from the Umi general-tab chunk when that page "
            "lists extras. Do not expand into rings or armor here.\n"
        )
    overlay = CLASS_STAT_SLOT_OVERRIDES.get((class_name, stat or ""), {})
    if overlay.get("ability"):
        prefix += (
            f"Player overlay ability for {class_name} {stat}: "
            f"[item:{overlay['ability']}]. Prefer this over the wiki "
            "scaling list below.\n"
        )
    return prefix + text


_ITEM_TOKEN_RE = re.compile(r"\[item:([^\]]+)\]")


async def top_build_items(
    redis: aioredis.Redis,
    class_name: str,
    stat: str,
    *,
    ttl_seconds: int,
    cache_only: bool = True,
) -> dict[str, str]:
    """The single best weapon/ability/armor/ring for a class+stat build.

    Found live Sep 14, right after fixing "attack huntress" from being
    misread as a literal item name (stored_answers._shiny_divine_item_name):
    "show me full shiny divine attack huntress" then fell through correctly,
    but landed on the multi-paragraph balanced-loadout brief instead of the
    shiny/divine item-circle loadout the wording actually asked for - that
    visual only existed for explicitly *named* sets ("full shiny divine
    Enforcer, Ballistic Star, Straitjacket, and Lean"), never for a
    class+stat ask with no items named. Rather than re-rank items a second
    time, this reuses the exact same ranking each text-brief slot agent
    already computes (retrieve_weapon_brief/retrieve_ability_brief/
    retrieve_armor_brief/retrieve_universal_rings - top_stat_items ordering,
    T7 fallback, ring infobox verification) by asking each for its top pick
    and reading back the first [item:...] token, so the single-item pick
    can never disagree with what the full brief would have said about that
    same slot.

    limit=2 (not 1) for weapon/armor: _top_stat_items' "always include a T7
    baseline" rule can *replace* the actual top pick when limit=1 (it only
    guarantees T7 appears *somewhere* in the returned list, not that it's
    ranked first) - asking for 2 and taking the first still returns the
    highest-stat_value item after the re-sort, T7 or not. Rings use limit=1
    since T7 is deliberately always the ring agent's first pick regardless
    of stat_value (a guaranteed, always-available choice, per
    retrieve_universal_rings' own header text) - not an artifact to work
    around.
    """
    picks: dict[str, str] = {}

    weapon_text = await retrieve_weapon_brief(
        redis, class_name, stat, ttl_seconds=ttl_seconds, limit=2, brief=True,
        cache_only=cache_only,
    )
    match = _ITEM_TOKEN_RE.search(weapon_text)
    if match:
        picks["weapon"] = match.group(1)

    ability_text = await retrieve_ability_brief(
        redis, class_name, stat=stat, ttl_seconds=ttl_seconds, brief=True,
        cache_only=cache_only,
    )
    match = _ITEM_TOKEN_RE.search(ability_text)
    if match:
        picks["ability"] = match.group(1)

    armor_text = await retrieve_armor_brief(
        redis, class_name, stat, ttl_seconds=ttl_seconds, limit=2, brief=True,
        cache_only=cache_only,
    )
    match = _ITEM_TOKEN_RE.search(armor_text)
    if match:
        picks["armor"] = match.group(1)

    ring_text = await retrieve_universal_rings(
        redis, stat, ttl_seconds=ttl_seconds, limit=1, brief=True,
        cache_only=cache_only,
    )
    match = _ITEM_TOKEN_RE.search(ring_text)
    if match:
        picks["ring"] = match.group(1)

    try:
        from .realmshark import shark_slot_picks

        shark = await shark_slot_picks(
            redis,
            class_name,
            stat,
            ttl_seconds=ttl_seconds,
            cache_only=cache_only,
        )
        picks = {**picks, **shark}
    except Exception as e:
        logger.bind(error=str(e), class_name=class_name, stat=stat).warning(
            "RealmShark slot picks unavailable"
        )

    return overlay_slot_picks(class_name, stat, picks)


async def retrieve_stat_gear(
    redis: aioredis.Redis,
    class_name: str,
    stat: str,
    *,
    ttl_seconds: int,
    cache_only: bool = False,
) -> str:
    """Class armor hub plus the shared rings list."""
    parts: list[str] = []
    armor = await retrieve_armor_brief(
        redis,
        class_name,
        stat,
        ttl_seconds=ttl_seconds,
        limit=5,
        brief=False,
        cache_only=cache_only,
    )
    if armor:
        parts.append(armor)
    rings = await retrieve_universal_rings(
        redis,
        stat,
        ttl_seconds=ttl_seconds,
        limit=5,
        brief=False,
        cache_only=cache_only,
    )
    if rings:
        parts.append(rings)
    return "\n\n".join(parts)


async def retrieve_wiki_scaling(
    redis: aioredis.Redis,
    class_name: str,
    *,
    stat: Optional[str] = None,
    ttl_seconds: int,
) -> str:
    """Ability infobox scaling plus armor/ring stat bonuses."""
    parts: list[str] = []
    try:
        payload = await load_class_wiki_scaling(
            redis, class_name, ttl_seconds=ttl_seconds, stat=stat
        )
        parts.append(format_wiki_scaling(payload, stat=stat))
    except Exception as e:
        logger.bind(class_name=class_name, error=str(e)).warning(
            "RealmEye wiki scaling unavailable"
        )
    if stat:
        gear = await retrieve_stat_gear(
            redis, class_name, stat, ttl_seconds=ttl_seconds
        )
        if gear:
            parts.append(gear)
    umi = await retrieve_umi_bis(redis, class_name, ttl_seconds=ttl_seconds)
    if umi:
        parts.append(umi)
    max_stats = await retrieve_class_max_stats(
        redis, class_name, ttl_seconds=ttl_seconds, stat=stat
    )
    if max_stats:
        parts.append(max_stats)
    return "\n\n".join(parts)


async def warm_all_class_scaling(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    classes: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """Scrape every class ability hub into Redis. Chat only reads this."""
    selected = [
        name
        for name in (classes or tuple(CLASS_ABILITY_HUB))
        if name in CLASS_ABILITY_HUB
    ]
    slugs = {CLASS_ABILITY_HUB[name] for name in selected}
    slugs |= {
        CLASS_ARMOR_HUB[name] for name in selected if name in CLASS_ARMOR_HUB
    }
    if classes is None:
        slugs |= set(STAT_RING_HUB.values()) | {RINGS_HUB}
    for slug in slugs:
        try:
            await _hub_index(redis, slug, ttl_seconds, force=True)
        except Exception as e:
            logger.bind(slug=slug, error=str(e)).warning(
                "Could not warm wiki hub index"
            )
    counts: dict[str, int] = {}
    for class_name in selected:
        try:
            payload = await load_class_wiki_scaling(
                redis, class_name, ttl_seconds=ttl_seconds, force=True
            )
            counts[class_name] = len(payload.get("abilities") or [])
            logger.bind(
                class_name=class_name, abilities=counts[class_name]
            ).info("Warmed class wiki scaling")
        except Exception as e:
            logger.bind(class_name=class_name, error=str(e)).warning(
                "Could not warm class wiki scaling"
            )
            counts[class_name] = 0
        try:
            await retrieve_class_max_stats(
                redis,
                class_name,
                ttl_seconds=ttl_seconds,
                cache_only=False,
                force=True,
            )
        except Exception as e:
            logger.bind(class_name=class_name, error=str(e)).warning(
                "Could not warm class max-stats table"
            )
    return counts


async def retrieve_umi_bis(
    redis: aioredis.Redis,
    class_name: str,
    *,
    ttl_seconds: int,
    cache_only: bool = False,
) -> str:
    """UmiEnjoyers general BIS — weapon/slot ideas, not stat truth."""
    cache_key = f"umi:bis:v1:{class_name.lower()}"
    cached = await redis.get(cache_key)
    if cached:
        text, url = json.loads(cached)
    elif cache_only:
        return ""
    else:
        try:
            text, url = await scrape_umi_bis(class_name)
        except Exception as e:
            logger.bind(class_name=class_name, error=str(e)).warning(
                "UmiEnjoyers BIS unavailable"
            )
            return ""
        await redis.setex(cache_key, ttl_seconds, json.dumps([text, url]))
    return (
        f"UmiEnjoyers community BIS ({class_name}, general tab). One of "
        f"three sources used together: RealmShark DPS boards first when a "
        f"board exists, this Umi page in synergy, RealmEye class-page "
        f"Maximum Achievable Stats last (that table is a max-stat stack, "
        f"not the best playstyle build). The general tab is often a generic "
        f"or Attack loadout. Do not use it as the armor, ring, or ability "
        f"pick for a non-Attack ask (e.g. do not pick Vesture of Duality "
        f"for a Wisdom robe build). For Attack robe classes, name "
        f"Diplomatic Robe and Vesture of Duality, with Flowering Kimono as "
        f"an honorable mention.\n"
        f"Source: {url}\n\n{text}"
    )


def format_class_max_stats(
    payload: dict,
    *,
    stat: Optional[str] = None,
) -> str:
    """Candidate items from the class wiki table. Last in the source rank."""
    rows = list(payload.get("rows") or [])
    if stat:
        want = stat.lower()
        rows = [row for row in rows if str(row.get("stat") or "").lower() == want]
    lines: list[str] = []
    for row in rows:
        items = []
        seen: set[str] = set()
        for name in row.get("items") or []:
            if not name or _SKIP_NAME.search(name) or _LE_CLONE.search(name):
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(name)
        if not items:
            continue
        tagged = ", ".join(f"[item:{name}]" for name in items[:6])
        lines.append(f"  {row.get('stat')}: {tagged}")
    if not lines:
        return ""
    class_name = payload.get("class_name") or "this class"
    wanted = f" ({stat})" if stat else ""
    header = (
        f"RealmEye class-page Maximum Achievable Stats for {class_name}{wanted}. "
        "Grain of salt: this table is a max-stat stack, not the best playstyle "
        "build. Rank it last after RealmShark (top 5 sets plus on-character "
        "enchants), the player overlay, and UmiEnjoyers BIS in synergy. "
        "Skip Limited Edition reskins. Example: Bard Attack on this table is "
        "often Wavecrest Concertina + Diplomatic Robe; the playstyle best is "
        "The Triangle + Vesture of Duality."
    )
    url = payload.get("url") or ""
    parts = [header, *lines]
    if url:
        parts.append(f"Source: {url}")
    return "\n".join(parts)


async def retrieve_class_max_stats(
    redis: aioredis.Redis,
    class_name: str,
    *,
    ttl_seconds: int,
    stat: Optional[str] = None,
    cache_only: bool = False,
    force: bool = False,
) -> str:
    """Stored Maximum Achievable Stats table for a class wiki page."""
    cache_key = f"{CLASS_MAXSTATS_PREFIX}:{class_name.lower()}"
    payload: dict | None = None
    if not force:
        cached = await redis.get(cache_key)
        if cached:
            payload = json.loads(cached)
        elif cache_only:
            return ""
    if payload is None:
        try:
            payload = await scrape_class_max_stats(class_name)
        except Exception as e:
            logger.bind(class_name=class_name, error=str(e)).warning(
                "Class max-stats table unavailable"
            )
            return ""
        await redis.setex(cache_key, ttl_seconds, json.dumps(payload))
    return format_class_max_stats(payload, stat=stat)
