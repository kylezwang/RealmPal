"""DPS specialist: wiki item shot data + RealmShark potential-DPS boards.

Wiki numbers are the inputs. RealmShark is a 5s / 8-ability reference
board, not live combat. Chat is cache_only.
"""
from __future__ import annotations

import re
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from ..models.item import ItemProfile
from .wiki_scaling import ITEM_CACHE_PREFIX

_DPS_WORD = re.compile(
    r"\b(dps|damage\s+per\s+second|potential[- ]dps)\b",
    re.I,
)
_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)")
_NUM = re.compile(r"(\d+(?:\.\d+)?)")
_ON_ITEM = re.compile(
    r"\b(?:of|for|for a|on)\s+(?:the\s+)?(.+?)\s*$",
    re.I,
)

# RealmEye Dex vs Att: 1.5 APS at 0 DEX, 8 APS at 75 DEX, times Rate of Fire.
_BASE_APS = 1.5
_DEX_APS = 6.5
_DEX_CAP = 75.0
_DEFAULT_DEX = 75.0


def is_dps_query(message: str) -> bool:
    return bool(_DPS_WORD.search(message or ""))


def parse_damage_range(text: str) -> Optional[tuple[float, float]]:
    if not text:
        return None
    match = _RANGE.search(text)
    if match:
        return float(match.group(1)), float(match.group(2))
    num = _NUM.search(text)
    if num:
        value = float(num.group(1))
        return value, value
    return None


def parse_shots(text: str) -> float:
    if not text:
        return 1.0
    num = _NUM.search(text)
    return float(num.group(1)) if num else 1.0


def parse_rof(text: str) -> float:
    """Wiki Rate of Fire: 100% → 1.0, 1.2 → 1.2x."""
    if not text:
        return 1.0
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if pct:
        return float(pct.group(1)) / 100.0
    num = _NUM.search(text)
    if not num:
        return 1.0
    value = float(num.group(1))
    return value / 100.0 if value > 3 else value


def attacks_per_second(*, dex: float, rof: float) -> float:
    return (_BASE_APS + _DEX_APS * (dex / _DEX_CAP)) * rof


def estimate_weapon_dps(
    stats: dict,
    *,
    dex: float = _DEFAULT_DEX,
) -> Optional[dict]:
    damage = parse_damage_range(str(stats.get("Damage") or stats.get("damage") or ""))
    if not damage:
        return None
    low, high = damage
    avg = (low + high) / 2.0
    shots = parse_shots(str(stats.get("Shots") or stats.get("shots") or "1"))
    rof = parse_rof(
        str(stats.get("Rate of Fire") or stats.get("Fire Rate") or stats.get("RoF") or "")
    )
    aps = attacks_per_second(dex=dex, rof=rof)
    return {
        "min": low,
        "max": high,
        "avg": avg,
        "shots": shots,
        "rof": rof,
        "dex": dex,
        "aps": aps,
        "dps": avg * shots * aps,
    }


def extract_dps_item(message: str) -> Optional[str]:
    from .item_aliases import community_canonical, extract_mentioned_items

    mentioned = extract_mentioned_items(message)
    if mentioned:
        return mentioned[0]
    text = (message or "").strip()
    match = _ON_ITEM.search(text)
    candidate = (match.group(1) if match else "").strip(" ?.!")
    if candidate:
        canonical = community_canonical(candidate)
        if canonical:
            return canonical
        if 1 <= len(candidate.split()) <= 6:
            return candidate
    for token in re.findall(r"\b[A-Za-z][A-Za-z']+\b", text):
        canonical = community_canonical(token)
        if canonical:
            return canonical
    return None


def _wiki_stat_lines(item: ItemProfile) -> list[str]:
    keys = (
        "Damage",
        "Shots",
        "Rate of Fire",
        "Fire Rate",
        "Projectile Speed",
        "Range",
        "Impact",
        "Effect(s)",
        "On Equip",
    )
    lines = []
    stats = item.stats or {}
    for key in keys:
        value = stats.get(key)
        if value:
            lines.append(f"- {key}: {value}")
    return lines


