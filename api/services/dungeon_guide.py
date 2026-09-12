"""Dungeon-guide specialist: RealmEye indexes, then the linked pages.

Chat scrapes https://www.realmeye.com/wiki/dungeon-guides and
https://www.realmeye.com/wiki/dungeons, matches the user's dungeon
against those links, and follows the matching guide + dungeon pages.
"""
from __future__ import annotations

import json
import re
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from .scraper import (
    REALMEYE_BASE,
    ScraperError,
    scrape_dungeon_indexes,
    scrape_wiki_article,
)

INDEX_CACHE_KEY = "wiki:dungeon-index:v4"
PAGE_CACHE_PREFIX = "wiki:guide:v6:"
MAX_PAGE_CHARS = 16000
_PRIORITY_SECTION = re.compile(
    r"(?:^|\n)((?:Shrine|Rice Field|Resting Grounds|Example Layout|"
    r"Drops of Interest|Leisurely Mode|Challenge Mode|True Umi|"
    r"Kitsune Umi|Fishing|Village Girl Umi)\b[\s\S]{0,4000})",
    re.IGNORECASE,
)

INDEX_URLS = (
    f"{REALMEYE_BASE}/wiki/dungeon-guides",
    f"{REALMEYE_BASE}/wiki/dungeons",
)

# Abbreviations that do not appear as wiki titles. Expanded before matching
# against the scraped index, not used as a dungeon list.
_NICKNAMES = {
    "shatts": "shatters",
    "lh": "lost halls",
    "o3": "oryx sanctuary",
    "o2": "wine cellar",
    "udl": "undead lair",
    "mv": "moonlight village",
}

_GUIDE_RE = re.compile(
    r"(?:"
    r"guide\s+to\s+complete|"
    r"guide\s+to\s+(?:beat|clear|finish)|"
    r"how\s+(?:do\s+i|to)\s+(?:complete|beat|clear|finish)|"
    r"walkthrough\s+(?:for|of)|"
    r"(?:dungeon\s+)?guide\s+(?:for|to)"
    r")\s+(.+?)\s*$",
    re.IGNORECASE,
)
_MODE_PREFIX = re.compile(r"^(?:hard\s*mode|hardmode|hm|easy\s*mode|easy)\s+", re.I)
_HARD_MODE_RE = re.compile(r"hard\s*mode|hardmode|\bhm\b", re.I)
_PUNCT_TAIL = re.compile(r"[?.!]+$")
_SOURCE_SLUG = "the-source"
_SOURCE_SPRITE_FALLBACK = "https://www.realmeye.com/s/a/img/wiki/i/bdfzUM2.png"
_HM_SHATTERS_TIP = (
    "To keep hardmode, kill the Source (the purple dome) during the clear to "
    "the second boss, Nox the Wild Shadow. After the dome, drag all 4 "
    "branches/flames to the center. Do not mention wings — that mechanic is "
    "regular The Shatters, not Hardmode."
)
_HM_CHRYSALIS_NOTE = (
    "Chrysalis of Eternity is a very low chance from King Azamoth. "
    "Never call it a high chance, common, likely, or a high drop rate. "
    "If the wiki says high chance, that is wrong — say very low chance."
)
_HM_AZAMOTH_NOTE = (
    "For your fight against King Azamoth, patience will be almost twice as "
    "long as regular Shatters and you will need heavy damage to defeat "
    "The Shattered Queen."
)
_HM_BOSS_ORDER_NOTE = (
    "Hard Mode has exactly three boss fights, in this order only: "
    "(1) Valen the Unbreakable, (2) Nox the Wild Shadow, "
    "(3) King Azamoth and The Shattered Queen. "
    "Do not list The Bridge Sentinel, Twilight Archmage, or The Forgotten King "
    "as Hard Mode bosses. Do not put Valen in the Throne Room or after Nox. "
    "Valen is the first fight, Nox is the second, Azamoth and the Queen are last."
)
_HM_IDOL_NOTE = (
    "Before the first boss fight, you must kill the Stone Idol by finding "
    "the Void Phantasm. Do not break all 8 monuments until the Idol is dead. "
    "Do not tell players to finish all 8 monuments first."
)
_CHRYSALIS_HYPE = re.compile(
    r"(?:a\s+)?(?:significantly\s+)?(?:high(?:er)?|great|good|strong)\s+"
    r"chance\s+(?:at|for|of|to(?:\s+drop)?)\s+(?:the\s+)?"
    r"Chrysalis(?:\s+of\s+Eternity)?",
    re.I,
)
_FOLLOWUP_RE = re.compile(
    r"\b(hard\s*mode|boss(?:es)?|route|phases?|unlock|walkthrough|"
    r"magi-?generators?|void phantasm)\b",
    re.IGNORECASE,
)
_STOP = {"the", "a", "an", "of", "and", "portal", "dungeon"}
_POTION_NAME = re.compile(r"\bpotion\b", re.I)
_MARK_NAME = re.compile(r"\bmark\b", re.I)
_GENERIC_TIER = re.compile(
    r"^tier\s+\d+\s+(?:alternate\s+)?(?:abilities|ability|rings?|weapons?|armou?r)s?\b",
    re.I,
)
_PET_SKIN = re.compile(r"(?:pet\s+)?skins?$", re.I)


