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

from .fuzzy_match import fuzzy_closed_vocab, fuzzy_word_match, levenshtein
from .scraper import (
    REALMEYE_BASE,
    ScraperError,
    scrape_dungeon_indexes,
    scrape_wiki_article,
)
from .wiki_scaling import read_cached_item

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
    "shaters": "shatters",
    "lh": "lost halls",
    "o3": "oryx sanctuary",
    "o2": "wine cellar",
    "udl": "undead lair",
    "mv": "moonlight village",
    "moonlite": "moonlight",
    "carniferous": "carboniferous",
    "carboniferus": "carboniferous",
    "keyper": "the keyper",
    "keypers": "the keyper",
}

# Always-on wiki pages for dungeons the daily quests and guide asks use.
# Hardmode Shatters is a section on The Shatters, not its own index row.
# If the scraped index is empty (API boot, TTL), cache-only chat used to
# match nothing and tell Claude the indexes have no page.
CORE_DUNGEON_PAGES = (
    {
        "title": "The Shatters",
        "slug": "the-shatters",
        "kind": "dungeon",
        "aliases": ("shatters", "shatts", "shaters"),
    },
    {
        "title": "Moonlight Village",
        "slug": "moonlight-village",
        "kind": "dungeon",
        "aliases": ("mv", "moonlite"),
    },
    {
        "title": "Oryx's Sanctuary",
        "slug": "oryxs-sanctuary",
        "kind": "dungeon",
        "aliases": ("o3", "oryx sanctuary"),
    },
    {
        "title": "The Nest",
        "slug": "the-nest",
        "kind": "dungeon",
        "aliases": ("nest",),
    },
    {
        "title": "Cultist Hideout",
        "slug": "cultist-hideout",
        "kind": "dungeon",
        "aliases": ("cultist",),
    },
)

# RealmEye event/NPC pages that are loot sources but often missing from
# /wiki/dungeons. Same merge pattern as veteran biomes.
EVENT_PAGES = (
    {
        "title": "The Keyper",
        "slug": "the-keyper",
        "kind": "dungeon",
        "aliases": ("keyper", "keypers"),
    },
)

_GUIDE_RE = re.compile(
    r"(?:"
    r"guide\s+to\s+complete|"
    r"guide\s+to\s+(?:beat|clear|finish|do|run|solo)|"
    # "do" must be included: "how to do moonlight village" is the single most
    # common phrasing for this and was previously falling through to generic
    # RAG (found live Sep 14 - see BACKLOG.md), since only
    # complete/beat/clear/finish were recognized as guide-request verbs.
    r"how\s+(?:do\s+i|to)\s+(?:complete|beat|clear|finish|do|run|solo)|"
    r"walkthrough\s+(?:for|of)|"
    r"(?:dungeon\s+)?guide\s+(?:for|to)"
    r")\s+(.+?)\s*$",
    re.IGNORECASE,
)
_MODE_PREFIX = re.compile(r"^(?:hard\s*mode|hardmode|hm|easy\s*mode|easy)\s+", re.I)
_HARD_MODE_RE = re.compile(r"hard\s*mode|hardmode|\bhm\b", re.I)
_PUNCT_TAIL = re.compile(r"[?.!]+$")
_WIKI_IMG = "https://www.realmeye.com/s/a/img/wiki/i/"
_SOURCE_SPRITE_FALLBACK = f"{_WIKI_IMG}bdfzUM2.png"
_SHATTERS_PORTAL_FALLBACK = f"{_WIKI_IMG}yA4tlry.png"
_ENEMY_PORTAL = re.compile(r"(?:ice|fire|stone)[-_\s]?portal", re.I)
_WIKI_TITLE_TAIL = re.compile(r"\s*[-–—]\s*the RotMG Wiki.*$", re.I)
# RealmEye dungeon-index sprites. Keep in sync with web/lib/quests.ts.
_KNOWN_PORTALS = (
    (re.compile(r"shatter", re.I), re.compile(r"hard\s*mode|hardmode", re.I), _SOURCE_SPRITE_FALLBACK),
    (re.compile(r"shatter", re.I), None, _SHATTERS_PORTAL_FALLBACK),
    (re.compile(r"moonlight|\bmv\b", re.I), None, f"{_WIKI_IMG}CHqjDCE.png"),
    (re.compile(r"sanctuary|\bo3\b", re.I), None, f"{_WIKI_IMG}JGnMCv2.png"),
    (re.compile(r"\bnest\b", re.I), None, f"{_WIKI_IMG}FgpEOel.png"),
    (re.compile(r"cultist", re.I), None, f"{_WIKI_IMG}on1ykYB.png"),
)
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


