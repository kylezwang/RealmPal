"""Forge specialist: RealmEye /wiki/forge mechanics (not enchanting).

Chat reads Redis only. Weekly refresh / warm_specialists scrape
https://www.realmeye.com/wiki/forge.
"""
from __future__ import annotations

import json
import re
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from .fuzzy_match import fuzzy_closed_vocab
from .scraper import REALMEYE_BASE, ScraperError, scrape_forge_page

CACHE_KEY = "wiki:forge:v1"
SOURCE_URL = f"{REALMEYE_BASE}/wiki/forge"
MAX_BRIEF_CHARS = 12_000

# Longest phrase aliases first (same idea as COMMUNITY_ALIASES).
_FORGE_PHRASE_ALIASES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        [
            ("vault forge", "forge"),
            ("nexus forge", "forge"),
            ("forge fire", "forgefire"),
            ("common material", "material"),
            ("rare material", "material"),
            ("legendary material", "material"),
            ("mythical material", "material"),
            ("set token", "token"),
            ("st token", "token"),
            ("craft ut", "forge"),
            ("recycle ut", "dismantle"),
        ],
        key=lambda pair: -len(pair[0]),
    )
)

_FORGE_WORD_ALIASES: tuple[tuple[str, str], ...] = (
    ("forge", "forge"),
    ("forging", "forge"),
    ("forged", "forge"),
    ("forges", "forge"),
    ("forgable", "forge"),
    ("unforgeable", "forge"),
    ("forgin", "forge"),
    ("dismantle", "dismantle"),
    ("dismantling", "dismantle"),
    ("dismantl", "dismantle"),
    ("blueprint", "blueprint"),
    ("blueprints", "blueprint"),
    ("forgefire", "forgefire"),
    ("sulphur", "sulphur"),
    ("sulfur", "sulphur"),
    ("blacksmith", "forge"),
    ("kanayama", "forge"),
    ("kanaya", "forge"),
    ("ore", "ore"),
)

_FORGE_REGEX = re.compile(
    r"\bforg(?:e|ing|ed|es|able)?\b|\bforgin\b",
    re.I,
)
_SHINY_DIVINE = re.compile(r"\b(?:shiny|divine)\b", re.I)
_CRAFT_RECYCLE = re.compile(
    r"\b(?:craft|make|create|recycle|dismantl(?:e|ing)?)\b",
    re.I,
)
_SHOW_ME = re.compile(r"\b(?:show|see|visuali[sz]e|display|preview)\b", re.I)
_ENCHANTMENT_ORB = re.compile(r"\benchantment orb\b", re.I)

_SECTION_SHINY = re.compile(
    r"exclusive|limited|upgrading|shiny",
    re.I,
)
_SECTION_FORGEFIRE = re.compile(r"forgefire|sulphur|sulfur", re.I)
_SECTION_MATERIALS = re.compile(
    r"material|dismantl|tier|cost|token",
    re.I,
)
_SECTION_DEFAULT = re.compile(
    r"default|blueprint|unlock",
    re.I,
)
_SECTION_ORE = re.compile(r"\bore\b", re.I)


def _normalize_for_aliases(text: str) -> str:
    lower = re.sub(r"\s+", " ", (text or "").lower()).strip()
    for phrase, _ in _FORGE_PHRASE_ALIASES:
        if phrase in lower:
            return lower
    return lower


def _has_forge_alias(text: str) -> bool:
    lower = _normalize_for_aliases(text)
    for phrase, _ in _FORGE_PHRASE_ALIASES:
        if phrase in lower:
            return True
    if _FORGE_REGEX.search(lower):
        return True
    for token in re.findall(r"[a-z]+", lower):
        if fuzzy_closed_vocab(token, _FORGE_WORD_ALIASES, min_len=4):
            return True
        if token in {pair[0] for pair in _FORGE_WORD_ALIASES}:
            return True
    return False


