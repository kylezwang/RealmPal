"""Veteran realm biomes: potion farms and wiki drop lists.

Daily quests already rotate Carboniferous. Chat used to treat biome names as
unknown and strip potions from dungeon drop lists, so "what veteran biomes
drop what potions" fell through to generic weapon/ability RAG.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis

STAT_POTIONS = (
    ("life", "Life"),
    ("mana", "Mana"),
    ("attack", "Attack"),
    ("defense", "Defense"),
    ("speed", "Speed"),
    ("dexterity", "Dexterity"),
    ("vitality", "Vitality"),
    ("wisdom", "Wisdom"),
)
STAT_LABELS = {key: label for key, label in STAT_POTIONS}
POTION_ORDER = [label for _key, label in STAT_POTIONS]

# RealmEye /wiki/{slug} pages. Veteran biomes are the ones daily quests and
# potion-farm questions actually name.
BIOMES = (
    {
        "title": "Floral Escape",
        "slug": "floral-escape",
        "tier": "veteran",
        "aliases": (),
    },
    {
        "title": "Carboniferous",
        "slug": "carboniferous",
        "tier": "veteran",
        "aliases": ("carniferous", "carboniferus"),
    },
    {
        "title": "Sanguine Forest",
        "slug": "sanguine-forest",
        "tier": "veteran",
        "aliases": (),
    },
    {
        "title": "Runic Tundra",
        "slug": "runic-tundra",
        "tier": "veteran",
        "aliases": (),
    },
    {
        "title": "Deep Sea Abyss",
        "slug": "deep-sea-abyss",
        "tier": "veteran",
        "aliases": ("deep sea abyss",),
    },
)

SURVEY_NAME = "veteran biomes"
_WIKI_TITLE_TAIL = re.compile(r"\s*[-–—]\s*the RotMG Wiki.*$", re.I)
_BIOME_SURVEY = re.compile(
    r"\b(?:veteran\s+)?biomes?\b|\brealm biomes?\b",
    re.I,
)
_POTION_WORD = re.compile(r"\bpotions?\b|\bpots?\b", re.I)
_DROP_WORD = re.compile(r"\bdrop(?:s|ped)?\b|\bfarm\b|\bget\b|\bfind\b", re.I)
_POTION_STAT = re.compile(
    r"(?:potion of |greater )?(life|mana|attack|defense|speed|dexterity|"
    r"vitality|wisdom|att|def|spd|dex|vit|wis)\s*(?:pots?|potions?)?",
    re.I,
)
_STAT_SHORT = {
    "att": "attack",
    "def": "defense",
    "spd": "speed",
    "dex": "dexterity",
    "vit": "vitality",
    "wis": "wisdom",
}


@dataclass(frozen=True)
class BiomeQuery:
    """Named biome, or a veteran-biome survey, optionally filtered by potion."""

    name: Optional[str] = None
    slug: Optional[str] = None
    potion: Optional[str] = None
    survey: bool = False


def biome_index_entries() -> list[dict]:
    return [
        {
            "title": row["title"],
            "slug": row["slug"],
            "kind": "biome",
            "tier": row["tier"],
            "portal_url": None,
            "difficulty": None,
        }
        for row in BIOMES
    ]


def merge_biome_entries(entries: list[dict]) -> list[dict]:
    seen = {(row.get("slug") or "").lower() for row in entries}
    extra = [row for row in biome_index_entries() if row["slug"] not in seen]
    return list(entries) + extra


def is_biome_slug(slug: str) -> bool:
    key = (slug or "").strip().lower()
    return any(row["slug"] == key for row in BIOMES)


def _norm(text: str) -> str:
    cleaned = _WIKI_TITLE_TAIL.sub("", text or "")
    cleaned = re.sub(r"['’]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def _alias_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for row in BIOMES:
        title = row["title"]
        pairs.append((_norm(title), title))
        for alias in row.get("aliases") or ():
            pairs.append((_norm(alias), title))
    return pairs


def biome_by_title(name: str) -> Optional[dict]:
    key = _norm(name)
    if not key:
        return None
    for row in BIOMES:
        if _norm(row["title"]) == key or key == row["slug"]:
            return row
        if any(_norm(alias) == key for alias in row.get("aliases") or ()):
            return row
    return None


def named_biome(message: str) -> Optional[str]:
    """Return the wiki title when this turn names a known biome."""
    text = _norm(message)
    if not text:
        return None
    hits: list[tuple[int, str]] = []
    for alias, title in _alias_pairs():
        if len(alias) < 4:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", text):
            hits.append((len(alias), title))
    if not hits:
        return None
    hits.sort(reverse=True)
    return hits[0][1]


def _potion_label(raw: str) -> Optional[str]:
    key = _STAT_SHORT.get((raw or "").strip().lower(), (raw or "").strip().lower())
    return STAT_LABELS.get(key)


def asked_potion(message: str) -> Optional[str]:
    if not _POTION_WORD.search(message or ""):
        return None
    match = _POTION_STAT.search(message or "")
    if not match:
        return None
    return _potion_label(match.group(1))


def extract_biome_query(message: str) -> Optional[BiomeQuery]:
    """Biome / veteran-potion questions, including daily-quest biome names."""
    text = (message or "").strip()
    if not text:
        return None
    name = named_biome(text)
    potion = asked_potion(text)
    if name:
        row = biome_by_title(name)
        return BiomeQuery(
            name=name,
            slug=(row or {}).get("slug"),
            potion=potion,
            survey=False,
        )
    surveyish = bool(_BIOME_SURVEY.search(text)) and (
        bool(_POTION_WORD.search(text)) or bool(_DROP_WORD.search(text))
    )
    farm_potion = bool(potion) and bool(_DROP_WORD.search(text))
    if surveyish or farm_potion:
        return BiomeQuery(name=SURVEY_NAME, potion=potion, survey=True)
    return None


def potions_from_text(text: str) -> list[str]:
    """Stat potions named in wiki lead sentences about drops."""
    body = _WIKI_TITLE_TAIL.sub("", text or "")
    chunks: list[str] = []
    for sent in re.split(r"(?<=[.!?])\s+", body[:2500]):
        if re.search(r"potion", sent, re.I):
            chunks.append(sent)
    blob = " ".join(chunks) if chunks else body[:900]
    found: list[str] = []
    seen: set[str] = set()
    for key, label in STAT_POTIONS:
        if re.search(rf"\b{key}\b", blob, re.I) and label not in seen:
            seen.add(label)
            found.append(label)
    return found


def _notable_drops(page: dict) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for drop in page.get("drops") or []:
        if isinstance(drop, dict):
            name = (drop.get("name") or "").strip()
        else:
            name = str(drop).strip()
        key = name.lower()
        if not name or key in seen:
            continue
        if re.search(r"\bpotion\b|^tier\s+\d+\s+", name, re.I):
            continue
        seen.add(key)
        names.append(name)
    lead = (page.get("text") or "")[:1200]
    ut = re.search(
        r"biome UT obtainable[^.]*?\bis\s+([^,.]+)",
        lead,
        re.I,
    )
    if ut:
        name = ut.group(1).strip()
        if name.lower() not in seen and not re.search(r"\bpotion\b", name, re.I):
            names.insert(0, name)
    return names[:12]


def _format_biome_block(row: dict, page: dict, *, potion: Optional[str] = None) -> str:
    title = _WIKI_TITLE_TAIL.sub("", page.get("title") or row["title"]).strip()
    pots = potions_from_text(page.get("text") or "")
    if potion and potion not in pots:
        return ""
    lines = [f"**{title}** (Veteran biome)"]
    if pots:
        lines.append("Potions: " + ", ".join(pots))
    notable = _notable_drops(page)
    if notable:
        lines.append("Also drops: " + ", ".join(notable))
    url = page.get("url") or f"https://www.realmeye.com/wiki/{row['slug']}"
    lines.append(f"Source: {url}")
    return "\n".join(lines)


async def _load_page(
    redis: aioredis.Redis,
    slug: str,
    *,
    ttl_seconds: int,
    cache_only: bool,
) -> Optional[dict]:
    from .dungeon_guide import get_or_scrape_wiki

    return await get_or_scrape_wiki(
        redis, slug, ttl_seconds=ttl_seconds, cache_only=cache_only
    )


async def compose_biome_brief(
    redis: aioredis.Redis,
    query: BiomeQuery,
    *,
    ttl_seconds: int,
    cache_only: bool = True,
) -> Optional[str]:
    rows = list(BIOMES)
    if query.name and not query.survey:
        row = biome_by_title(query.name)
        rows = [row] if row else []
    blocks: list[str] = []
    for row in rows:
        page = await _load_page(
            redis, row["slug"], ttl_seconds=ttl_seconds, cache_only=cache_only
        )
        if not page:
            continue
        block = _format_biome_block(row, page, potion=query.potion)
        if block:
            blocks.append(block)
    if not blocks:
        return None
    if query.survey or len(blocks) > 1:
        heading = "Veteran biome potion drops"
        if query.potion:
            heading = f"Veteran biomes that drop Potion of {query.potion}"
        return heading + "\n\n" + "\n\n".join(blocks)
    return blocks[0]


async def retrieve_biome_context(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int,
    cache_only: bool = False,
) -> str:
    query = extract_biome_query(message)
    if not query:
        return ""
    brief = await compose_biome_brief(
        redis, query, ttl_seconds=ttl_seconds, cache_only=cache_only
    )
    if not brief:
        return (
            "BIOME CONTEXT. RealmEye biome pages were not in the store. "
            "Say so rather than inventing potion drops."
        )
    return (
        "BIOME CONTEXT from RealmEye biome pages. Potions listed here are "
        "the farm for that biome. Do not say you lack biome potion data.\n\n"
        + brief
    )
