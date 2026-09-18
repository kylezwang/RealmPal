"""RealmPal reply store: serve common answers without calling Claude.

Warming is the fact store (item profiles, hubs, dungeon pages). This is the
reply store. A drop question, a best-slot list, an early-game list, a minted
`{stat} {class}` brief, or a dungeon walkthrough should hit Redis. Claude
only when the ask is new or constrained ("no ST", "white bag only").
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from ..models.build import CLASS_ABILITY_HUB, CLASS_ALIASES, STAT_ALIASES
from .dungeon_guide import (
    _focus_text,
    _is_hardmode_shatters,
    cached_drops_from_source,
    extract_drop_source_query,
    extract_dungeon_query,
    get_or_scrape_index,
    get_or_scrape_wiki,
    match_index_pages,
)
from .biomes import compose_biome_brief, extract_biome_query
from .farm_guides import extract_farm_guide, farm_reply_text
from .enchanting import is_enchant_query
from .item_aliases import (
    community_canonical,
    extract_set_item_names,
    item_can_be_shiny,
    parse_rarity,
    prefer_original_name,
    resolve_item_query,
    resolve_item_query_with_trim,
)
from .player_lookup import (
    extract_player_ign,
    format_player_stored_reply,
    get_or_scrape_player,
)
from .community_knowledge import (
    SlotListSpec,
    names_mentioned_in_umi,
    rank_community_slot_names,
    spec_for_slot,
)
from .progression import compose_progression_brief, parse_progression_query
from .realmshark import parse_query, shark_name_counts
from .skin_visualizer import compose_skin_stored_reply, is_skin_visualize_query
from .wiki_scaling import HUB_PREFIX, UMI_BIS_PREFIX, cached_items_from_place, read_cached_item

BUILD_PREFIX = "wiki:build:v1"
ABILITY_PREFIX = "wiki:ability-brief:v1"
GUIDE_BRIEF_PREFIX = "wiki:guide-brief:v2"
BRIEF_INDEX_KEY = "wiki:brief-index"
MAX_BRIEF_CHARS = 8_000
GUIDE_MAX_CHARS = 16_000

_CONSTRAINT = re.compile(
    r"\b("
    r"no\s+st(?:s)?|without\s+st(?:s)?|no\s+soulbound|"
    r"white\s+bags?\s+only|whites?\s+only|"
    r"no\s+ut(?:s)?|without\s+ut(?:s)?|"
    r"with\s+my\s+mule|on\s+my\s+mule|"
    r"f2p\s+only|budget\s+only|no\s+st/?ut"
    r")\b",
    re.I,
)
_DROP = re.compile(
    r"(?:"
    r"where\s+(?:does|do)\s+(.+?)\s+drop|"
    r"where\s+(?:can|do)\s+i\s+(?:get|find|farm)\s+(.+?)|"
    r"how\s+(?:do\s+i|to)\s+(?:get|find|farm)\s+(.+?)|"
    r"what\s+drops\s+(.+?)|"
    r"(.+?)\s+drop\s+locations"
    r")\s*\??\s*$",
    re.I,
)
_SLOT = re.compile(
    r"\bbest\s+(bows?|longbows?|wands?|staves|staffs?|swords?|daggers?|"
    r"katanas?|lutes?|wakizashi|traps?|quivers?|tomes?|seals?|cloaks?|"
    r"helms?|shields?|rings?|orbs?|prisms?|scepters?|stars?|maces?|"
    r"sheaths?|sigils?|poisons?|skulls?|spells?|"
    r"armou?rs?|robes?|leathers?|"
    r"equipment|gear)\b",
    re.I,
)
_SHINY_DIVINE_ITEM = re.compile(
    r"(?:"
    r"(?:show|see|visualize)\s+(?:me\s+)?(?:a\s+)?"
    r")?"
    # shiny and divine are independent visual flags in-game (a single item
    # can be either, both, or neither) - matching either alone, not just the
    # combo, and stripping a trailing "look(s) like ...?" so "what does
    # shiny X look like" (found live Sep 14, no "divine") still extracts a
    # clean name instead of swallowing "look like?" into it or, before this
    # fix, not matching at all and falling through to a real Claude call
    # that has no way to actually render anything.
    r"(?:a\s+)?(?:shiny\s+(?:divine|legendary|rare|uncommon)"
    r"|(?:divine|legendary|rare|uncommon)\s+shiny"
    r"|shiny|divine|legendary|rare|uncommon)\s+"
    r"(.+?)"
    # Stop at the first sentence break (or " look(s) like", or end of
    # string) instead of the old bare `$` anchor, which forced the capture
    # to swallow everything up to the end of the message. Found live Sep 14:
    # "Shiny divine snake eye ring. Is it insane with the awakened
    # enchantment?" captured "snake eye ring. Is it insane with the awakened
    # enchantment" as the "item name" - a second sentence asking a real
    # follow-up question got glued onto the item, guaranteeing a bogus
    # lookup instead of a clean single-word match.
    #
    # A punctuation/"look(s) like" boundary isn't enough on its own though -
    # found live Sep 14 (again, same day, different phrasing): "Shiny divine
    # snake eye ring is the awakened enchantment good?" has no sentence break
    # at all before the trailing "?", the item name and the question run on
    # as one grammatical sentence ("... ring IS ... good?"). No real item
    # name contains a bare auxiliary/modal verb as a whole word, so treat
    # one as an equally valid stop point.
    r"(?=[.!?]|\s+looks?\s+like\b|\s+(?:is|does|has|can|will|should|would)\b|$)",
    re.I,
)
_SHINY_WORD = re.compile(r"\bshiny\b", re.I)
_MAKE_IT_VISUAL = re.compile(
    r"\b(?:make\s+(?:it|them|this|that)|show\s+(?:it|them)(?:\s+as)?)\b",
    re.I,
)
_ITEM_TOKEN = re.compile(r"\[item:([^\]]+)\]")
_FILLER_ITEM = frozenset(
    {
        "please",
        "pls",
        "thanks",
        "it",
        "this",
        "that",
        "them",
        "now",
        "too",
        "again",
        "also",
    }
)


def _visual_flags(message: str) -> tuple[bool, Optional[str]]:
    """Shiny plus the highest named slot rarity (Uncommon/Rare/Legendary/Divine)."""
    return bool(_SHINY_WORD.search(message or "")), parse_rarity(message)


def _shiny_divine_flags(message: str) -> tuple[bool, bool]:
    """Which of the two independent visual flags this message names."""
    shiny, rarity = _visual_flags(message)
    return shiny, rarity == "divine"

_EARLY = re.compile(
    r"\b(early[\s-]?game|beginner|new\s+player|starter)\b.+\b(items?|gear|loadout|equips?)\b"
    r"|\bbest\s+(early[\s-]?game|beginner|starter)\b",
    re.I,
)
_SLOT_SLUG = {
    "bow": "bows",
    "bows": "bows",
    "longbow": "longbows",
    "longbows": "longbows",
    "wand": "wands",
    "wands": "wands",
    "staff": "staves",
    "staffs": "staves",
    "staves": "staves",
    "sword": "swords",
    "swords": "swords",
    "dagger": "daggers",
    "daggers": "daggers",
    "katana": "katanas",
    "katanas": "katanas",
    "lute": "lutes",
    "lutes": "lutes",
    "wakizashi": "wakizashi",
    "trap": "traps",
    "traps": "traps",
    "quiver": "quivers",
    "quivers": "quivers",
    "tome": "tomes",
    "tomes": "tomes",
    "seal": "seals",
    "seals": "seals",
    "cloak": "cloaks",
    "cloaks": "cloaks",
    "helm": "helms",
    "helms": "helms",
    "shield": "shields",
    "shields": "shields",
    "ring": "rings",
    "rings": "rings",
    "orb": "orbs",
    "orbs": "orbs",
    "prism": "prisms",
    "prisms": "prisms",
    "scepter": "scepters",
    "scepters": "scepters",
    "star": "stars",
    "stars": "stars",
    "mace": "maces",
    "maces": "maces",
    "sheath": "sheaths",
    "sheaths": "sheaths",
    "sigil": "sigils",
    "sigils": "sigils",
    "poison": "poisons",
    "poisons": "poisons",
    "skull": "skulls",
    "skulls": "skulls",
    "spell": "spells",
    "spells": "spells",
    "armor": "armors",
    "armors": "armors",
    "armour": "armors",
    "armours": "armors",
    "robe": "robes",
    "robes": "robes",
    "leather": "leather-armors",
    "leathers": "leather-armors",
    "equipment": "equipment",
    "gear": "equipment",
}

_EARLY_TEXT = (
    "Early-game gear is T0–T6 from the Nexus priest and the first dungeons "
    "(Snake Pit, Sprite World, Undead Lair). Buy the T6 weapon, ability, and "
    "armor for your class; swap the ring once you have something with a real "
    "stat (Sprite Wand / Snake Eye Ring are common first finds).\n\n"
    "Skip UT hunting until those T6s are on. Come back when you want a "
    "stat-specific endgame brief.\n\n"
    "[item:Sprite Wand] [item:Snake Eye Ring]"
)

_SKIN_TEXT = (
    "Composited from RealmEye sprites — class skin plus clothing and accessory "
    "dyes. That render is code, not a model guess. Ask if you want a different "
    "cloth or dye combo."
)


async def _skin_reply(
    redis: aioredis.Redis,
    message: str,
    *,
    history: Optional[list[str]] = None,
    ttl_seconds: int,
) -> Optional[StoredReply]:
    if not is_skin_visualize_query(message, history=history):
        return None
    text = await compose_skin_stored_reply(
        redis, message, ttl_seconds=ttl_seconds, history=history
    )
    return StoredReply(text=text, kind="skin")


@dataclass(frozen=True)
class StoredReply:
    text: str
    kind: str
    key: str = ""


def is_constrained(message: str) -> bool:
    return bool(_CONSTRAINT.search(message or ""))


_ABILITY_ASK = re.compile(
    r"\b(?:best|top)\s+(?:\w+\s+)*abilit(?:y|ies)\b"
    r"|\babilit(?:y|ies)\b.+\b(?:best|top)\b",
    re.I,
)


def is_ability_ask(message: str) -> bool:
    """True for 'best druid abilities', not 'best items for a dex huntress'."""
    return bool(_ABILITY_ASK.search(message or ""))


def build_brief_key(class_name: str, stat: str) -> str:
    return f"{BUILD_PREFIX}:{class_name.lower()}:{stat.lower()}"


def ability_brief_key(class_name: str, stat: Optional[str] = None) -> str:
    slug = (class_name or "").strip().lower()
    if stat:
        return f"{ABILITY_PREFIX}:{slug}:{stat.lower()}"
    return f"{ABILITY_PREFIX}:{slug}"


def guide_brief_key(dungeon_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (dungeon_name or "").lower()).strip("-")
    return f"{GUIDE_BRIEF_PREFIX}:{slug}"


def _item_tags(names: list[str]) -> str:
    tags = [f"[item:{name}]" for name in names if name]
    return ("\n\n" + " ".join(tags)) if tags else ""


_ITEM_TAG = re.compile(r"\[(?:item|sprite):[^\]]+\]", re.I)
_WIKI_LINK = re.compile(
    r"\[([^\]]+)\]\((?:https?://(?:www\.)?realmeye\.com)?/wiki/[^)]+\)",
    re.I,
)


def _strip_item_card_hooks(text: str) -> str:
    """Keep readable names; drop hooks that fan out dozens of item-card fetches."""
    cleaned = _ITEM_TAG.sub("", text or "")
    cleaned = _WIKI_LINK.sub(r"\1", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


_WIKI_CHROME = re.compile(
    r"(?im)^(?:This page is currently a work in progress\.?|"
    r"The .+? Guide is currently a work in progress\.?|"
    r"Last updated:.*|"
    r"Contents|"
    r"Back to top|"
    r"For details pertaining to the version.+|"
    r"WIP)\s*$"
)
_WIKI_TITLE_TAIL = re.compile(r"\s*[-–—]\s*the RotMG Wiki.*$", re.I | re.M)
_INSTRUCTION_VOICE = re.compile(
    r"(?im)^.*("
    r"do not mention wings|"
    r"do not list (?:the )?bridge sentinel|"
    r"do not tell players|"
    r"never call it|"
    r"never emit|"
    r"these override realmeye|"
    r"do not write separate sections|"
    r"that mechanic is regular"
    r").*$"
)


def _strip_wiki_chrome(text: str) -> str:
    """Keep RealmEye prose. Drop navigation, WIP banners, and update stamps."""
    cleaned = _WIKI_TITLE_TAIL.sub("", text or "")
    cleaned = "\n".join(
        line
        for line in cleaned.splitlines()
        if not _WIKI_CHROME.match(line.strip())
        and not _INSTRUCTION_VOICE.match(line.strip())
    )
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


_HM_PLAYER_NOTES = (
    "To keep hardmode, kill the Source (the purple dome) on the way to "
    "Nox the Wild Shadow. After the dome, drag all 4 branches to the center.",
    "Hard Mode bosses are Valen the Unbreakable, then Nox the Wild Shadow, "
    "then King Azamoth and The Shattered Queen.",
    "Before Valen, kill the Stone Idol by finding the Void Phantasm. "
    "Do not break all 8 monuments until the Idol is dead.",
    "The Azamoth fight takes almost twice as long as regular Shatters and "
    "needs heavy damage for The Shattered Queen.",
    "Chrysalis of Eternity is a very low chance from King Azamoth.",
)


def _clean_drop_name(raw: str) -> str:
    name = re.sub(r"\b(drop|drops|from|locations?)\b", "", raw or "", flags=re.I)
    return re.sub(r"[?.!]+$", "", name).strip(" \t-")


# Every word that names a stat or a class (plus their nicknames -
# STAT_ALIASES/CLASS_ALIASES already cover "dex"/"atk"/"myst"/"war"/etc). A
# real item name is never composed *entirely* of these - used below to
# reject "attack huntress" / "dex huntress" as an item name the same way
# the "for X" guard above rejects "for full dexterity huntress": both are
# build references, not a name RealmEye could ever have a wiki page for.
_BUILD_VOCAB_WORDS: frozenset[str] = frozenset(
    word.lower()
    for word in (
        *STAT_ALIASES.keys(),
        *CLASS_ALIASES.keys(),
        *(alias for aliases in CLASS_ALIASES.values() for alias in aliases),
    )
)


def _shiny_divine_item_name(message: str) -> Optional[str]:
    """Single item from 'show me a shiny divine Crown'. Not a four-slot set."""
    if extract_set_item_names(message or ""):
        return None
    match = _SHINY_DIVINE_ITEM.search((message or "").strip())
    if not match:
        return None
    name = re.sub(r"\b(item|sprite|set|loadout|build|gear)\b", "", match.group(1), flags=re.I)
    name = re.sub(r"[?.!]+$", "", name).strip(" \t-")
    name = re.sub(r"\s+", " ", name)
    if not name or len(name) > 80:
        return None
    # Regression, found live Sep 14 (in-game playtest): "best shiny divine
    # set for full dexterity huntress" strips "set" above and leaves "for
    # full dexterity huntress" - no item was ever named, this is a build
    # request ("a set FOR this class/stat"), not "an item literally named
    # X". No real item name starts with a bare preposition/relative word,
    # so treat one as a sign the real noun got consumed by the "set"/"item"
    # strip and bail out here, letting this fall through to the general
    # build-brief flow (realmshark.parse_query) that already understands
    # "best build for a dex huntress" - instead of sending "for full
    # dexterity huntress" to a doomed wiki scrape.
    if re.match(r"^(?:for|on|to|that|which|who)\b", name, re.I):
        return None
    # Regression, found live Sep 14 (in-game playtest, right after the "for
    # X" fix above): "shiny divine attack huntress" has no "for"/"set" to
    # strip or catch - it's a bare stat+class pair with no item named at
    # all, but nothing above rejects it, so it went to a doomed wiki scrape
    # of "/wiki/attack-huntress" (404 after a ~30s timeout). If every
    # remaining word is stat/class vocabulary, this is a build reference,
    # not an item.
    words = [w.lower() for w in name.split()]
    if words and all(w in _BUILD_VOCAB_WORDS for w in words):
        return None
    if name.lower() in _FILLER_ITEM:
        return None
    return name


def _last_visualized_item(
    history: Optional[list[str]],
) -> tuple[Optional[str], bool, Optional[str]]:
    """Last named item plus the visual flags from that turn."""
    if not history:
        return None, False, None
    for prev in reversed(history):
        token = _ITEM_TOKEN.search(prev or "")
        if token:
            title = token.group(1).strip()
            if title:
                shiny, rarity = _visual_flags(prev)
                return title, shiny, rarity
        name = _shiny_divine_item_name(prev or "")
        if name:
            shiny, rarity = _visual_flags(prev)
            return name, shiny, rarity
    return None, False, None


async def _shiny_divine_reply(
    redis: aioredis.Redis,
    message: str,
    ttl: int,
    history: Optional[list[str]] = None,
) -> Optional[StoredReply]:
    shiny, rarity = _visual_flags(message)
    name = _shiny_divine_item_name(message)
    if not name and (shiny or rarity or _MAKE_IT_VISUAL.search(message or "")):
        name, prior_shiny, prior_rarity = _last_visualized_item(history)
        if not shiny:
            shiny = prior_shiny
        if not rarity:
            rarity = prior_rarity
    if not name or not (shiny or rarity):
        return None
    name = community_canonical(name) or name
    item = await read_cached_item(redis, name)
    if item is None:
        try:
            resolved = await resolve_item_query(
                redis,
                name,
                ttl_seconds=ttl,
                allow_scrape=False,
                prefer_shiny_ut=shiny,
            )
            if not resolved:
                resolved = await resolve_item_query_with_trim(
                    redis, name, ttl_seconds=ttl, prefer_shiny_ut=shiny
                )
        except Exception:
            resolved = None
        if resolved:
            item = await read_cached_item(redis, resolved)
            title = item.name if item else resolved
        else:
            return None
    else:
        title = item.name
    original = await prefer_original_name(redis, title, query=message)
    if not original:
        return None
    title = original
    item = await read_cached_item(redis, title) or item
    if shiny and item and not item_can_be_shiny(item):
        return None
    flags = " ".join(part for part in (("shiny" if shiny else None), rarity) if part)
    return StoredReply(
        text=f"[loadout {flags}]\n[item:{title}]",
        kind="shiny",
        key=f"item:profile:v3:{title.lower()}",
    )


async def _drop_reply(redis: aioredis.Redis, message: str, ttl: int) -> Optional[StoredReply]:
    match = _DROP.search((message or "").strip())
    if not match:
        return None
    raw = next((group for group in match.groups() if group), "")
    name = _clean_drop_name(raw)
    if not name or len(name) > 80:
        return None
    lookup = name
    try:
        resolved = await resolve_item_query(
            redis, name, ttl_seconds=ttl, allow_scrape=False
        )
        if resolved:
            lookup = resolved
    except Exception:
        lookup = name
    item = await read_cached_item(redis, lookup)
    if item is None:
        return None
    drops = [d for d in (item.drop_locations or []) if d]
    if not drops:
        body = (
            f"**{item.name}** is in the wiki store, but this profile has no "
            f"drop locations yet. Check {item.wiki_url or 'RealmEye'}."
        )
    else:
        lines = "\n".join(f"- {place}" for place in drops[:12])
        body = f"**{item.name}** drops from:\n{lines}"
    return StoredReply(
        text=body + _item_tags([item.name]),
        kind="drop",
        key=f"item:profile:v3:{item.name.lower()}",
    )


def _place_loot_reply(
    *,
    title: str,
    wiki_url: str,
    wiki_drops: list[str],
    cached_items: list,
    want_shiny: bool,
) -> StoredReply:
    by_name: dict[str, dict] = {}
    for name in wiki_drops:
        by_name.setdefault(name.lower(), {"name": name, "shiny": False})
    for cached in cached_items:
        row = by_name.setdefault(
            cached.name.lower(), {"name": cached.name, "shiny": False}
        )
        row["name"] = cached.name
        row["shiny"] = bool(cached.shiny_sprite_url)

    names = [row["name"] for row in by_name.values()]
    if not names:
        body = (
            f"The wiki store has no loot table for **{title}** yet. "
            "It will not invent item names."
        )
        if wiki_url:
            body += f" Check {wiki_url}."
        return StoredReply(
            text=body,
            kind="source-drop",
            key=f"wiki:source-drop:v1:{title.lower()}",
        )

    if want_shiny:
        shiny_names = [row["name"] for row in by_name.values() if row["shiny"]]
        if shiny_names:
            lines = "\n".join(f"- {name}" for name in shiny_names[:12])
            body = f"**{title}** drops with a stored shiny sprite:\n{lines}"
            return StoredReply(
                text=body + _item_tags(shiny_names[:8]),
                kind="source-drop",
                key=f"wiki:source-drop:v1:{title.lower()}",
            )
        listed = "\n".join(f"- {name}" for name in names[:12])
        body = (
            f"The wiki store has **{title}** loot, but no shiny sprite on "
            "those item pages yet. It will not guess which can be shiny.\n"
            f"{listed}"
        )
        return StoredReply(
            text=body + _item_tags(names[:8]),
            kind="source-drop",
            key=f"wiki:source-drop:v1:{title.lower()}",
        )

    lines = "\n".join(
        f"- {row['name']}"
        + (" (shiny sprite on RealmEye)" if row["shiny"] else "")
        for row in list(by_name.values())[:12]
    )
    body = f"**{title}** loot in the wiki store:\n{lines}"
    return StoredReply(
        text=body + _item_tags(names[:8]),
        kind="source-drop",
        key=f"wiki:source-drop:v1:{title.lower()}",
    )


async def _loot_for_source(
    redis: aioredis.Redis,
    source: str,
    ttl: int,
    want_shiny: bool,
) -> StoredReply:
    """Wiki loot for one dungeon, boss, or NPC. Never invent item names."""
    wiki_drops, wiki_url = await cached_drops_from_source(redis, source)
    title = source
    try:
        entries = await get_or_scrape_index(
            redis, ttl_seconds=ttl, cache_only=True
        )
    except Exception:
        entries = []
    matches = match_index_pages(source, entries) if entries else []
    if matches:
        title = matches[0].get("title") or title
        page = await get_or_scrape_wiki(
            redis,
            matches[0].get("slug") or "",
            ttl_seconds=ttl,
            cache_only=True,
        )
        if page:
            wiki_url = wiki_url or page.get("url") or ""
            for row in page.get("drops") or []:
                name = (row.get("name") or "").strip()
                if name:
                    wiki_drops.append(name)
    cached_items = await cached_items_from_place(redis, source)
    if title.lower() != source.lower():
        extra = await cached_items_from_place(redis, title)
        have = {item.name.lower() for item in cached_items}
        cached_items = cached_items + [
            item for item in extra if item.name.lower() not in have
        ]
    if wiki_drops or cached_items or matches:
        return _place_loot_reply(
            title=title,
            wiki_url=wiki_url,
            wiki_drops=wiki_drops,
            cached_items=cached_items,
            want_shiny=want_shiny,
        )

    resolved = None
    try:
        resolved = await resolve_item_query(
            redis, source, ttl_seconds=ttl, allow_scrape=False
        )
    except Exception:
        resolved = None
    item = await read_cached_item(redis, resolved or source)
    if item:
        if want_shiny:
            if item.shiny_sprite_url:
                body = (
                    f"**{item.name}** has a shiny sprite on its RealmEye wiki page."
                )
            else:
                body = (
                    f"**{item.name}** is in the wiki store with no shiny sprite "
                    "recorded. The store does not guess shiny drops."
                )
        else:
            places = [d for d in (item.drop_locations or []) if d]
            if places:
                lines = "\n".join(f"- {place}" for place in places[:12])
                body = f"**{item.name}** drops from:\n{lines}"
            else:
                body = (
                    f"**{item.name}** is in the wiki store, but this profile "
                    "has no drop locations yet."
                )
        return StoredReply(
            text=body + _item_tags([item.name]),
            kind="source-drop",
            key=f"item:profile:v3:{item.name.lower()}",
        )

    body = (
        f"The wiki store has no loot table for **{source}** yet. "
        "It will not invent item names."
    )
    return StoredReply(
        text=body,
        kind="source-drop",
        key=f"wiki:source-drop:v1:{source.lower()}",
    )


async def _source_drop_reply(
    redis: aioredis.Redis, message: str, ttl: int
) -> Optional[StoredReply]:
    """Loot for a dungeon/boss/NPC from wiki tables only. Never invent names.

    Live Sep 17: 'Can the Keyper drop shinies?' went to Claude, which made up
    Keyper's Trickery. The first pass only matched dungeon-index titles, so
    'what does Nox / Twilight Archmage drop' said the store was empty even
    when those bosses were on the Shatters loot table. This path lists names
    from drops_from rows and item drop_locations for every source in the ask.
    """
    parsed = extract_drop_source_query(message)
    if not parsed:
        return None
    names, want_shiny = parsed
    parts = [
        await _loot_for_source(redis, source, ttl, want_shiny) for source in names
    ]
    if len(parts) == 1:
        return parts[0]
    text = "\n\n".join(part.text for part in parts)
    key = "wiki:source-drop:v1:" + "|".join(name.lower() for name in names)
    return StoredReply(text=text, kind="source-drop", key=key)


async def _biome_reply(
    redis: aioredis.Redis, message: str, ttl: int
) -> Optional[StoredReply]:
    query = extract_biome_query(message)
    if not query:
        return None
    brief = await compose_biome_brief(
        redis, query, ttl_seconds=ttl, cache_only=True
    )
    if not brief:
        return None
    key = "wiki:biome:v1:veteran"
    if query.name and not query.survey:
        key = f"wiki:biome:v1:{(query.slug or query.name).lower()}"
    if query.potion:
        key = f"{key}:{query.potion.lower()}"
    return StoredReply(text=brief, kind="biome", key=key)


async def _farm_reply(message: str) -> Optional[StoredReply]:
    guide_id = extract_farm_guide(message)
    if not guide_id:
        return None
    text = farm_reply_text(guide_id)
    if not text:
        return None
    return StoredReply(text=text, kind="farm", key=f"wiki:farm:v1:{guide_id}")


async def _hub_catalog_names(
    redis: aioredis.Redis, hubs: tuple[str, ...]
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for slug in hubs:
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
            if name and key not in seen:
                seen.add(key)
                names.append(name)
    return names


async def _umi_slot_names(
    redis: aioredis.Redis,
    classes: tuple[str, ...],
    catalog: list[str],
    *,
    stat: Optional[str],
) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for class_name in classes:
        raw = await redis.get(f"{UMI_BIS_PREFIX}{class_name.lower()}")
        if not raw:
            continue
        try:
            payload = json.loads(raw)
            text = payload[0] if isinstance(payload, list) else str(payload)
        except (json.JSONDecodeError, TypeError, IndexError):
            continue
        for name in names_mentioned_in_umi(text, catalog, stat=stat):
            key = name.lower()
            if key not in seen:
                seen.add(key)
                found.append(name)
    return found


async def _best_slot_names(
    redis: aioredis.Redis,
    spec: SlotListSpec,
    *,
    stat: Optional[str],
    ttl_seconds: int,
) -> list[str]:
    catalog = list(spec.cores)
    catalog.extend(await _hub_catalog_names(redis, spec.hubs))
    shark = await shark_name_counts(
        redis,
        spec.classes,
        spec.shark_slot,
        stat=stat,
        ttl_seconds=ttl_seconds,
    )
    umi = await _umi_slot_names(redis, spec.classes, catalog, stat=stat)
    return rank_community_slot_names(
        cores=spec.cores, shark_counts=shark, umi_names=umi
    )


async def _slot_reply(
    redis: aioredis.Redis, message: str, *, ttl_seconds: int
) -> Optional[StoredReply]:
    class_name, stat, _buildish = parse_query(message)
    if class_name and stat:
        return None
    match = _SLOT.search(message or "")
    if match:
        slug = _SLOT_SLUG.get(match.group(1).lower())
    elif stat and re.search(
        r"\bbest\s+(?:items?|loadouts?|equips?)\b", message or "", re.I
    ):
        slug = "equipment"
    else:
        return None
    if not slug:
        return None
    spec = spec_for_slot(slug)
    if spec is None:
        return None
    if spec.slug == "equipment" and not stat:
        return None

    if spec.slug == "equipment":
        weapons: list[str] = []
        armors: list[str] = []
        rings: list[str] = []
        for part in ("bows", "swords", "armors", "rings"):
            piece = spec_for_slot(part)
            if piece is None:
                continue
            names = await _best_slot_names(
                redis, piece, stat=stat, ttl_seconds=ttl_seconds
            )
            if part == "rings":
                rings = names
            elif part == "armors":
                armors = names
            else:
                for name in names:
                    if name not in weapons:
                        weapons.append(name)
                weapons = weapons[:6]
        if not (weapons or armors or rings):
            return None
        heading = (
            f"**Best {stat} equipment** from UmiEnjoyers BIS and "
            f"RealmShark top 5s, aiming to maximize {stat}:"
        )
        chunks = [heading]
        if weapons:
            chunks.append(
                "Weapons:\n" + "\n".join(f"- {name}" for name in weapons)
            )
        if armors:
            chunks.append(
                "Armor:\n" + "\n".join(f"- {name}" for name in armors)
            )
        if rings:
            chunks.append(
                "Rings:\n" + "\n".join(f"- {name}" for name in rings)
            )
        shown = weapons + armors + rings
        return StoredReply(
            text="\n\n".join(chunks) + _item_tags(shown),
            kind="slot",
            key=f"slot:best:equipment:{stat.lower()}",
        )

    names = await _best_slot_names(
        redis, spec, stat=stat, ttl_seconds=ttl_seconds
    )
    if not names:
        return None
    if stat:
        heading = (
            f"**Best {stat} {spec.label}** from UmiEnjoyers BIS and "
            f"RealmShark top 5s, aiming to maximize {stat}:"
        )
        key = f"slot:best:{spec.slug}:{stat.lower()}"
    else:
        heading = (
            f"**Best {spec.label}** from UmiEnjoyers BIS and "
            "RealmShark top 5s:"
        )
        key = f"slot:best:{spec.slug}"
    lines = "\n".join(f"- {name}" for name in names)
    return StoredReply(
        text=f"{heading}\n{lines}" + _item_tags(names),
        kind="slot",
        key=key,
    )


async def _build_reply(
    redis: aioredis.Redis, message: str
) -> Optional[StoredReply]:
    if is_enchant_query(message):
        # An enchant question (e.g. "...insane with the awakened
        # enchantment?") almost always names a slot noun (ring/armor/weapon/
        # ability), which alone flips parse_query's weak `buildish` regex to
        # True even with no class or stat in *this* message. Enchant
        # questions have their own specialist (is_enchant_query is the same
        # gate api/routers/chat.py uses to route to it) - never let the
        # generic class+stat build cache intercept them first.
        return None
    # Stored briefs are "ask this again" hits, not conversation memory.
    # parse_query's history inheritance is for Claude follow-ups
    # ("what other rings"). Found live Sep 16: after a Dexterity Huntress
    # brief, a later LLM-bound test prompt inherited Huntress/Dexterity
    # and slipped the same cached loadout out instead of 402ing the
    # in-depth paywall. Only this turn's own class+stat may match a brief.
    class_name, stat, buildish = parse_query(message)
    if not (buildish and class_name and stat):
        return None
    if class_name not in CLASS_ABILITY_HUB:
        return None
    key = build_brief_key(class_name, stat)
    raw = await redis.get(key)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        text = (payload.get("text") or "").strip()
    except json.JSONDecodeError:
        text = raw.decode() if isinstance(raw, bytes) else str(raw)
    if not text:
        return None
    return StoredReply(text=text, kind="build", key=key)


async def _read_brief(redis: aioredis.Redis, key: str) -> Optional[str]:
    raw = await redis.get(key)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        text = (payload.get("text") or "").strip()
    except json.JSONDecodeError:
        text = raw.decode() if isinstance(raw, bytes) else str(raw)
    return text or None


async def _ability_reply(
    redis: aioredis.Redis, message: str
) -> Optional[StoredReply]:
    """Replay a minted ability essay when this turn asks for it again.

    Found live Sep 16: 'Best druid abilities' used Claude twice. The mint
    path required a named stat (wiki:build:v1:{class}:{stat}) and skipped
    Haiku, so a class-only ability ask never landed in the store.
    """
    if not is_ability_ask(message) or is_enchant_query(message):
        return None
    class_name, stat, _buildish = parse_query(message)
    if not class_name or class_name not in CLASS_ABILITY_HUB:
        return None
    key = ability_brief_key(class_name, stat)
    text = await _read_brief(redis, key)
    if not text:
        return None
    return StoredReply(text=text, kind="ability", key=key)


async def _guide_reply(
    redis: aioredis.Redis, message: str, history: Optional[list[str]], ttl: int
) -> Optional[StoredReply]:
    dungeon = extract_dungeon_query(message, history=history)
    if not dungeon:
        return None
    key = guide_brief_key(dungeon)
    raw = await redis.get(key)
    if raw:
        try:
            payload = json.loads(raw)
            text = (payload.get("text") or "").strip()
        except json.JSONDecodeError:
            text = raw.decode() if isinstance(raw, bytes) else str(raw)
        if text:
            return StoredReply(text=_strip_item_card_hooks(text), kind="guide", key=key)
    composed = await _compose_guide_brief(redis, dungeon, ttl)
    if not composed:
        return None
    await _write_brief(redis, key, composed, ttl, kind="guide")
    return StoredReply(text=composed, kind="guide", key=key)


async def _compose_guide_brief(
    redis: aioredis.Redis, dungeon: str, ttl: int
) -> Optional[str]:
    try:
        entries = await get_or_scrape_index(
            redis, ttl_seconds=ttl, cache_only=True
        )
    except Exception:
        return None
    if not entries:
        return None
    matches = match_index_pages(dungeon, entries)
    pages: list[dict] = []
    for entry in matches:
        page = await get_or_scrape_wiki(
            redis,
            entry.get("slug") or "",
            ttl_seconds=ttl,
            cache_only=True,
        )
        if page:
            pages.append(page)
    if not pages:
        return None
    hm = _is_hardmode_shatters(dungeon)
    hm_pages = [
        p
        for p in pages
        if re.search(r"^Hard Mode\s*$", p.get("text") or "", re.I | re.M)
    ]
    guide_pages = [
        p
        for p in pages
        if (p.get("url") or "").rsplit("/", 1)[-1].endswith("-guide")
    ]
    # One RealmEye page, not a Claude essay. The wiki is the reply store.
    use_pages = (hm_pages[:1] if hm else None) or (guide_pages[:1] or pages[:1])
    chunks = [f"# {dungeon.strip().title()}"]
    from .biomes import biome_by_title

    keep_potions = bool(biome_by_title(dungeon))
    for page in use_pages:
        focused = _focus_text(
            page.get("text") or "",
            dungeon,
            include_lead=not hm,
            keep_potions=keep_potions,
        )
        title = _WIKI_TITLE_TAIL.sub("", page.get("title") or page.get("slug") or "Guide")
        body = _strip_wiki_chrome(focused)
        if body:
            chunks.append(f"## {title.strip()}\n{body}")
    if hm:
        chunks.append(
            "Hardmode notes:\n" + "\n".join(f"- {note}" for note in _HM_PLAYER_NOTES)
        )
    text = _strip_item_card_hooks("\n\n".join(chunks))
    return text[:GUIDE_MAX_CHARS] if text else None


async def _player_reply(
    redis: aioredis.Redis,
    message: str,
    *,
    history: Optional[list[str]] = None,
    ttl_seconds: int,
) -> Optional[StoredReply]:
    """Scrape/cache the RealmEye row. No Claude. Lookup after the in-depth
    cap still works because this never reaches `_enforce_quota`."""
    ign = extract_player_ign(message, history=history)
    if not ign:
        return None
    try:
        profile = await get_or_scrape_player(
            redis, ign, ttl_seconds=ttl_seconds
        )
    except Exception as e:
        logger.bind(username=ign, error=str(e)).warning(
            "Stored player lookup could not load a profile"
        )
        return None
    return StoredReply(
        text=format_player_stored_reply(profile),
        kind="player",
        key=f"player:profile:v3:{ign.lower()}",
    )


async def _progression_reply(
    redis: aioredis.Redis, message: str, *, ttl_seconds: int
) -> Optional[StoredReply]:
    parsed = parse_progression_query(message)
    if not parsed:
        return None
    class_name, band = parsed
    text = await compose_progression_brief(
        redis, class_name, band=band, ttl_seconds=ttl_seconds
    )
    key = f"wiki:progression:v1:{class_name.lower()}"
    if band:
        key = f"{key}:{band}"
    return StoredReply(text=text, kind="progression", key=key)


async def try_stored_reply(
    redis: aioredis.Redis,
    message: str,
    *,
    history: Optional[list[str]] = None,
    ttl_seconds: int,
    player_ttl_seconds: int = 120,
    has_attachment: bool = False,
) -> Optional[StoredReply]:
    """Return a ready reply, or None if this turn still needs Claude."""
    if has_attachment or not (message or "").strip():
        return None
    if is_constrained(message):
        return None
    player = await _player_reply(
        redis,
        message,
        history=history,
        ttl_seconds=player_ttl_seconds,
    )
    if player:
        return player
    skin = await _skin_reply(
        redis, message, history=history, ttl_seconds=ttl_seconds
    )
    if skin:
        return skin

    shiny = await _shiny_divine_reply(
        redis, message, ttl_seconds, history=history
    )
    if shiny:
        return shiny

    biome = await _biome_reply(redis, message, ttl_seconds)
    if biome:
        return biome
    farm = await _farm_reply(message)
    if farm:
        return farm
    drop = await _drop_reply(redis, message, ttl_seconds)
    if drop:
        return drop
    source_drop = await _source_drop_reply(redis, message, ttl_seconds)
    if source_drop:
        return source_drop
    guide = await _guide_reply(redis, message, history, ttl_seconds)
    if guide:
        return guide
    progression = await _progression_reply(
        redis, message, ttl_seconds=ttl_seconds
    )
    if progression:
        return progression
    if _EARLY.search(message or "") and not parse_query(message)[0]:
        return StoredReply(text=_EARLY_TEXT, kind="early")
    slot = await _slot_reply(redis, message, ttl_seconds=ttl_seconds)
    if slot:
        return slot
    ability = await _ability_reply(redis, message)
    if ability:
        return ability
    return await _build_reply(redis, message)


async def maybe_mint_brief(
    redis: aioredis.Redis,
    message: str,
    reply: str,
    *,
    history: Optional[list[str]] = None,
    ttl_seconds: int,
) -> Optional[str]:
    """Persist a solid Claude build reply for the next identical ask.

    Dungeon how-tos stay on the warmed RealmEye page. Do not mint a model
    rewrite over that source.
    """
    if is_constrained(message) or not (reply or "").strip():
        return None
    if extract_dungeon_query(message, history=history):
        return None
    if extract_biome_query(message):
        return None
    if extract_farm_guide(message):
        return None
    if parse_progression_query(message):
        return None
    if is_enchant_query(message):
        # Same reasoning as _build_reply: a slot noun (ring/armor/weapon/
        # ability) alone can flip buildish True. Enchant answers are never
        # a substitute for the general build brief.
        return None
    text = reply.strip()[:MAX_BRIEF_CHARS]
    class_name, stat, buildish = parse_query(message)
    if is_ability_ask(message) and class_name and class_name in CLASS_ABILITY_HUB:
        key = ability_brief_key(class_name, stat)
        if await redis.get(key):
            return None
        await _write_brief(redis, key, text, ttl_seconds, kind="ability")
        return key
    if not (buildish and class_name and stat):
        return None
    key = build_brief_key(class_name, stat)
    if await redis.get(key):
        return None
    await _write_brief(redis, key, text, ttl_seconds, kind="build")
    return key


async def _write_brief(
    redis: aioredis.Redis,
    key: str,
    text: str,
    ttl_seconds: int,
    *,
    kind: str,
) -> None:
    payload = json.dumps(
        {"text": text, "kind": kind, "minted_at": int(time.time())}
    )
    await redis.setex(key, ttl_seconds, payload)
    await redis.sadd(BRIEF_INDEX_KEY, key)
    logger.bind(key=key, kind=kind).info("Stored RealmPal brief")


async def invalidate_briefs(redis: aioredis.Redis) -> int:
    """Drop minted briefs so weekly wiki refresh cannot leave stale essays."""
    keys = list(await redis.smembers(BRIEF_INDEX_KEY) or [])
    removed = 0
    if keys:
        removed = await redis.delete(*keys)
    await redis.delete(BRIEF_INDEX_KEY)
    logger.bind(removed=removed).info("Invalidated stored briefs")
    return int(removed or 0)