_SOURCE_DROP_RE = re.compile(
    r"^(?:can|does|do)\s+(?:the\s+)?(.+?)\s+drop(?:s)?(?:\s+"
    r"(?:shin(?:y|ies)|loot|items?|uts?|sts?|whites?))?\s*\??\s*$"
    r"|^(?:what|which)\s+(?:does|can|do)\s+(?:the\s+)?(.+?)\s+drop(?:s)?"
    r"(?:\s+(?:shin(?:y|ies)|loot|items?))?\s*\??\s*$"
    r"|^what\s+(?:the\s+)?(.+?)\s+drops?\b"
    r"|^(?:what|which)\s+(?:loot|drops|items)\s+(?:does|do|can)\s+(?:the\s+)?"
    r"(.+?)\s+(?:have|drop)"
    r"|^(.+?)\s+(?:loot\s+table|drops?\s+of\s+interest)\s*\??\s*$",
    re.I,
)
_SOURCE_SPLIT = re.compile(r"\s+(?:and|&)\s+|,\s+(?:and\s+)?", re.I)
_SKIP_DROP_SOURCE = frozenset(
    {"you", "i", "we", "it", "they", "he", "she", "this", "that"}
)
_SKIP_SOURCE_PREFIX = frozenset(
    {"what", "which", "where", "how", "who", "why", "best"}
)


def _clean_source_name(raw: str) -> str:
    name = re.sub(r"^(?:the\s+)", "", (raw or "").strip(), flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" ?.")
    return name


def _split_drop_sources(raw: str) -> list[str]:
    """'Nox the wild shadow and the twilight archmage' -> two sources."""
    chunks = _SOURCE_SPLIT.split(raw or "") or [raw]
    names: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        name = _clean_source_name(chunk)
        if not name or len(name) > 60:
            continue
        first = name.split()[0].lower()
        if name.lower() in _SKIP_DROP_SOURCE or first in _SKIP_SOURCE_PREFIX:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def extract_drop_source_query(message: str) -> Optional[tuple[list[str], bool]]:
    """Dungeon/boss/NPC loot ask: (['Keyper'], shiny) or None.

    Live Sep 17: 'Can the Keyper drop shinies?' invented Keyper's Trickery
    because this never matched a guide verb and Claude filled in an item.
    Same day: Nox / Twilight Archmage missed because only index titles
    (not drops_from bosses) were treated as sources.
    """
    text = (message or "").strip()
    match = _SOURCE_DROP_RE.search(text)
    if not match:
        return None
    raw = next((group for group in match.groups() if group), "")
    names = _split_drop_sources(raw)
    if not names:
        return None
    shiny = bool(re.search(r"\bshin(?:y|ies)\b", text, re.I))
    return names, shiny


def mentions_drop_source(haystack: str, source: str) -> bool:
    """True when a Drops from cell names this dungeon, boss, or NPC."""
    q = _core(source)
    h = _core(haystack)
    if not q or len(q) < 3 or not h:
        return False
    if q == h:
        return True
    if f" {q} " in f" {h} ":
        return True
    qtoks = _tokens(source)
    htoks = _tokens(haystack)
    return bool(qtoks) and qtoks <= htoks


async def cached_drops_from_source(
    redis: aioredis.Redis,
    source: str,
    *,
    limit: int = 24,
) -> tuple[list[str], str]:
    """Item names on cached dungeon pages whose drops_from mention source."""
    names: list[str] = []
    seen: set[str] = set()
    wiki_url = ""
    async for raw_key in redis.scan_iter(match=f"{PAGE_CACHE_PREFIX}*", count=100):
        raw = await redis.get(raw_key)
        if not raw:
            continue
        try:
            page = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(page, dict):
            continue
        for row in page.get("drops") or []:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            if not mentions_drop_source(row.get("drops_from") or "", source):
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(name)
            if not wiki_url:
                wiki_url = page.get("url") or ""
            if len(names) >= limit:
                return names, wiki_url
    return names, wiki_url