def _enchant_signal_besides_orb(message: str) -> bool:
    from .enchanting import is_enchant_query

    stripped = _ENCHANTMENT_ORB.sub(" ", message or "")
    return is_enchant_query(stripped)


def is_forge_query(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False

    from .item_aliases import is_set_visualize_query

    if is_set_visualize_query(text):
        if not _has_forge_alias(text):
            return False
    lower = text.lower()
    if _SHOW_ME.search(lower) and _SHINY_DIVINE.search(lower):
        if not _has_forge_alias(text):
            return False

    if _has_forge_alias(text):
        return True

    if _SHINY_DIVINE.search(text) and _CRAFT_RECYCLE.search(text):
        return True

    return False


def store_from_scrape(raw: dict) -> dict:
    return {
        "title": raw.get("title") or "Forge",
        "url": raw.get("url") or SOURCE_URL,
        "overview": (raw.get("overview") or "")[:2000],
        "sections": list(raw.get("sections") or []),
    }


async def load_forging_store(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    cache_only: bool = False,
    force: bool = False,
) -> dict:
    if not force:
        cached = await redis.get(CACHE_KEY)
        if cached:
            try:
                return store_from_scrape(json.loads(cached))
            except json.JSONDecodeError:
                pass
        if cache_only:
            return {}
    try:
        raw = await scrape_forge_page()
    except ScraperError as e:
        logger.bind(error=str(e)).warning("RealmEye forge page unavailable")
        return {}
    store = store_from_scrape(raw)
    await redis.setex(CACHE_KEY, ttl_seconds, json.dumps(store))
    return store


async def forging_store_status(redis: aioredis.Redis) -> dict:
    raw = await redis.get(CACHE_KEY)
    ttl = await redis.ttl(CACHE_KEY)
    sections = 0
    if raw:
        try:
            sections = len(store_from_scrape(json.loads(raw)).get("sections") or [])
        except json.JSONDecodeError:
            sections = 0
    return {
        "stored": 1 if sections else 0,
        "sections": sections,
        "ttl_seconds": max(0, int(ttl or 0)),
    }


async def warm_forging_store(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    force: bool = False,
) -> dict:
    store = await load_forging_store(
        redis, ttl_seconds=ttl_seconds, cache_only=False, force=force
    )
    sections = len(store.get("sections") or [])
    return {"stored": 1 if sections else 0, "sections": sections}


def _section_blob(section: dict) -> str:
    heading = (section.get("heading") or "").strip()
    text = (section.get("text") or "").strip()
    parts = [f"### {heading}"] if heading else []
    if text:
        parts.append(text)
    for table in section.get("tables") or []:
        rows = table.get("rows") or []
        if not rows:
            continue
        lines = []
        for row in rows[:40]:
            lines.append(" | ".join(str(c) for c in row))
        if lines:
            parts.append("\n".join(lines))
    return "\n\n".join(parts).strip()


def _pick_sections(
    sections: list[dict],
    *,
    message: str,
    item_names: list[str],
) -> list[dict]:
    lower = (message or "").lower()
    picked: list[dict] = []
    seen: set[str] = set()

    def add(section: dict) -> None:
        key = (section.get("heading") or "").lower()
        if key in seen:
            return
        seen.add(key)
        picked.append(section)

    def by_heading(pattern: re.Pattern[str]) -> None:
        for sec in sections:
            if pattern.search(sec.get("heading") or ""):
                add(sec)

    shiny_ask = bool(_SHINY_DIVINE.search(message)) or "shiny" in lower
    generic = not any(
        re.search(
            r"\b(?:forgefire|sulphur|sulfur|dismantl|tier|material|blueprint|ore|token|upgrade)\b",
            lower,
            re.I,
        )
        for _ in [0]
    )

    if shiny_ask or generic:
        by_heading(re.compile(r"exclusive|limited", re.I))
        by_heading(re.compile(r"upgrading", re.I))

    if re.search(r"forgefire|sulphur|sulfur", lower, re.I):
        by_heading(_SECTION_FORGEFIRE)

    if re.search(r"dismantl|tier|material|token", lower, re.I):
        by_heading(re.compile(r"materials|tiers", re.I))

    if re.search(r"blueprint|default|unlock", lower, re.I):
        by_heading(_SECTION_DEFAULT)

    if re.search(r"\bore\b", lower, re.I):
        by_heading(_SECTION_ORE)

    if re.search(r"\bupgrade", lower, re.I):
        by_heading(re.compile(r"upgrading", re.I))

    if item_names:
        for sec in sections:
            blob = _section_blob(sec).lower()
            if any(name.lower() in blob for name in item_names):
                add(sec)

    if generic and len(picked) < 3:
        by_heading(re.compile(r"^materials$|^forgefire$", re.I))
        if not picked:
            for sec in sections[:4]:
                add(sec)

    return picked


def _format_table_rows_for_items(
    sections: list[dict], item_names: list[str], message: str = ""
) -> str:
    needles = [n.lower() for n in item_names]
    if not needles:
        needles = [
            w
            for w in re.findall(r"[a-z']+", (message or "").lower())
            if len(w) >= 5 and w not in {"forge", "upgrade", "possible", "shiny"}
        ]
    if not needles:
        return ""
    lines: list[str] = []
    for sec in sections:
        for table in sec.get("tables") or []:
            for row in table.get("rows") or []:
                joined = " | ".join(str(c) for c in row).lower()
                if any(n in joined for n in needles):
                    lines.append(" | ".join(str(c) for c in row))
    return "\n".join(lines[:24])


async def retrieve_forging_brief(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int,
    cache_only: bool = True,
) -> str:
    store = await load_forging_store(
        redis, ttl_seconds=ttl_seconds, cache_only=cache_only
    )
    sections = list((store or {}).get("sections") or [])
    url = store.get("url") or SOURCE_URL

    parts = [
        "FORGE AGENT — RealmEye /wiki/forge only. "
        "Forging (Blacksmith / Kanayama) is not Enchanting (Enchanter). "
        "Never cite /wiki/enchanting or enchant roll rarity for forge answers. "
        "Copy rules from this chunk only. "
        f"Source: {url}",
        "Shiny forging (RealmEye): Most shiny items cannot be forged. "
        "Dismantling a shiny gives the same materials as the normal item. "
        "The only shinies that can be forged are upgraded outputs and require "
        "both a shiny base item and a shiny token. "
        "A shiny base cannot be used to craft a non-shiny upgrade "
        "(workaround: forge a regular copy from the shiny base, then upgrade).",
    ]

    if not sections:
        parts.append(
            "Forge store is empty. Do not invent forge rules. Do not answer from enchanting."
        )
        return "\n\n".join(parts)

    item_names: list[str] = []
    try:
        from .item_aliases import (
            community_canonical,
            extract_mentioned_items,
            resolve_item_query,
        )

        for name in extract_mentioned_items(message):
            resolved = community_canonical(name) or await resolve_item_query(
                redis,
                name,
                ttl_seconds=ttl_seconds,
                allow_scrape=False,
            )
            item_names.append(resolved or name)
    except Exception:
        item_names = []

    picked = _pick_sections(sections, message=message, item_names=item_names)
    overview = (store.get("overview") or "").strip()
    if overview and len(picked) <= 2:
        parts.append(overview[:900])

    for sec in picked:
        blob = _section_blob(sec)
        if blob:
            parts.append(blob[:3500])

    item_rows = _format_table_rows_for_items(sections, item_names, message)
    if item_rows:
        parts.append("Matching upgrade / default rows:\n" + item_rows)

    text = "\n\n".join(parts)
    if len(text) > MAX_BRIEF_CHARS:
        text = text[: MAX_BRIEF_CHARS - 3] + "..."
    return text
