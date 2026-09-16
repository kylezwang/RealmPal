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
    extract_dungeon_query,
    get_or_scrape_index,
    get_or_scrape_wiki,
    match_index_pages,
)
from .enchanting import is_enchant_query
from .item_aliases import (
    MAX_PLAUSIBLE_ITEM_NAME_WORDS,
    extract_set_item_names,
    resolve_item_query,
    resolve_item_query_with_trim,
)
from .player_lookup import (
    extract_player_ign,
    format_player_stored_reply,
    get_or_scrape_player,
)
from .realmshark import parse_query
from .skin_visualizer import compose_skin_stored_reply, is_skin_visualize_query
from .wiki_scaling import HUB_PREFIX, read_cached_item

BUILD_PREFIX = "wiki:build:v1"
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
    r"sheaths?|sigils?|poisons?|skulls?|spells?)\b",
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
    r"(?:a\s+)?(?:shiny\s+divine|divine\s+shiny|shiny|divine)\s+"
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
_DIVINE_WORD = re.compile(r"\bdivine\b", re.I)


def _shiny_divine_flags(message: str) -> tuple[bool, bool]:
    """Which of the two independent visual flags this message names."""
    text = message or ""
    return bool(_SHINY_WORD.search(text)), bool(_DIVINE_WORD.search(text))

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


def build_brief_key(class_name: str, stat: str) -> str:
    return f"{BUILD_PREFIX}:{class_name.lower()}:{stat.lower()}"


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
    return name


async def _shiny_divine_reply(
    redis: aioredis.Redis, message: str, ttl: int
) -> Optional[StoredReply]:
    name = _shiny_divine_item_name(message)
    if not name:
        return None
    item = await read_cached_item(redis, name)
    if item is None:
        try:
            resolved = await resolve_item_query(
                redis, name, ttl_seconds=ttl, allow_scrape=False
            )
            if not resolved:
                # The durable fix (found live Sep 14, repeatedly): a regex
                # extraction only knows where an item name *starts*, not
                # reliably where a trailing question with no clear
                # punctuation boundary *ends* ("...ring is the awakened
                # enchantment good?"). Rather than keep guessing which
                # trailing words are junk one incident at a time, ask the
                # real item catalog whether any *prefix* of this text names
                # a real item - see resolve_item_query_with_trim's
                # docstring.
                resolved = await resolve_item_query_with_trim(
                    redis, name, ttl_seconds=ttl
                )
        except Exception:
            resolved = None
        if resolved:
            item = await read_cached_item(redis, resolved)
            title = item.name if item else resolved
        elif len(name.split()) <= MAX_PLAUSIBLE_ITEM_NAME_WORDS:
            # Short enough to plausibly be a real, just-not-yet-cataloged
            # item (e.g. brand new gear the hub pages haven't listed yet) -
            # let the router's own scrape-then-cache path have a shot at it.
            title = name
        else:
            # Too long to plausibly be a real item name and the catalog
            # (even with trimming) found nothing in it - this is extraction
            # garbage, not an item. Returning it here would hand the
            # frontend a doomed lookup guaranteed to 404 after a long
            # scrape timeout. Fall through to a different reply path
            # instead of pretending this was a real item request.
            return None
    else:
        title = item.name
    shiny, divine = _shiny_divine_flags(message)
    flags = " ".join(flag for flag, on in (("shiny", shiny), ("divine", divine)) if on)
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


async def _slot_reply(redis: aioredis.Redis, message: str) -> Optional[StoredReply]:
    match = _SLOT.search(message or "")
    if not match:
        return None
    class_name, stat, _buildish = parse_query(message)
    if class_name and stat:
        return None
    slug = _SLOT_SLUG.get(match.group(1).lower())
    if not slug:
        return None
    raw = await redis.get(f"{HUB_PREFIX}:{slug}")
    if not raw:
        return None
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return None
    names: list[str] = []
    for row in rows:
        name = (row.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
        if len(names) >= 6:
            break
    if not names:
        return None
    label = slug.replace("-", " ")
    lines = "\n".join(f"- {name}" for name in names)
    return StoredReply(
        text=f"Top **{label}** from the warmed RealmEye hub:\n{lines}"
        + _item_tags(names),
        kind="slot",
        key=f"{HUB_PREFIX}:{slug}",
    )


async def _build_reply(
    redis: aioredis.Redis, message: str, history: Optional[list[str]]
) -> Optional[StoredReply]:
    if is_enchant_query(message):
        # An enchant question (e.g. "...insane with the awakened
        # enchantment?") almost always names a slot noun (ring/armor/weapon/
        # ability), which alone flips parse_query's weak `buildish` regex to
        # True even with no class or stat in *this* message - and once
        # buildish is True, class_name/stat get pulled in from history no
        # matter how many turns back or how unrelated. Found live Sep 14: a
        # follow-up about a Snake Eye Ring's awakened enchant got answered
        # with a stale cached "Ninja Attack build" brief from several turns
        # earlier because "ring" alone was enough to look buildish. Enchant
        # questions have their own specialist (is_enchant_query is the same
        # gate api/routers/chat.py uses to route to it) - never let the
        # generic class+stat build cache intercept them first.
        return None
    class_name, stat, buildish = parse_query(message, history=history)
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
    for page in use_pages:
        focused = _focus_text(
            page.get("text") or "", dungeon, include_lead=not hm
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

    shiny = await _shiny_divine_reply(redis, message, ttl_seconds)
    if shiny:
        return shiny

    drop = await _drop_reply(redis, message, ttl_seconds)
    if drop:
        return drop
    guide = await _guide_reply(redis, message, history, ttl_seconds)
    if guide:
        return guide
    if _EARLY.search(message or ""):
        return StoredReply(text=_EARLY_TEXT, kind="early")
    slot = await _slot_reply(redis, message)
    if slot:
        return slot
    return await _build_reply(redis, message, history)


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
    if is_enchant_query(message):
        # Same reasoning as _build_reply: a slot noun (ring/armor/weapon/
        # ability) alone can flip buildish True and pull a stale class+stat
        # in from history, which would mint *this* enchant answer over the
        # general class+stat build brief - corrupting it for the next real
        # "best attack ninja build" ask. Enchant answers are never a
        # substitute for the general build brief.
        return None
    text = reply.strip()[:MAX_BRIEF_CHARS]
    class_name, stat, buildish = parse_query(message, history=history)
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