def format_wiki_estimate(item: ItemProfile, estimate: Optional[dict]) -> str:
    lines = [
        f"WIKI ITEM DATA — [item:{item.name}]",
        f"Source: {item.wiki_url or 'RealmEye item page'}",
    ]
    lines.extend(_wiki_stat_lines(item))
    if estimate:
        lines.extend(
            [
                "",
                "Approximate weapon DPS (0 DEF, no procs, no ability):",
                f"- Formula: avg damage × shots × (1.5 + 6.5 × DEX/75) × Rate of Fire",
                f"- DEX assumed: {estimate['dex']:.0f} (8/8 cap unless the user gave another)",
                f"- Avg damage {estimate['avg']:.1f} × {estimate['shots']:.0f} shot(s) × "
                f"{estimate['aps']:.2f} APS = **{estimate['dps']:.1f}**",
            ]
        )
    else:
        lines.append(
            "No Damage row on the stored wiki profile — do not invent a DPS number."
        )
    return "\n".join(lines)


async def _cached_item(redis: aioredis.Redis, name: str) -> Optional[ItemProfile]:
    raw = await redis.get(f"{ITEM_CACHE_PREFIX}:{name.lower()}")
    if not raw:
        return None
    try:
        return ItemProfile.model_validate_json(raw)
    except Exception:
        return None


async def retrieve_dps_brief(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int,
    class_name: Optional[str] = None,
    stat: Optional[str] = None,
    cache_only: bool = True,
) -> str:
    from .item_aliases import community_canonical, extract_mentioned_items, resolve_item_query
    from .realmshark import format_loadouts, load_graph, load_top_loadouts

    parts = [
        "DPS AGENT — RealmEye wiki item shot data for the formula; "
        "RealmShark boards are a 5s / 8-ability potential-DPS reference, "
        "not live combat. Do not invent numbers missing from this chunk."
    ]
    mentioned = extract_mentioned_items(message)
    item_name = mentioned[0] if mentioned else extract_dps_item(message)
    names = mentioned or ([item_name] if item_name else [])
    for raw in names:
        resolved = community_canonical(raw) or await resolve_item_query(
            redis,
            raw,
            ttl_seconds=ttl_seconds,
            class_name=class_name,
            allow_scrape=False,
        )
        lookup = resolved or raw
        item = await _cached_item(redis, lookup)
        if item:
            estimate = estimate_weapon_dps(item.stats or {})
            parts.append(format_wiki_estimate(item, estimate))
        else:
            parts.append(
                f"No stored wiki profile for {lookup}. "
                "Do not invent Damage / Shots / Rate of Fire."
            )
    if len(names) > 1:
        parts.append(
            "Compare the wiki estimates above and pick a winner only from "
            "those numbers. Do not invent a third item."
        )

    try:
        graph = await load_graph(redis, ttl_seconds, cache_only=True)
    except Exception as e:
        logger.bind(error=str(e)).warning("DPS specialist could not load RealmShark graph")
        return "\n\n".join(parts)

    matched = graph.edges
    if class_name:
        matched = [e for e in matched if e.class_name.lower() == class_name.lower()]
    if stat:
        matched = [e for e in matched if e.stat.lower() == stat.lower()]
    if not matched:
        if class_name or stat:
            parts.append(
                "No RealmShark potential-DPS board for this class/stat. "
                "Use the wiki estimate only."
            )
        return "\n\n".join(parts)

    shark_bits = []
    for edge in matched[:3]:
        loadouts = await load_top_loadouts(
            redis,
            edge,
            season=graph.season,
            ttl_seconds=ttl_seconds,
            cache_only=True,
        )
        formatted = format_loadouts(edge.label, loadouts)
        if formatted:
            shark_bits.append(formatted)
        if loadouts and not item_name:
            by_slot = {s.slot.lower(): s.item_name for s in loadouts[0].equipment}
            weapon = by_slot.get("weapon") or loadouts[0].weapon_name
            if weapon:
                item = await _cached_item(redis, weapon)
                if item:
                    estimate = estimate_weapon_dps(item.stats or {})
                    parts.append(format_wiki_estimate(item, estimate))
                    item_name = weapon
    if shark_bits:
        parts.append("\n\n".join(shark_bits))
    return "\n\n".join(parts)