def _name_from_guide_match(message: str) -> Optional[str]:
    text = _PUNCT_TAIL.sub("", (message or "").strip())
    match = _GUIDE_RE.search(text)
    if not match:
        return None
    name = match.group(1).strip()
    name = re.sub(r"^(?:the\s+)?dungeon\s+", "", name, flags=re.I)
    name = re.sub(r"\s+dungeon$", "", name, flags=re.I)
    return name or None


def extract_dungeon_query(
    message: str,
    history: Optional[list[str]] = None,
) -> Optional[str]:
    """Pull the dungeon name from this turn, or from a prior guide follow-up."""
    direct = _name_from_guide_match(message)
    if direct:
        return direct
    if history and _FOLLOWUP_RE.search(message or ""):
        for prev in reversed(history):
            found = _name_from_guide_match(prev)
            if found:
                return found
    return None


def _normalize(name: str) -> str:
    cleaned = re.sub(r"['’]", "", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    parts = [_NICKNAMES.get(p, p) for p in cleaned.split()]
    return " ".join(parts)


def _core(name: str) -> str:
    """Drop mode prefixes and leading 'the' so Hardmode Shatters → shatters."""
    text = _MODE_PREFIX.sub("", _normalize(name)).strip()
    text = re.sub(r"^the\s+", "", text)
    text = re.sub(r"\s+portal$", "", text)
    return text


def _tokens(name: str) -> set[str]:
    return {t for t in _core(name).split() if t and t not in _STOP}


def _wants_hard_mode(query: str) -> bool:
    return bool(_HARD_MODE_RE.search(query or ""))


def _is_shatters_query(query: str) -> bool:
    return "shatter" in _normalize(query)


def _is_hardmode_shatters(query: str) -> bool:
    return _wants_hard_mode(query) and _is_shatters_query(query)


def _merge_drop_sources(existing: str, incoming: str) -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for chunk in (existing, incoming):
        for part in re.split(r",\s*", chunk or ""):
            name = part.strip()
            key = name.lower()
            if name and key not in seen:
                seen.add(key)
                parts.append(name)
    return ", ".join(parts)


def _is_potion_drop(name: str) -> bool:
    """HP/MP/stat potions are noise on dungeon drop lists; Marks stay."""
    text = (name or "").strip()
    if not text or _MARK_NAME.search(text):
        return False
    return bool(_POTION_NAME.search(text))


def _is_generic_tier_drop(name: str) -> bool:
    """Wiki 'Tier 6 Abilities' rows are category links, not item cards."""
    return bool(_GENERIC_TIER.search((name or "").strip()))


def _is_pet_skin_drop(name: str) -> bool:
    return bool(_PET_SKIN.search((name or "").strip()))


def _skip_dungeon_drop(name: str) -> bool:
    return (
        _is_potion_drop(name)
        or _is_generic_tier_drop(name)
        or _is_pet_skin_drop(name)
    )


def _strip_potion_drop_lines(text: str) -> str:
    """Drop short potion / generic-tier rows from scraped wiki text."""
    kept: list[str] = []
    for line in (text or "").splitlines():
        cell = re.sub(r"^[\s|*-]+", "", line).split("|")[0].strip()
        if cell and len(cell) < 60 and _skip_dungeon_drop(cell) and not re.search(r"[.!?]", cell):
            continue
        kept.append(line)
    return "\n".join(kept)


def _score_entry(query: str, entry: dict) -> int:
    title = entry.get("title") or ""
    slug = (entry.get("slug") or "").replace("-", " ")
    q = _core(query)
    t = _core(title)
    if not q or not t:
        return 0
    if q == t:
        return 100
    if t.startswith(q) or q.startswith(t):
        return 80 + min(len(t), 15)
    if q in t or t in q:
        return 70 + min(len(t), 15)
    s = _core(slug.replace(" guide", ""))
    if q == s or q in s:
        return 60
    qtoks = _tokens(query)
    ttoks = _tokens(title)
    if qtoks and qtoks <= ttoks:
        return 55 + 5 * len(qtoks)
    overlap = qtoks & ttoks
    if overlap:
        return 25 + 10 * len(overlap)
    return 0


def match_index_pages(query: str, entries: list[dict]) -> list[dict]:
    """Pick the best guide + dungeon pages from the scraped indexes."""
    scored: list[tuple[int, dict]] = []
    for entry in entries:
        score = _score_entry(query, entry)
        if score >= 55:
            scored.append((score, entry))
    scored.sort(key=lambda pair: (pair[0], pair[1].get("kind") == "guide"), reverse=True)

    picked: list[dict] = []
    seen: set[str] = set()
    for _score, entry in scored:
        slug = entry.get("slug") or ""
        if not slug or slug in seen:
            continue
        seen.add(slug)
        picked.append(entry)
        if len(picked) >= 2:
            break

    # Dungeon pages hold secrets the WIP guide pages often omit (Umi quiz).
    dungeons = [e for e in picked if e.get("kind") != "guide"]
    guides = [e for e in picked if e.get("kind") == "guide"]
    return (dungeons + guides)[:2]


def _focus_text(text: str, query: str) -> str:
    """Keep Hard Mode plus shrine/Umi/layout/drops even when trimming."""
    body = text or ""
    parts: list[str] = []
    if _wants_hard_mode(query):
        match = re.search(r"(^Hard Mode\s*$[\s\S]{0,7000})", body, re.I | re.M)
        if match:
            parts.append(body[:1800])
            parts.append(match.group(1))
    if not parts:
        parts.append(body[:MAX_PAGE_CHARS])
    for match in _PRIORITY_SECTION.finditer(body):
        chunk = match.group(1).strip()
        if chunk and chunk not in "\n".join(parts):
            parts.append(chunk)
    focused = _strip_potion_drop_lines("\n\n".join(parts))
    if _is_hardmode_shatters(query):
        focused = _CHRYSALIS_HYPE.sub(
            "a very low chance at the Chrysalis of Eternity", focused
        )
        focused = re.sub(
            r"high chance at(?: the)? Chrysalis of Eternity",
            "very low chance at the Chrysalis of Eternity",
            focused,
            flags=re.I,
        )
    return focused


async def get_or_scrape_index(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    force: bool = False,
    cache_only: bool = False,
) -> list[dict]:
    if not force:
        cached = await redis.get(INDEX_CACHE_KEY)
        if cached:
            return json.loads(cached)
        if cache_only:
            return []
    entries = await scrape_dungeon_indexes()
    await redis.setex(INDEX_CACHE_KEY, ttl_seconds, json.dumps(entries))
    return entries


async def get_or_scrape_wiki(
    redis: aioredis.Redis,
    slug: str,
    *,
    ttl_seconds: int,
    force: bool = False,
    cache_only: bool = False,
) -> Optional[dict[str, str]]:
    cache_key = f"{PAGE_CACHE_PREFIX}{slug}"
    if not force:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
        if cache_only:
            return None

    try:
        payload = await scrape_wiki_article(slug)
    except ScraperError as e:
        logger.bind(slug=slug, error=str(e)).warning("Dungeon wiki scrape missed")
        await redis.setex(cache_key, min(ttl_seconds, 1800), json.dumps(None))
        return None

    payload["text"] = (payload.get("text") or "")[:20000]
    await redis.setex(cache_key, ttl_seconds, json.dumps(payload))
    logger.bind(slug=slug, title=payload.get("title")).info(
        "Cached RealmEye dungeon page"
    )
    return payload


async def retrieve_dungeon_guide(
    redis: aioredis.Redis,
    dungeon_name: str,
    *,
    ttl_seconds: int,
    cache_only: bool = False,
) -> str:
    """Match a dungeon on the RealmEye indexes, then scrape those linked pages."""
    try:
        entries = await get_or_scrape_index(
            redis, ttl_seconds=ttl_seconds, cache_only=cache_only
        )
    except Exception as e:
        logger.bind(error=str(e)).warning("Dungeon index unavailable")
        return (
            "No RealmEye dungeon index could be scraped. "
            "Say you could not load the guide rather than inventing a route. "
            f"Tried {INDEX_URLS[0]} and {INDEX_URLS[1]}."
        )

    matches = match_index_pages(dungeon_name, entries)
    if not matches:
        return (
            "The RealmEye dungeon indexes have no page that matches this "
            f"dungeon ({dungeon_name}). Say so rather than inventing a route. "
            f"Source: {INDEX_URLS[0]}\nSource: {INDEX_URLS[1]}"
        )

    pages: list[dict[str, str]] = []
    for entry in matches:
        page = await get_or_scrape_wiki(
            redis,
            entry["slug"],
            ttl_seconds=ttl_seconds,
            cache_only=cache_only,
        )
        if page:
            pages.append(page)

    if not pages:
        return (
            "The matching RealmEye dungeon links could not be scraped. "
            "Say you could not load the guide rather than inventing a route. "
            f"Source: {INDEX_URLS[0]}\nSource: {INDEX_URLS[1]}"
        )

    media = await _finalize_media(
        redis,
        dungeon_name,
        pages,
        matches,
        ttl_seconds=ttl_seconds,
        cache_only=cache_only,
    )
    index_cite = "\n".join(f"Source: {url}" for url in INDEX_URLS)
    blocks: list[str] = [_media_instructions(media)]
    for page in pages:
        focused = _focus_text(page.get("text") or "", dungeon_name)
        blocks.append(
            "RealmEye dungeon page, reached from the official dungeon "
            "indexes. Use this walkthrough for the route, shrine/NPC quiz "
            "answers, hard-mode steps, and bosses. Copy shrine Q&A lines "
            "exactly when they appear (players need them to start Kitsune "
            "Umi solo). Do not invent mechanics that are not on this page.\n"
            f"{index_cite}\nSource: {page.get('url')}\n\n"
            f"# {page.get('title')}\n{focused}"
        )
    return "\n\n---\n\n".join(blocks)


def _merge_media(pages: list[dict], matches: list[dict]) -> dict:
    portal = None
    graves_url = None
    difficulty = None
    title = ""
    url = ""
    layouts: list[dict] = []
    drops: list[dict] = []
    seen_layout: set[str] = set()
    seen_drop: set[str] = set()
    for page in pages:
        slug = (page.get("url") or "").rsplit("/", 1)[-1]
        if not title or not slug.endswith("-guide"):
            title = page.get("title") or title
            url = page.get("url") or url
        if page.get("portal_url") and (
            not portal or not slug.endswith("-guide")
        ):
            portal = page.get("portal_url")
        if page.get("graves_url") and not graves_url:
            graves_url = page.get("graves_url")
        if page.get("difficulty") is not None:
            difficulty = page.get("difficulty")
        for layout in page.get("layouts") or []:
            src = layout.get("url")
            if src and src not in seen_layout:
                seen_layout.add(src)
                layouts.append(layout)
        for drop in page.get("drops") or []:
            key = (drop.get("name") or "").lower()
            if not key or _skip_dungeon_drop(drop.get("name") or ""):
                continue
            if key in seen_drop:
                prev = next(d for d in drops if (d.get("name") or "").lower() == key)
                prev["drops_from"] = _merge_drop_sources(
                    prev.get("drops_from") or "", drop.get("drops_from") or ""
                )
                if not prev.get("sprite_url") and drop.get("sprite_url"):
                    prev["sprite_url"] = drop.get("sprite_url")
                continue
            seen_drop.add(key)
            drops.append(drop)
    for entry in matches:
        if entry.get("portal_url") and not portal:
            portal = entry.get("portal_url")
        if entry.get("difficulty") is not None and difficulty is None:
            difficulty = entry.get("difficulty")
        if not title:
            title = entry.get("title") or title
    return {
        "title": title,
        "url": url,
        "portal_url": portal,
        "graves_url": graves_url,
        "difficulty": difficulty,
        "layouts": layouts,
        "drops": drops,
        "tips": [],
    }


async def _finalize_media(
    redis: aioredis.Redis,
    query: str,
    pages: list[dict],
    matches: list[dict],
    *,
    ttl_seconds: int,
    cache_only: bool = False,
) -> dict:
    media = _merge_media(pages, matches)
    if not _is_hardmode_shatters(query):
        return media
    source = await get_or_scrape_wiki(
        redis, _SOURCE_SLUG, ttl_seconds=ttl_seconds, cache_only=cache_only
    )
    media["portal_url"] = (source or {}).get("portal_url") or _SOURCE_SPRITE_FALLBACK
    media["tips"] = [_HM_SHATTERS_TIP]
    media["notes"] = [
        _HM_BOSS_ORDER_NOTE,
        _HM_IDOL_NOTE,
        _HM_CHRYSALIS_NOTE,
        _HM_AZAMOTH_NOTE,
    ]
    media["large_portal"] = True
    title = re.sub(
        r"\s*[-–—]\s*the RotMG Wiki.*$", "", media.get("title") or "The Shatters"
    ).strip()
    if "hard" not in title.lower():
        media["title"] = f"{title} Hard Mode"
    return media


def _media_instructions(media: dict) -> str:
    lines = [
        "DUNGEON MEDIA from RealmEye. The UI already shows the portal sprite "
        "and grave rating above the title, and the full Drops of Interest "
        "list from the wiki table. Still include Example Layout images using "
        "the exact markdown below. If a Shrine / Village Girl Umi quiz is in the chunk, add "
        "## Kitsune Umi with the exact questions and answers (Mushroom, "
        "Carosburg, The Happy Prince when those are the listed answers), "
        "note to wait a few seconds before answering, and that a correct "
        "answer can unlock the Kitsune Umi fight. Never emit [item:] tokens "
        "for potions (Health, Magic, Greater Potion of Attack, and the rest). "
        "Dungeon Marks stay. The UI already lists every Drops of Interest "
        "row with its source. Do not write a ## Drops of Interest section.",
    ]
    tips = media.get("tips") or []
    if tips:
        lines.append(
            "The UI already shows this tip under the portal. Mention The Source "
            "in the castle / Nox route, but do not repeat this exact sentence:"
        )
        for tip in tips:
            lines.append(f"Tip: {tip}")
    notes = media.get("notes") or []
    if notes:
        lines.append(
            "HARDMODE SHATTERS CORRECTIONS. These override RealmEye if it "
            "conflicts. Structure the route around the three Hard Mode bosses "
            "only — Valen, then Nox, then King Azamoth and The Shattered Queen. "
            "Do not write separate sections for The Bridge Sentinel, Twilight "
            "Archmage, or The Forgotten King as if they are still the bosses."
        )
        for note in notes:
            lines.append(f"- {note}")
        lines.append(
            f"When covering Act I / before Valen, include this exact sentence: "
            f"{_HM_IDOL_NOTE}"
        )
        lines.append(
            f"When covering the third / final boss, include this exact sentence: "
            f"{_HM_AZAMOTH_NOTE}"
        )
    if media.get("difficulty") is not None:
        lines.append(f"Difficulty: {media['difficulty']}/10")
    layouts = media.get("layouts") or []
    if layouts:
        lines.append("## Example Layout")
        for layout in layouts:
            caption = layout.get("caption") or "Example Layout"
            lines.append(f"![{caption}]({layout['url']})")
    return "\n".join(lines)


async def load_dungeon_guide(
    redis: aioredis.Redis,
    dungeon_name: str,
    *,
    ttl_seconds: int,
    cache_only: bool = True,
) -> Optional[dict]:
    """Structured portal/graves/layouts/drops for the chat UI."""
    try:
        entries = await get_or_scrape_index(
            redis, ttl_seconds=ttl_seconds, cache_only=cache_only
        )
    except Exception:
        return None
    matches = match_index_pages(dungeon_name, entries)
    if not matches:
        return None
    pages: list[dict] = []
    for entry in matches:
        page = await get_or_scrape_wiki(
            redis,
            entry["slug"],
            ttl_seconds=ttl_seconds,
            cache_only=cache_only,
        )
        if page:
            pages.append(page)
    if not pages:
        return None
    return await _finalize_media(
        redis,
        dungeon_name,
        pages,
        matches,
        ttl_seconds=ttl_seconds,
        cache_only=cache_only,
    )
