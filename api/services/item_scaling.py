"""Single-item scaling questions (infobox formulas, not class ability hubs).

Found live Sep 22: after a correct ATT answer on Scepter of Devastation,
"What about scaling off wis?" lost the item, pulled unrelated class-hub
RAG, and invented family-wide rules. This specialist reads the cached
item profile via scaling_from_item() for every formula row.
"""
from __future__ import annotations

import re
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from .item_aliases import (
    community_canonical,
    extract_mentioned_items,
    resolve_item_query,
)
from .scraper import REALMEYE_BASE
from .wiki_scaling import read_cached_item, scaling_from_item

_ITEM_TOKEN_RE = re.compile(r"\[item:([^\]]+)\]", re.I)

_SCALE_ASK = re.compile(
    r"\b(?:scale|scales|scaling)\s+(?:off|with|on)\b"
    r"|\b(?:does|do)\s+.+\s+scale\s+(?:off|with)\b",
    re.I,
)
_FOLLOWUP = re.compile(r"\b(?:what about|how about)\b", re.I)
_STAT_IN_MESSAGE = re.compile(
    r"\b(?:hp|mp|att|atk|attack|def|defense|spd|speed|dex|dexterity|"
    r"vit|vitality|wis|wisdom|life|mana)\b",
    re.I,
)


def _item_name_from_message(message: str) -> Optional[str]:
    mentioned = extract_mentioned_items(message or "")
    if len(mentioned) == 1:
        return mentioned[0]
    if mentioned:
        return mentioned[0]
    tokens = [t.strip() for t in _ITEM_TOKEN_RE.findall(message or "") if t.strip()]
    if len(tokens) == 1:
        return tokens[0]
    return None


def last_item_from_scaling_history(history: Optional[list[str]]) -> Optional[str]:
    """Most recent wiki item tied to a scaling question in this chat."""
    if not history:
        return None
    for prev in reversed(history):
        text = prev or ""
        if not text.strip():
            continue
        name = _item_name_from_message(text)
        if name and _SCALE_ASK.search(text):
            return name
        tokens = [t.strip() for t in _ITEM_TOKEN_RE.findall(text) if t.strip()]
        if len(tokens) == 1 and _SCALE_ASK.search(text):
            return tokens[0]
    for prev in reversed(history):
        name = _item_name_from_message(prev or "")
        if name:
            return name
        tokens = [t.strip() for t in _ITEM_TOKEN_RE.findall(prev or "") if t.strip()]
        if len(tokens) == 1:
            return tokens[0]
    return None


def _prior_scaling_turn(history: Optional[list[str]]) -> bool:
    if not history:
        return False
    for prev in reversed(history):
        if _SCALE_ASK.search(prev or ""):
            return True
    return False


def is_item_scaling_query(
    message: str, history: Optional[list[str]] = None
) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    if re.search(r"\b(?:build|loadout|best items?|gear)\b", text, re.I):
        return False

    if _SCALE_ASK.search(text):
        if _item_name_from_message(text):
            return True
        if history and last_item_from_scaling_history(history):
            return True

    if history and _FOLLOWUP.search(text):
        if _SCALE_ASK.search(text) or _STAT_IN_MESSAGE.search(text):
            if _prior_scaling_turn(history) or last_item_from_scaling_history(
                history
            ):
                return True
    return False


def _requested_stat(message: str) -> Optional[str]:
    from ..models.build import STAT_ALIASES
    from .fuzzy_match import fuzzy_closed_vocab

    lower = (message or "").lower()
    stats: list[str] = []
    seen: set[str] = set()
    for alias in sorted(STAT_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", lower):
            canon = STAT_ALIASES[alias]
            if canon not in seen:
                seen.add(canon)
                stats.append(canon)
    if len(stats) == 1:
        return stats[0]
    for token in re.findall(r"[a-z]+", lower):
        canon = fuzzy_closed_vocab(token, [(a, STAT_ALIASES[a]) for a in STAT_ALIASES])
        if canon:
            return canon
    return None


def _slug_url(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return f"{REALMEYE_BASE}/wiki/{slug}"


async def retrieve_item_scaling_brief(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int,
    history: Optional[list[str]] = None,
    cache_only: bool = True,
) -> str:
    item_name = _item_name_from_message(message) or last_item_from_scaling_history(
        history
    )
    if not item_name:
        return (
            "ITEM SCALING AGENT - No item name in this turn or recent history. "
            "Do not guess scaling or generalize about weapon/ability families."
        )

    resolved = community_canonical(item_name) or await resolve_item_query(
        redis,
        item_name,
        ttl_seconds=ttl_seconds,
        allow_scrape=not cache_only,
    )
    item_name = resolved or item_name
    item = await read_cached_item(redis, item_name)
    if not item and not cache_only:
        resolved = await resolve_item_query(
            redis,
            item_name,
            ttl_seconds=ttl_seconds,
            allow_scrape=True,
        )
        if resolved:
            item_name = resolved
            item = await read_cached_item(redis, item_name)

    scales = scaling_from_item(item) if item else {}
    url = _slug_url(item_name)
    asked = _requested_stat(message)

    parts = [
        "ITEM SCALING AGENT - RealmEye item infobox only. "
        "Copy every formula row below; do not invent stats. "
        "One item can scale with multiple stats (e.g. main Damage with "
        "Wisdom and Shockblast lines with Attack). Never say an entire "
        "item family (scepters, bows, staves) all scale with one stat. "
        f"Source: {url}",
        f"Item: [item:{item_name}]",
    ]

    if not scales:
        parts.append(
            "No scaling formulas are stored for this item yet. "
            "Say you do not have the infobox formulas in context rather "
            "than guessing or citing a class ability hub."
        )
        if item and item.stats:
            parts.append("Raw infobox rows (unparsed):")
            for key, val in list(item.stats.items())[:24]:
                if not re.search(r"on equip|feed power|xp bonus|forging|dust", str(key), re.I):
                    parts.append(f"  {key}: {val}")
        return "\n\n".join(parts)

    stat_list = ", ".join(sorted(scales.keys()))
    parts.append(f"Scaling stats on this item: {stat_list}.")

    for stat, evidence in sorted(scales.items()):
        parts.append(f"{stat}:\n  {evidence}")

    if asked:
        if asked in scales:
            parts.append(
                f"User asked about {asked}: yes - copy the {asked} lines above."
            )
        else:
            parts.append(
                f"User asked about {asked}: no formula row on this item uses "
                f"{asked} (only {stat_list or 'none listed'})."
            )

    return "\n\n".join(parts)