def event_index_entries() -> list[dict]:
    return [
        {
            "title": row["title"],
            "slug": row["slug"],
            "kind": row.get("kind") or "dungeon",
            "portal_url": None,
            "difficulty": None,
            "aliases": list(row.get("aliases") or ()),
        }
        for row in EVENT_PAGES
    ]


def merge_event_entries(entries: list[dict]) -> list[dict]:
    seen = {(row.get("slug") or "").lower() for row in entries}
    extra = [row for row in event_index_entries() if row["slug"] not in seen]
    return list(entries) + extra


def core_dungeon_index_entries() -> list[dict]:
    return [
        {
            "title": row["title"],
            "slug": row["slug"],
            "kind": row.get("kind") or "dungeon",
            "portal_url": None,
            "difficulty": None,
            "aliases": list(row.get("aliases") or ()),
        }
        for row in CORE_DUNGEON_PAGES
    ]


def merge_core_dungeon_entries(entries: list[dict]) -> list[dict]:
    seen = {(row.get("slug") or "").lower() for row in entries}
    extra = [
        row for row in core_dungeon_index_entries() if row["slug"] not in seen
    ]
    return list(entries) + extra


def _index_with_fallbacks(entries: list[dict]) -> list[dict]:
    from .biomes import merge_biome_entries

    return merge_core_dungeon_entries(
        merge_event_entries(merge_biome_entries(entries))
    )


def extract_dungeon_query(
    message: str,
    history: Optional[list[str]] = None,
) -> Optional[str]:
    """Pull the dungeon name from this turn, or from a prior guide follow-up."""
    direct = _name_from_guide_match(message)
    if direct:
        return direct
    from .biomes import named_biome

    biome = named_biome(message)
    if biome:
        return biome
    if history and _FOLLOWUP_RE.search(message or ""):
        for prev in reversed(history):
            found = _name_from_guide_match(prev)
            if found:
                return found
    return None


def _normalize(name: str) -> str:
    cleaned = re.sub(r"['’]", "", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    nick_pairs = list(_NICKNAMES.items()) + [(value, value) for value in _NICKNAMES.values()]
    parts = []
    for part in cleaned.split():
        mapped = _NICKNAMES.get(part)
        if mapped:
            parts.append(mapped)
            continue
        fuzzy = fuzzy_closed_vocab(part, nick_pairs)
        parts.append(fuzzy or part)
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


def portal_for_dungeon(name: str, fallback: str | None = None) -> str | None:
    """Index sprite for a known dungeon. Ice/Fire/Stone portals never win."""
    text = _WIKI_TITLE_TAIL.sub("", name or "").lower()
    for match, extra, url in _KNOWN_PORTALS:
        if not match.search(text):
            continue
        if extra and not extra.search(text):
            continue
        return url
    return fallback or None


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
    for alias in entry.get("aliases") or []:
        a = _core(str(alias))
        if a and q == a:
            return 95
    if t.startswith(q) or q.startswith(t):
        return 80 + min(len(t), 15)
    if q in t or t in q:
        return 70 + min(len(t), 15)
    for alias in entry.get("aliases") or []:
        a = _core(str(alias))
        if a and (a in q or q in a):
            return 75
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
    fuzzy_hits = 0
    for qt in qtoks:
        if any(
            fuzzy_word_match(qt, tt)
            or (
                len(qt) >= 3
                and len(tt) >= 3
                and abs(len(qt) - len(tt)) <= 1
                and levenshtein(qt, tt) <= 1
            )
            for tt in ttoks
        ):
            fuzzy_hits += 1
    if qtoks and fuzzy_hits == len(qtoks):
        return 55
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


def _hard_mode_section(body: str) -> Optional[str]:
    """The last 'Hard Mode' heading is the real section. An earlier hit is the TOC."""
    matches = list(re.finditer(r"^Hard Mode\s*$", body or "", re.I | re.M))
    if not matches:
        return None
    start = matches[-1].start()
    return (body or "")[start : start + 8000]


def _focus_text(
    text: str, query: str, *, include_lead: bool = True, keep_potions: bool = False
) -> str:
    """Keep Hard Mode plus shrine/Umi/layout/drops even when trimming."""
    body = text or ""
    parts: list[str] = []
    section: Optional[str] = None
    if _wants_hard_mode(query):
        section = _hard_mode_section(body)
        if section:
            if include_lead:
                parts.append(body[:1800])
            parts.append(section)
    if not parts:
        parts.append(body[:MAX_PAGE_CHARS])
    # Stored HM replies stay on the Hard Mode writeup. Do not pull the
    # contents-list "Drops of Interest" hit from the regular dungeon page.
    search_in = section if (section and not include_lead) else body
    for match in _PRIORITY_SECTION.finditer(search_in):
        chunk = match.group(1).strip()
        if chunk and chunk not in "\n".join(parts):
            parts.append(chunk)
    focused = "\n\n".join(parts) if keep_potions else _strip_potion_drop_lines(
        "\n\n".join(parts)
    )
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
            return _index_with_fallbacks(json.loads(cached))
        if cache_only:
            return _index_with_fallbacks([])
    entries = await scrape_dungeon_indexes()
    await redis.setex(INDEX_CACHE_KEY, ttl_seconds, json.dumps(entries))
    return _index_with_fallbacks(entries)


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
        slug = entry.get("slug") or ""
        page = await get_or_scrape_wiki(
            redis,
            slug,
            ttl_seconds=ttl_seconds,
            cache_only=cache_only,
        )
        if not page and cache_only and slug:
            page = await get_or_scrape_wiki(
                redis, slug, ttl_seconds=ttl_seconds, cache_only=False
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
    from .biomes import biome_by_title, is_biome_slug

    keep_potions = bool(biome_by_title(dungeon_name)) or any(
        is_biome_slug(entry.get("slug") or "") for entry in matches
    )
    for page in pages:
        focused = _focus_text(
            page.get("text") or "", dungeon_name, keep_potions=keep_potions
        )
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
        page_portal = page.get("portal_url")
        if page_portal and not _ENEMY_PORTAL.search(page_portal) and (
            not portal or not slug.endswith("-guide")
        ):
            portal = page_portal
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
    index_difficulty = None
    index_portal = None
    for entry in matches:
        if entry.get("difficulty") is not None and index_difficulty is None:
            index_difficulty = entry.get("difficulty")
        if not title:
            title = entry.get("title") or title
        candidate = entry.get("portal_url")
        if candidate and not _ENEMY_PORTAL.search(candidate) and not index_portal:
            index_portal = candidate
    if index_portal:
        portal = index_portal
    if index_difficulty is not None:
        difficulty = index_difficulty
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


async def _hydrate_drop_sprites(
    redis: aioredis.Redis, drops: list[dict]
) -> list[dict]:
    hydrated: list[dict] = []
    for drop in drops:
        row = dict(drop)
        if not row.get("sprite_url") and row.get("name"):
            item = await read_cached_item(redis, row["name"])
            if item and item.sprite_url:
                row["sprite_url"] = item.sprite_url
        hydrated.append(row)
    return hydrated


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
    forced = portal_for_dungeon(query) or portal_for_dungeon(media.get("title") or "")
    if forced:
        media["portal_url"] = forced
    elif _ENEMY_PORTAL.search(media.get("portal_url") or ""):
        media["portal_url"] = None
    media["drops"] = await _hydrate_drop_sprites(redis, media.get("drops") or [])
    if not _is_hardmode_shatters(query):
        return media
    media["portal_url"] = _SOURCE_SPRITE_FALLBACK
    media["tips"] = [
        "To keep hardmode, kill the Source (the purple dome) on the way to "
        "Nox the Wild Shadow. After the dome, drag all 4 branches to the center."
    ]
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
        "DUNGEON MEDIA from RealmEye. The UI already shows the portal sprite, "
        "grave rating, Example Layout maps, and the full Drops of Interest "
        "list from the wiki table. Do not repeat those in prose or markdown. "
        "If a Shrine / Village Girl Umi quiz is in the chunk, add "
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
        lines.append(f"Difficulty: {media['difficulty']}/10 (shown as graves in the UI)")
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
