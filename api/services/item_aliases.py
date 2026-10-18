"""Resolve RotMG item nicknames to RealmEye wiki titles.

Players type QOT, Vest, Vile, Snake Ring, Lean - not the full wiki name.
The set-visualizer specialist expands those before the UI fetches sprites.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from ..models.build import (
    CLASS_ABILITY_HUB,
    CLASS_ARMOR_HUB,
    RINGS_HUB,
    WEAPON_FAMILIES,
    weapon_family,
)
from ..models.item import ItemProfile
from .fuzzy_match import fuzzy_closed_vocab, fuzzy_word_match, levenshtein
from .wiki_scaling import (
    HUB_PREFIX,
    ITEM_CACHE_PREFIX,
    _hub_index,
    _LE_CLONE,
    _SKIP_NAME,
    cached_items_from_place,
    read_cached_item,
    top_build_items,
)

SET_SLOT_COUNT = 4
SET_SLOTS = ("weapon", "ability", "armor", "ring")
CATALOG_PREFIX = "item:alias-catalog:v8"
REALMEYE_WIKI = "https://www.realmeye.com/wiki"

# RealmEye hub slug -> the noun Claude should use in prose. A Bard bow
# must never be called a sword just because the item name sounds martial.
_HUB_KIND: dict[str, str] = {
    "bows": "bow",
    "longbows": "bow",
    "staves": "staff",
    "spellblades": "spellblade",
    "daggers": "dagger",
    "dual-blades": "dagger",
    "swords": "sword",
    "flails": "flail",
    "wands": "wand",
    "morning-stars": "wand",
    "katanas": "katana",
    "tachis": "katana",
    "lutes": "lute",
    "cloaks": "cloak",
    "quivers": "quiver",
    "spells": "spell",
    "tomes": "tome",
    "helms": "helm",
    "shields": "shield",
    "seals": "seal",
    "poisons": "poison",
    "skulls": "skull",
    "traps": "trap",
    "orbs": "orb",
    "prisms": "prism",
    "scepters": "scepter",
    "stars": "star",
    "wakizashi": "wakizashi",
    "maces": "mace",
    "sheaths": "sheath",
    "sigils": "sigil",
    "robes": "robe",
    "leather-armors": "leather armor",
    "heavy-armors": "heavy armor",
    "rings": "ring",
}

# Overlay for names that are ambiguous, too short, or not in the title
# letters (Lean, Cult staff). Letter nicknames still generate from hubs.
COMMUNITY_ALIASES: dict[str, str] = {
    "lean": "Chrysalis of Eternity",
    "lean crown": "Chrysalis of Eternity",
    "oreo": "Seal of Blasphemous Prayer",
    "tablet": "Tablet of the King's Avatar",
    "vest": "Vest of Abandoned Shadows",
    "vesture": "Vesture of Duality",
    "scythe": "Jailer's Scythe",
    "ogmur": "Shield of Ogmur",
    "cult staff": "Staff of Unholy Sacrifice",
    "cult": "Staff of Unholy Sacrifice",
    "tshot": "Thousand Shot",
    "t shot": "Thousand Shot",
    "vbow": "Bow of the Void",
    "void bow": "Bow of the Void",
    "maka": "Makakoyumi",
    "lumi": "Lumiaire",
    "doku": "Doku No Ken",
    "ray": "Ray Katana",
    "dblade": "Demon Blade",
    "cutlass": "Pirate King's Cutlass",
    "colossus": "Sword of the Colossus",
    "fractal": "Fractal Blades",
    "fractals": "Fractal Blades",
    "phantom sickle": "Phantom Sickle",
    "sickle": "Phantom Sickle",
    "divinity": "Divinity",
    "damnation": "Damnation",
    "enforcer": "Enforcer",
    "valor": "Valor",
    "tarnished": "Tools of the Tarnished",
    "tools of the tarnished": "Tools of the Tarnished",
    "tenne": "Hirejou Tenne",
    "happi": "Ethereal Happi",
    "jacket": "Cackling Straitjacket",
    "straitjacket": "Cackling Straitjacket",
    "strait jacket": "Cackling Straitjacket",
    "nil": "Armor of Nil",
    "centaur": "Centaur's Shielding",
    "centaurs": "Centaur's Shielding",
    "kimono": "Flowering Kimono",
    "cult robe": "Ritual Robe",
    "diplo": "Diplomatic Robe",
    "diplomat": "Diplomatic Robe",
    "diplomatic": "Diplomatic Robe",
    "resu": "Resurrected Warrior's Armor",
    "fungal bp": "Fungal Breastplate",
    "fungal breastplate": "Fungal Breastplate",
    "vessel": "Boundless Vessel",
    "cuirass": "Royal Guard's Cuirass",
    "glad": "Gladiator Guard",
    "glad guard": "Gladiator Guard",
    "guard": "Gladiator Guard",
    "tools": "Tools of the Tarnished",
    "ronin": "Ronin's Wakizashi",
    "ronins": "Ronin's Wakizashi",
    "ronin waki": "Ronin's Wakizashi",
    "ronins waki": "Ronin's Wakizashi",
    "ryu": "Ryu's Blade",
    "ryus": "Ryu's Blade",
    "mt waki": "Ryu's Blade",
    "mtwaki": "Ryu's Blade",
    "crown": "The Forgotten Crown",
    "forgotten crown": "The Forgotten Crown",
    "gem": "The Twilight Gemstone",
    "gemstone": "The Twilight Gemstone",
    "bracer": "Bracer of the Guardian",
    "poop sock": "Bracer of the Guardian",
    "poopsock": "Bracer of the Guardian",
    "banner": "Battalion Banner",
    "omni": "Omnipotence Ring",
    "kage": "Kagenohikari",
    "snake ring": "Snake Eye Ring",
    "snake eye": "Snake Eye Ring",
    "snakeeye": "Snake Eye Ring",
    "coro": "Divine Coronation",
    "amulet": "Amulet of Restoration",
    "pungi": "Snake Charmer's Pungi",
    "escu": "Oryx's Escutcheon",
    "jugg": "Helm of the Juggernaut",
    "mseal": "Marble Seal",
    "marble seal": "Marble Seal",
    "lotus": "Lifebringing Lotus",
    "slurp spell": "Slurpian Sea Scroll",
    "slurp": "Slurpian Sea Scroll",
    "ot spell": "Slurpian Sea Scroll",
    "clib quiver": "Quiver of Shrieking Scepters",
    "lib quiver": "Quiver of Shrieking Scepters",
    "clib quiv": "Quiver of Shrieking Scepters",
    "lib quiv": "Quiver of Shrieking Scepters",
    "conflict": "Orb of Conflict",
    "arcana": "Primal Arcana",
    "cornea": "Command Cornea",
    "void quiv": "Quiver of Shadows",
    "void quiver": "Quiver of Shadows",
    "qot": "Quiver of Thunder",
    "leaf bow": "Leaf Bow",
    "lbow": "Leaf Bow",
    "cbow": "Coral Bow",
    "coral bow": "Coral Bow",
    "dbow": "Doom Bow",
    "doom bow": "Doom Bow",
    "clockwork": "Clockwork Repeater",
    "clockwork repeater": "Clockwork Repeater",
    "triangle": "The Triangle",
    "the triangle": "The Triangle",
    "fulmination": "Scepter of Fulmination",
    "conducting wand": "Conducting Wand",
    "souls guidance": "Soul's Guidance",
    "soul's guidance": "Soul's Guidance",
    "bulwark": "Wand of the Bulwark",
    "wand of the bulwark": "Wand of the Bulwark",
    "devastation": "Scepter of Devastation",
    "cnidaria": "Cnidaria Rod",
    "cnidaria rod": "Cnidaria Rod",
    "water dragon silk": "Water Dragon Silk Robe",
    "tezutsu": "Tezutsu Hanabi",
    "hanabi": "Tezutsu Hanabi",
    "scepter of rust": "Scepter of Rust",
    "dispersion": "Amulet of Dispersion",
    "dusky": "Dusky Catalyst",
    "dusky catalyst": "Dusky Catalyst",
    "hannya": "Fractured Hannya",
    "astronomer": "Astronomer's Gown",
    "astronomer's gown": "Astronomer's Gown",
}

_EXTRACT_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "is",
        "it",
        "on",
        "for",
        "to",
        "of",
        "get",
        "got",
        "vs",
        "better",
        "best",
        "what",
        "which",
        "should",
        "i",
        "me",
        "my",
        "you",
        "we",
        "this",
        "that",
        "with",
        "from",
        "do",
        "does",
        "how",
    }
)

_STOP = frozenset({"of", "the", "a", "an", "and", "to", "for", "s"})
_GENERIC = frozenset(
    {
        "ring",
        "rings",
        "armor",
        "armour",
        "robe",
        "bow",
        "staff",
        "wand",
        "sword",
        "dagger",
        "star",
        "trap",
        "quiver",
        "cloak",
        "seal",
        "shield",
        "helm",
        "tome",
        "spell",
        "orb",
        "prism",
        "lute",
        "mace",
        "poison",
        "skull",
        "scepter",
        "sheath",
        "sigil",
        "katana",
        "tachi",
        "flail",
        "spirit",
        "item",
        "ut",
        "st",
        "blade",
        "blades",
    }
)

# Slot/type words used to build Vbow, Dblade, etc.
_TYPE_WORDS = frozenset(
    {
        "bow",
        "staff",
        "sword",
        "katana",
        "blade",
        "dagger",
        "wand",
        "star",
        "kunai",
        "cloak",
        "quiver",
        "trap",
        "lute",
        "orb",
        "prism",
        "tome",
        "spell",
        "helm",
        "shield",
        "seal",
        "skull",
        "poison",
        "scepter",
        "mace",
        "sheath",
        "sigil",
        "tachi",
        "flail",
        "ring",
        "robe",
        "scythe",
        "cutlass",
        "spellblade",
        "flail",
        "tachi",
        "longbow",
        "shuriken",
    }
)

_COMPOUND_SUFFIXES = (
    "jacket",
    "robe",
    "plate",
    "mail",
    "guard",
    "breastplate",
    "kimono",
    "cuirass",
)

# Last-word types that are too vague as a first-word-only nickname.
# Fungal Breastplate is "fungal bp", not "fungal".
_QUALIFIED_TAIL = frozenset({"breastplate"})
_TAIL_ABBREV = {"breastplate": "bp", "wakizashi": "waki", "quiver": "quiv"}

_BARE_QUALITY_WORDS = {
    "rare", "epic", "legendary", "mythic", "godly", "common", "uncommon", "fabled",
}
# Same words as _BARE_QUALITY_WORDS, but stripped from *inside* a segment
# (not just when the whole segment is nothing else) - "rare genesis spell"
# and "legendary snake eye ring" name real items with a rarity tier glued
# on the front, same as "shiny"/"divine" already were. Found live Sep 15:
# "rare genesis spell" and "rare diplomatic robe" kept their "rare" prefix
# and failed to resolve against the catalog ("Genesis Spell"/"Diplomatic
# Robe" have no "rare" in their wiki titles).
_QUALITY_WORDS_RE = re.compile(
    r"\b(?:" + "|".join(sorted(_BARE_QUALITY_WORDS)) + r")\b", re.I
)
_SHINY = re.compile(r"\b(?:all\s+)?shiny\b", re.I)
_DIVINE = re.compile(r"\b(?:all\s+)?divine\b", re.I)
# Enchantment slot rarities on RealmEye slots.png (1/2/3/4 diamonds).
# Highest listed first so "shiny legendary divine" keeps Divine.
RARITY_TIERS = ("divine", "legendary", "rare", "uncommon")
RARITY_ALIASES = {
    "divine": ("divine", "div"),
    "legendary": ("legendary", "legend", "legen", "leg"),
    "rare": ("rare",),
    "uncommon": ("uncommon", "uncomm", "unco", "unc"),
}
_RARITY_ALT = "|".join(RARITY_TIERS)
_VISUAL_FLAG = (
    r"(?:all\s+)?"
    rf"(?:shiny\s+(?:{_RARITY_ALT})|(?:{_RARITY_ALT})\s+shiny|shiny|{_RARITY_ALT})"
)
_WITH_ITEMS = re.compile(r"\bwith\s+([\s\S]+?)(?:[.!?]|$)", re.I)
# "Full shiny divine A, B, C, and D" names a four-slot set without ever
# saying "with" - see extract_set_item_names' fallback below.
_AFTER_SHINY_DIVINE = re.compile(
    rf"\b{_VISUAL_FLAG}\b\s+(.+?)(?:[.!?]|$)",
    re.I,
)
_LOOK_LIKE_TAIL = re.compile(r"\s+looks?\s+like\b.*$", re.I)
_NAME_SPLIT = re.compile(r",\s*(?:and\s+)?|\s+and\s+", re.I)
_SHINY_DIVINE_WORDS = re.compile(
    rf"\b(?:all\s+)?(?:shiny|{_RARITY_ALT})\b", re.I
)


def parse_rarity(message: str) -> Optional[str]:
    """Highest named slot rarity, or None. Shiny is a separate flag."""
    text = (message or "").lower()
    for tier in RARITY_TIERS:
        for name in RARITY_ALIASES[tier]:
            if re.search(rf"\b{re.escape(name)}\b", text):
                return tier
    return None
_LEADING_AND = re.compile(r"^(?:and|&)\s+", re.I)
# "Crown all shiny divine" is the last comma-segment when the user puts
# "all shiny divine" after the list. Shiny/divine words are stripped
# separately; leftover "all"/"please" is not part of the item name.
_FILLER_TAIL = re.compile(
    r"\s+\b(?:all|please|pls|thanks|thank you)\b\s*$", re.I
)
_CATALOG_LOCKS: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True)
class CatalogItem:
    name: str
    slot: str
    aliases: frozenset[str]
    hub: str = ""


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _norm(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _tokens(text: str) -> list[str]:
    return [part for part in _norm(text).split() if part]


def _sig_words(name: str) -> list[str]:
    return [word for word in _tokens(name) if word not in _STOP]


def _stem(text: str) -> str:
    """fractals → fractal; cutlass stays cutlass."""
    word = (text or "").strip()
    if word.endswith("s") and not word.endswith("ss") and len(word) > 4:
        return word[:-1]
    return word


def _levenshtein(a: str, b: str) -> int:
    return levenshtein(a, b)


def _fuzzy_word_match(query_word: str, name_word: str) -> bool:
    return fuzzy_word_match(query_word, name_word)


def _type_words_in(name: str) -> list[str]:
    found: list[str] = []
    for word in _tokens(name):
        if word in _TYPE_WORDS:
            found.append(word)
        elif word.endswith("s") and word[:-1] in _TYPE_WORDS:
            found.append(word[:-1])
    return found


def acronym_variants(name: str) -> set[str]:
    """Letter nicknames from the title.

    Quiver of Thunder → qot (keeps of) and qt (skips of/the).
    Trap of the Vile Spirit → tvs and totvs.
    """
    tokens = _tokens(name)
    significant = [word for word in tokens if word not in _STOP]
    keep_of = [word for word in tokens if word not in {"the", "a", "an", "and", "to", "for"}]
    variants = {
        "".join(word[0] for word in significant if word),
        "".join(word[0] for word in keep_of if word),
        "".join(word[0] for word in tokens if word),
    }
    return {variant for variant in variants if len(variant) >= 2}


def acronym(name: str) -> str:
    variants = acronym_variants(name)
    keep_of = "".join(
        word[0]
        for word in _tokens(name)
        if word not in {"the", "a", "an", "and", "to", "for"}
    )
    return keep_of if keep_of in variants else next(iter(variants), "")


def generated_aliases(name: str) -> frozenset[str]:
    words = _sig_words(name)
    aliases = {_norm(name), _compact(name), *acronym_variants(name)}
    if len(words) >= 2:
        # Doom Bow → dbow, Coral Venom Trap → ctrap
        aliases.add(words[0][0] + words[-1])
        aliases.add(f"{words[0]} {words[-1]}")
    if "ring" in _tokens(name) and words:
        aliases.add(f"{words[0]} ring")
    types = _type_words_in(name)
    distinctive = [word for word in words if word not in _TYPE_WORDS]
    if types and distinctive:
        kind = types[0]
        mark = distinctive[0]
        # Bow of the Void → vbow / void bow; Demon Blade → dblade
        aliases.add(mark[0] + kind)
        aliases.add(f"{mark} {kind}")
    if words:
        first = words[0]
        last = words[-1]
        if first not in _GENERIC:
            if last in _TAIL_ABBREV:
                short = _TAIL_ABBREV[last]
                aliases.add(f"{first} {short}")  # fungal bp, ronin waki
                aliases.add(first + short)
                aliases.add(f"{first}s {short}")  # ronins waki
            if last not in _QUALIFIED_TAIL and len(first) >= 3:
                aliases.add(first)
            if len(first) >= 6 and last not in _QUALIFIED_TAIL:
                aliases.add(first[:4])  # Makakoyumi → maka, Resurrected → resu
                aliases.add(first[:5])  # Diplomatic → diplo, Gladiator → gladi
        if last not in _GENERIC and len(last) >= 3:
            aliases.add(last)  # Nil, Tenne, Happi, Vessel, Cuirass
            if last.startswith("gem") and last != "gem":
                aliases.add("gem")  # Twilight Gemstone
            if len(last) >= 6:
                prefix = last[:4]
                if prefix != "gems":
                    aliases.add(prefix)  # jugg, escu, coro
        for suffix in _COMPOUND_SUFFIXES:
            if last.endswith(suffix) and suffix != last:
                aliases.add(suffix)  # Straitjacket → jacket
    for word in words[1:]:
        if len(word) >= 3 and word not in _GENERIC:
            aliases.add(word)
    return frozenset(alias for alias in aliases if len(alias) >= 2)


def catalog_item(name: str, slot: str, hub: str = "") -> CatalogItem:
    return CatalogItem(
        name=name, slot=slot, aliases=generated_aliases(name), hub=hub
    )


def item_wiki_url(name: str) -> str:
    slug = (name or "").strip().lower()
    slug = slug.replace("'", "-").replace("\u2019", "-").replace("\u2018", "-")
    slug = slug.replace(".", "").replace(":", "-").replace(";", "-")
    slug = slug.replace("(", "-").replace(")", "-")
    slug = slug.replace(" ", "-")
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return f"{REALMEYE_WIKI}/{slug}" if slug else REALMEYE_WIKI


def hub_kind(slug: str, slot: str = "") -> str:
    if slug in _HUB_KIND:
        return _HUB_KIND[slug]
    if slot == "ring" or (slug or "").endswith("-rings"):
        return "ring"
    return slot or "item"


def _find_catalog_item(
    catalog: list[CatalogItem], name: Optional[str]
) -> Optional[CatalogItem]:
    if not name:
        return None
    key = name.lower()
    for item in catalog:
        if item.name.lower() == key:
            return item
    return None


def _item_kind(
    item: Optional[CatalogItem],
    slot: str,
    class_name: Optional[str],
) -> str:
    if item and item.hub:
        return hub_kind(item.hub, slot or item.slot)
    if slot == "weapon" and class_name:
        hubs, _label = weapon_family(class_name)
        if hubs:
            return hub_kind(hubs[0], slot)
    if slot == "ability" and class_name:
        return hub_kind(CLASS_ABILITY_HUB.get(class_name, ""), slot)
    if slot == "armor" and class_name:
        return hub_kind(CLASS_ARMOR_HUB.get(class_name, ""), slot)
    if slot == "ring":
        return "ring"
    return hub_kind(item.hub if item else "", slot)


def community_canonical(query: str) -> Optional[str]:
    key = _norm(query)
    for candidate in (key, _stem(key)):
        if candidate in COMMUNITY_ALIASES:
            return COMMUNITY_ALIASES[candidate]
    compact = _compact(query)
    for nick, canonical in COMMUNITY_ALIASES.items():
        if _compact(nick) == compact or _compact(nick) == _compact(_stem(key)):
            return canonical
    return fuzzy_closed_vocab(key, COMMUNITY_ALIASES.items())


def extract_mentioned_items(message: str) -> list[str]:
    """Every community nickname in the message, left to right.

    "is cbow awakening or lbow awakening better" must return both Coral
    Bow and Leaf Bow so the enchant/DPS agents can compare them. Phrase
    keys (lean crown, leaf bow) win over their shorter pieces.
    """
    text = message or ""
    lower = text.lower()
    hits: list[tuple[int, int, str]] = []
    for key, canon in sorted(COMMUNITY_ALIASES.items(), key=lambda kv: -len(kv[0])):
        for match in re.finditer(rf"\b{re.escape(key)}\b", lower):
            hits.append((match.start(), match.end(), canon))
    for match in re.finditer(r"\b[A-Za-z][A-Za-z']+\b", text):
        token = match.group(0)
        if token.lower() in _EXTRACT_STOP:
            continue
        # Exact keys already matched above. This pass is typos of 4+ letter
        # nicknames only; min_len=3 would map "get" -> "gem".
        canon = fuzzy_closed_vocab(
            token, COMMUNITY_ALIASES.items(), min_len=4
        )
        if canon:
            hits.append((match.start(), match.end(), canon))
    hits.sort(key=lambda row: (row[0], -(row[1] - row[0])))
    found: list[str] = []
    seen: set[str] = set()
    covered: list[tuple[int, int]] = []
    for start, end, canon in hits:
        if any(start >= a and end <= b for a, b in covered):
            continue
        covered.append((start, end))
        key = canon.lower()
        if key not in seen:
            seen.add(key)
            found.append(canon)
    return found


def score_nickname(
    query: str, item: CatalogItem, slot_hint: Optional[str] = None
) -> int:
    qn = _norm(query)
    qc = _compact(query)
    if not qn:
        return 0
    if qn == _norm(item.name) or qc == _compact(item.name):
        return 1000
    score = 0
    alias_compacts = {_compact(alias) for alias in item.aliases}
    stems = {qn, qc, _stem(qn), _compact(_stem(qn))}
    if any(stem in item.aliases or stem in alias_compacts for stem in stems if stem):
        score += 80
    q_tokens = [token for token in qn.split() if token]
    name_words = set(_tokens(item.name))
    sig = _sig_words(item.name)
    first_word_only = (
        len(q_tokens) == 1
        and len(sig) >= 2
        and q_tokens[0] == sig[0]
        and sig[-1] in _QUALIFIED_TAIL
    )
    if not first_word_only:
        # A single-letter typo on an otherwise-exact word match ("croak"
        # for the real "crook") is as strong a signal as an exact match
        # for our purposes, so it earns the same high-score tier instead
        # of falling to the looser +25 branch below (which alone doesn't
        # clear resolve_against_catalog's score-40 cutoff). Found live
        # Sep 15: "bogwood croak" failed to resolve to "Bogwood Crook" at
        # all.
        if q_tokens and all(
            token in name_words or any(_fuzzy_word_match(token, word) for word in name_words)
            for token in q_tokens
        ):
            score += 40 + 15 * len(q_tokens)
        elif q_tokens and all(
            any(
                word == token
                or _stem(word) == token
                or _stem(token) == word
                or _stem(token) == _stem(word)
                or (len(token) >= 4 and word.startswith(token))
                for word in name_words
            )
            for token in q_tokens
        ):
            score += 25
        if len(q_tokens) == 1 and re.search(
            rf"\b{re.escape(q_tokens[0])}\b", item.name, re.I
        ):
            score += 35
    if slot_hint and item.slot == slot_hint:
        score += 12
    return score


def resolve_against_catalog(
    query: str,
    catalog: list[CatalogItem],
    slot_hint: Optional[str] = None,
) -> Optional[str]:
    """Pick a unique wiki title for a nickname, or None if it's ambiguous."""
    community = community_canonical(query)
    if community:
        return community

    ranked = sorted(
        (
            (score_nickname(query, item, slot_hint), len(item.name), item.name)
            for item in catalog
        ),
        key=lambda row: (-row[0], row[1], row[2].lower()),
    )
    if not ranked or ranked[0][0] < 40:
        return None
    top = ranked[0][0]
    winners = [name for score, _length, name in ranked if score == top]
    if len(winners) == 1:
        return winners[0]
    if slot_hint:
        slotted = [
            item.name
            for item in catalog
            if item.name in winners and item.slot == slot_hint
        ]
        if len(set(slotted)) == 1:
            return slotted[0]
    if top >= 80:
        return winners[0]
    return None


# Fungal Cavern and Crystal Cavern are one dungeon chain. "fungal star"
# and "crystal star" share that loot. Shiny asks prefer the UT star.
_LINKED_PLACES = {
    "fungal": ("crystal",),
    "crystal": ("fungal",),
}


def _kind_forms(text: str) -> set[str]:
    """staff / staves / spellblade forms without splitting morning-star into star."""
    raw = (text or "").replace("-", " ").strip().lower()
    if not raw:
        return set()
    compact = raw.replace(" ", "")
    forms = {raw, compact, _stem(compact)}
    if " " not in raw:
        if raw.endswith("s") and not raw.endswith("ss") and len(raw) > 3:
            forms.add(raw[:-1])
        elif len(raw) >= 3:
            forms.add(raw + "s")
    return {form for form in forms if len(form) >= 3}


def _register_kind_group(members: set[str]) -> None:
    group = tuple(sorted(members))
    if not group:
        return
    for word in group:
        prior = _KIND_SYNONYMS.get(word)
        merged = tuple(sorted(set(prior or ()) | set(group)))
        for item in merged:
            _KIND_SYNONYMS[item] = merged


# Sister weapon hubs share a meaning: staff ≈ spellblade, sword ≈ flail.
_KIND_SYNONYMS: dict[str, tuple[str, ...]] = {}
for _classes, _hubs, _label in WEAPON_FAMILIES:
    family: set[str] = set()
    for hub in _hubs:
        family |= _kind_forms(hub)
        noun = _HUB_KIND.get(hub)
        if noun:
            family |= _kind_forms(noun)
    _register_kind_group(family)
_register_kind_group(
    _kind_forms("star")
    | _kind_forms("stars")
    | _kind_forms("kunai")
    | _kind_forms("shuriken")
)
_PLACE_GENERIC = frozenset(
    {
        "cavern",
        "dungeon",
        "the",
        "of",
        "chamber",
        "room",
        "lands",
        "land",
        "biome",
        "forest",
        "abyss",
        "portal",
        "boss",
        "guide",
    }
)
SUGGEST_KEY = "wiki:suggest:v2"
SUGGEST_TTL_DEFAULT = 7 * 24 * 3600
_SUGGEST_FILLER = frozenset(
    {
        "i",
        "im",
        "i'm",
        "want",
        "to",
        "see",
        "a",
        "an",
        "the",
        "of",
        "for",
        "please",
        "show",
        "me",
        "my",
        "look",
        "at",
        "what",
        "does",
        "like",
        "with",
        "and",
        "or",
        "is",
        "it",
        "this",
        "that",
    }
)


def _is_limited_item(item: ItemProfile) -> bool:
    if item.limited_edition:
        return True
    if _LE_CLONE.search(item.name or ""):
        return True
    return bool(re.search(r"limited|\(le\)", item.tier or "", re.I))


def _tier_code(item: ItemProfile) -> str:
    raw = (item.tier or "").strip().upper()
    match = re.search(r"\b(UT\+?|ST|L|T[0-7])\b", raw)
    return match.group(1) if match else ""


def _is_st_item(item: ItemProfile) -> bool:
    return _tier_code(item) == "ST"


def _is_ut_item(item: ItemProfile) -> bool:
    code = _tier_code(item)
    return code.startswith("UT") or code == "L"


def item_can_be_shiny(item: ItemProfile) -> bool:
    """ST set pieces cannot be shiny."""
    return not _is_st_item(item)


def _shiny_place_score(item: ItemProfile) -> Optional[int]:
    """Higher is better. None means skip (ST, or no UT / shiny sprite)."""
    if _is_st_item(item):
        return None
    has_shiny = bool(item.shiny_sprite_url)
    is_ut = _is_ut_item(item)
    if not has_shiny and not is_ut:
        return None
    return (20 if has_shiny else 0) + (10 if is_ut else 0)


def _slot_keys(text: str) -> set[str]:
    raw = (text or "").replace("-", " ").strip().lower()
    if not raw:
        return set()
    compact = raw.replace(" ", "")
    keys = {raw, compact, _stem(compact)}
    for token in (compact, _stem(compact), raw):
        keys.update(_KIND_SYNONYMS.get(token, ()))
    return {key for key in keys if key}


def _item_matches_kind(item: ItemProfile, kinds: tuple[str, ...], extra: str = "") -> bool:
    have = _slot_keys(item.type or "") | _slot_keys(extra)
    want: set[str] = set()
    for kind in kinds:
        if kind:
            want |= _slot_keys(kind)
    return bool(have & want)


def _split_place_kind(query: str) -> Optional[tuple[str, str]]:
    parts = _tokens(query)
    if len(parts) == 2:
        return parts[0], _stem(parts[1])
    if len(parts) < 3:
        return None
    compact = "".join(parts[-2:])
    spaced = " ".join(parts[-2:])
    if compact in _KIND_SYNONYMS or spaced in _KIND_SYNONYMS:
        return parts[0], _stem(compact)
    if parts[1] in _PLACE_GENERIC:
        return parts[0], _stem(parts[-1])
    return None


def _explicit_limited_query(query: str) -> bool:
    return bool(re.search(r"\blimited\b|\(le\)", query or "", re.I))


async def prefer_original_name(
    redis: aioredis.Redis, name: str, *, query: str = ""
) -> Optional[str]:
    """Swap a Limited Edition clone for the original unless the user asked for LE."""
    if _explicit_limited_query(query):
        return name
    item = await read_cached_item(redis, name)
    if not item or not _is_limited_item(item):
        return name
    original = (item.original_name or "").strip()
    if original and original.lower() != item.name.lower():
        return original
    return None


async def resolve_place_slot(
    redis: aioredis.Redis,
    query: str,
    catalog: list[CatalogItem],
    *,
    want_shiny: bool = False,
) -> Optional[str]:
    """'fungal star' -> item whose drop_locations mention Fungal/Crystal and type is star.

    Shiny asks skip ST (set pieces cannot be shiny) and prefer UT, then a
    recorded shiny sprite.
    """
    parsed = _split_place_kind(query)
    if not parsed:
        return None
    place, kind = parsed
    kinds = _KIND_SYNONYMS.get(kind) or _KIND_SYNONYMS.get(_stem(kind)) or (kind,)
    known = _TYPE_WORDS | set(_HUB_KIND.values()) | set(_KIND_SYNONYMS)
    if kind not in known and _stem(kind) not in known and not any(
        token in known for token in kinds
    ):
        return None
    by_name = {row.name.lower(): row for row in catalog}
    hits: list[ItemProfile] = []
    for loc in (place, *_LINKED_PLACES.get(place, ())):
        for item in await cached_items_from_place(redis, loc):
            if _is_limited_item(item):
                continue
            cat = by_name.get(item.name.lower())
            extra = hub_kind(cat.hub, cat.slot) if cat else ""
            if not _item_matches_kind(item, kinds, extra=extra):
                continue
            if not any(hit.name.lower() == item.name.lower() for hit in hits):
                hits.append(item)
    if not hits:
        return None
    if want_shiny:
        ranked: list[tuple[int, str]] = []
        for item in hits:
            score = _shiny_place_score(item)
            if score is None:
                continue
            ranked.append((score, item.name))
        if not ranked:
            return None
        ranked.sort(key=lambda row: (-row[0], row[1].lower()))
        return ranked[0][1]
    return hits[0].name


async def suggest_terms(
    redis: aioredis.Redis,
    query: str,
    *,
    limit: int = 8,
) -> list[dict[str, str]]:
    """Prefix match warmed item/dungeon names for composer Tab complete."""
    raw_query = query or ""
    want_shiny = bool(re.search(r"\bshin(?:y|ies)\b", raw_query, re.I))
    text = raw_query.strip().lower()
    if len(text) < 2:
        return []
    words = [part for part in text.split() if part]
    last = words[-1] if words else ""
    needles: list[str] = []
    if last and last not in _SUGGEST_FILLER and len(last) >= 2:
        needles.append(last)
        if len(words) >= 2:
            needles.append(" ".join(words[-2:]))
    elif len(words) <= 2 and len(text) >= 2:
        needles.append(text)
    if not needles:
        return []
    raw = await redis.get(SUGGEST_KEY)
    if not raw:
        try:
            await warm_suggest_index(redis, ttl_seconds=SUGGEST_TTL_DEFAULT)
        except Exception:
            logger.exception("Suggest index warm on miss failed")
        raw = await redis.get(SUGGEST_KEY)
    if not raw:
        return []
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    picked: dict[str, dict] = {}
    for row in rows:
        alias_raw = (row.get("a") or "").strip()
        alias = alias_raw.lower()
        name = (row.get("n") or "").strip()
        if not name:
            continue
        if want_shiny and re.search(r"\bST\b", row.get("t") or "", re.I):
            continue
        matched = False
        last_prefix = bool(last) and (
            alias.startswith(last) or name.lower().startswith(last)
        )
        for needle in needles:
            if len(needle) < 2:
                continue
            if alias.startswith(needle) or name.lower().startswith(needle):
                matched = True
                break
            if len(needle) >= 3 and (needle in alias or needle in name.lower()):
                matched = True
                break
        if not matched:
            continue
        shown = alias_raw or name
        if last_prefix and alias.startswith(last):
            shown = alias_raw
        elif last and last_prefix and name.lower().startswith(last):
            shown = name
        key = name.lower()
        prior = picked.get(key)
        if prior and (prior["_last"] or not last_prefix):
            continue
        picked[key] = {
            "name": name,
            "kind": row.get("k") or "item",
            "alias": shown,
            "_last": last_prefix,
        }
    hits = sorted(
        picked.values(),
        key=lambda row: (not row["_last"], row["name"].lower()),
    )
    return [{k: v for k, v in row.items() if k != "_last"} for row in hits[:limit]]


def _source_terms(text: str) -> list[str]:
    raw = (text or "").strip()
    if len(raw) < 3:
        return []
    parts = re.split(r"\s*(?:,|;|/|\band\b)\s*", raw, flags=re.I)
    return [part.strip() for part in parts if len(part.strip()) >= 3]


def _slug_alias(slug: str) -> str:
    return (slug or "").replace("-", " ").strip()


async def warm_suggest_index(
    redis: aioredis.Redis, *, ttl_seconds: int
) -> dict[str, int]:
    """Build Tab-complete terms from every scraped Redis store.

    One pass at warm / first miss. Hubs, item profiles, dungeon pages,
    biomes, community nicknames, and place-slot aliases all go in.
    """
    from .biomes import BIOMES, biome_index_entries
    from .dungeon_guide import (
        PAGE_CACHE_PREFIX,
        _NICKNAMES,
        event_index_entries,
        get_or_scrape_index,
    )

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(canonical: str, alias: str, kind: str, tier: str = "") -> None:
        name = (canonical or "").strip()
        nick = (alias or "").strip()
        if not name or not nick or len(nick) < 2:
            return
        if kind == "item" and (
            _SKIP_NAME.search(name) or _LE_CLONE.search(name)
        ):
            return
        key = (name.lower(), nick.lower())
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {"n": name, "a": nick, "k": kind, "t": (tier or "").strip()}
        )

    def add_named(
        canonical: str,
        *,
        kind: str,
        tier: str = "",
        extra: tuple[str, ...] | list[str] = (),
    ) -> None:
        add(canonical, canonical, kind, tier)
        for alias in extra:
            add(canonical, alias, kind, tier)
        if kind == "item":
            for alias in generated_aliases(canonical):
                add(canonical, alias, kind, tier)

    catalog = await load_item_catalog(
        redis, ttl_seconds=ttl_seconds, class_name=None, allow_scrape=False
    )
    by_name = {row.name.lower(): row for row in catalog}
    for item in catalog:
        add_named(item.name, kind="item", extra=tuple(item.aliases))

    for nick, canonical in COMMUNITY_ALIASES.items():
        add(canonical, nick, "item")

    async for raw_key in redis.scan_iter(match=f"{HUB_PREFIX}:*", count=200):
        raw = await redis.get(raw_key)
        if not raw:
            continue
        try:
            hub_rows = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(hub_rows, list):
            continue
        slug = str(raw_key).rsplit(":", 1)[-1]
        for row in hub_rows:
            if not isinstance(row, dict):
                continue
            name = (row.get("name") or "").strip()
            if not name:
                continue
            add_named(
                name,
                kind="item",
                tier=str(row.get("tier") or ""),
                extra=(hub_kind(slug, ""),) if hub_kind(slug, "") else (),
            )

    async for raw_key in redis.scan_iter(match=f"{ITEM_CACHE_PREFIX}:*", count=200):
        raw = await redis.get(raw_key)
        if not raw:
            continue
        try:
            item = ItemProfile.model_validate_json(raw)
        except Exception:
            continue
        if _is_limited_item(item):
            original = (item.original_name or "").strip()
            if original:
                add_named(original, kind="item")
            continue
        add_named(item.name, kind="item", tier=item.tier or "")
        cat = by_name.get(item.name.lower())
        kind = hub_kind(cat.hub, cat.slot) if cat else _stem((item.type or "").lower())
        nick_kinds = _KIND_SYNONYMS.get(kind) or _KIND_SYNONYMS.get(_stem(kind)) or (
            (kind,) if kind else ()
        )
        for loc in item.drop_locations or []:
            add(item.name, loc, "item", item.tier or "")
            for word in _tokens(loc):
                if word in _PLACE_GENERIC or len(word) < 3:
                    continue
                add(item.name, word, "item", item.tier or "")
                for nick_kind in nick_kinds:
                    add(item.name, f"{word} {nick_kind}", "item", item.tier or "")
                    for linked in _LINKED_PLACES.get(word, ()):
                        add(
                            item.name,
                            f"{linked} {nick_kind}",
                            "item",
                            item.tier or "",
                        )

    try:
        entries = await get_or_scrape_index(
            redis, ttl_seconds=ttl_seconds, cache_only=True
        )
    except Exception:
        entries = []
    for entry in list(entries) + event_index_entries() + biome_index_entries():
        title = (entry.get("title") or "").strip()
        kind = entry.get("kind") or "dungeon"
        extras = [ _slug_alias(entry.get("slug") or "") ]
        extras.extend(entry.get("aliases") or [])
        if title:
            add_named(title, kind=kind, extra=tuple(x for x in extras if x))

    for biome in BIOMES:
        add_named(
            biome["title"],
            kind="dungeon",
            extra=tuple(biome.get("aliases") or ()),
        )

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
        title = (page.get("title") or "").strip()
        slug = _slug_alias(page.get("slug") or str(raw_key).rsplit(":", 1)[-1])
        if title:
            add_named(title, kind="dungeon", extra=(slug,))
        for row in page.get("drops") or []:
            drop_name = (row.get("name") or "").strip()
            if drop_name:
                add_named(drop_name, kind="item")
            for source in _source_terms(row.get("drops_from") or ""):
                add_named(source, kind="dungeon")

    from .rotmg_hub import hub_item_names

    for hub_name in await hub_item_names(redis):
        add_named(hub_name, kind="item")

    titles = [row["n"] for row in rows if row.get("k") == "dungeon"]
    for nick, target in _NICKNAMES.items():
        needle = target.lower()
        match = next(
            (title for title in titles if needle in title.lower()),
            target,
        )
        add(match, nick, "dungeon")

    if rows:
        await redis.setex(SUGGEST_KEY, ttl_seconds, json.dumps(rows))
    logger.bind(terms=len(rows)).info("Suggest index warmed from scrape cache")
    return {"terms": len(rows)}


def extract_set_item_names(prompt: str) -> list[str]:
    text = prompt or ""
    match = _WITH_ITEMS.search(text)
    candidate = match.group(1) if match else None
    if candidate is None:
        # Regression, found live Sep 14: "Full shiny divine enforcer,
        # ballistic star, straitjacket, and lean" has no "with", so this
        # returned [] and stored_answers._shiny_divine_item_name's
        # single-item guard (`if extract_set_item_names(...): return None`)
        # never tripped - the whole comma list got treated as ONE item name
        # and sent to a doomed wiki scrape (guaranteed 404/timeout, and the
        # frontend's item card spun forever waiting on it). Only take this
        # branch when it actually splits into 2+ real names below - a
        # single name here (e.g. "shiny Crown") is
        # stored_answers._shiny_divine_item_name's job, not this function's.
        after = _AFTER_SHINY_DIVINE.search(text)
        candidate = after.group(1) if after else None
    if candidate is None:
        return []
    candidate = _LOOK_LIKE_TAIL.sub("", candidate)
    names: list[str] = []
    for part in _NAME_SPLIT.split(candidate):
        cleaned = _SHINY_DIVINE_WORDS.sub("", part)
        cleaned = _QUALITY_WORDS_RE.sub("", cleaned)
        cleaned = _LEADING_AND.sub("", cleaned).strip()
        cleaned = _FILLER_TAIL.sub("", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        # A stray comma can split a rarity word off its own item, e.g.
        # "...rare diplomatic robe, shiny rare, the twilight gemstone"
        # (found live Sep 15) yields a bare "rare" segment once "shiny" is
        # stripped. That is never a real item name on its own and, once
        # _QUALITY_WORDS_RE above also strips it, is just empty - the
        # length check below already drops it, no separate case needed.
        if 3 <= len(cleaned) <= 60:
            names.append(community_canonical(cleaned) or cleaned)
    # A real set names 2+ items. This guard used to only apply to the
    # _AFTER_SHINY_DIVINE fallback (`match is None and ...`), so _WITH_ITEMS'
    # very permissive "with <anything>" still counted a single trailing noun
    # phrase as a one-item "set." Found live Sep 14: "Shiny divine snake eye
    # ring. Is it insane with the awakened enchantment?" matched "with the
    # awakened enchantment" and returned ["the awakened enchantment"] - a
    # single bogus "item" that then got scraped as a real wiki page (404) and
    # also made _shiny_divine_item_name wrongly bail out of the real single-
    # item shiny/divine path for "snake eye ring." Applying the >=2 check
    # regardless of which branch matched closes both holes.
    if len(names) < 2:
        return []
    return names[:SET_SLOT_COUNT]


_SET_FOLLOWUP = re.compile(
    r"\b(?:same\s+set|that\s+set|this\s+set|show\s+me\s+all|"
    r"all\s+(?:four\s+)?(?:slots?|items?)|"
    r"all\s+(?:shiny|divine|legendary|rare|uncommon|awakened))\b",
    re.I,
)
_ITEM_TOKEN_RE = re.compile(r"\[item:([^\]]+)\]")


def is_set_followup(message: str) -> bool:
    """True for 'same set but all divine' / 'show me all shiny divine'."""
    text = message or ""
    if extract_set_item_names(text):
        return False
    if _SET_FOLLOWUP.search(text):
        return True
    shiny, rarity = set_visualize_flags(text)
    looks = bool(re.search(r"\blooks?\s+like\b|\bturned\b", text, re.I))
    return bool(looks and (shiny or rarity))


def last_set_names_from_history(history: Optional[list[str]]) -> list[str]:
    """Most recent 2-4 item names from a prior visualize turn."""
    if not history:
        return []
    for prev in reversed(history):
        named = extract_set_item_names(prev or "")
        if named:
            return named
        tokens = [
            token.strip()
            for token in _ITEM_TOKEN_RE.findall(prev or "")
            if token.strip()
        ]
        if len(tokens) >= 2:
            return tokens[:SET_SLOT_COUNT]
    return []


def is_set_visualize_query(message: str, history: Optional[list[str]] = None) -> bool:
    text = message or ""
    if extract_set_item_names(text):
        shiny = bool(_SHINY.search(text))
        rarity = parse_rarity(text)
        return bool(shiny or rarity)
    if history and is_set_followup(text) and last_set_names_from_history(history):
        return True
    return False


def set_visualize_flags(message: str) -> tuple[bool, Optional[str]]:
    """Independent shiny flag plus the highest named slot rarity."""
    text = message or ""
    return bool(_SHINY.search(text)), parse_rarity(text)


def is_stat_class_shiny_divine_query(
    message: str, class_name: Optional[str], stat: Optional[str]
) -> bool:
    """'Show me full shiny divine attack huntress' - shiny/divine wording
    plus a resolved class+stat, but no items named directly (a real named
    set always takes priority - this only fires when
    extract_set_item_names finds nothing). The user wants the best weapon/
    ability/armor/ring for this exact build rendered as the same shiny/
    divine item-circle loadout the named-set path already produces, not a
    wall of build-brief text.

    Found live Sep 14, immediately after "attack huntress" stopped being
    misread as a literal item name (see
    stored_answers._shiny_divine_item_name's bare-stat-and-class guard):
    the message correctly stopped 404ing, but fell through to the generic
    balanced-loadout brief (weapon/ability/armor/ring paragraphs, a
    RealmShark loadouts table) instead of what "full shiny divine X"
    actually asked for - a set visualization, same as naming the four
    items directly would produce.
    """
    if not (class_name and stat):
        return False
    if extract_set_item_names(message):
        return False
    shiny, rarity = set_visualize_flags(message)
    return bool(shiny or rarity)


def _equipment_hubs(class_name: Optional[str]) -> list[tuple[str, str]]:
    hubs: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(slug: str, slot: str) -> None:
        if slug and slug not in seen:
            seen.add(slug)
            hubs.append((slug, slot))

    if class_name:
        weapon_hubs, _label = weapon_family(class_name)
        for slug in weapon_hubs:
            add(slug, "weapon")
        for classes, _weps, _label in WEAPON_FAMILIES:
            if class_name in classes:
                for sister in classes:
                    add(CLASS_ABILITY_HUB.get(sister, ""), "ability")
                break
        add(CLASS_ARMOR_HUB.get(class_name, ""), "armor")
    else:
        for _classes, weapon_hubs, _label in WEAPON_FAMILIES:
            for slug in weapon_hubs:
                add(slug, "weapon")
        for slug in CLASS_ABILITY_HUB.values():
            add(slug, "ability")
        for slug in set(CLASS_ARMOR_HUB.values()):
            add(slug, "armor")
    add(RINGS_HUB, "ring")
    return hubs


async def _read_hub(
    redis: aioredis.Redis,
    slug: str,
    ttl_seconds: int,
    *,
    allow_scrape: bool,
) -> list[dict]:
    if allow_scrape:
        try:
            return await _hub_index(redis, slug, ttl_seconds)
        except Exception as e:
            logger.bind(slug=slug, error=str(e)).warning(
                "Item alias hub unavailable"
            )
            return []
    raw = await redis.get(f"{HUB_PREFIX}:{slug}")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


async def load_item_catalog(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    class_name: Optional[str] = None,
    allow_scrape: bool = True,
) -> list[CatalogItem]:
    cache_key = (
        f"{CATALOG_PREFIX}:{(class_name or 'all').lower()}:"
        f"{'scrape' if allow_scrape else 'cached'}"
    )
    cached = await redis.get(cache_key)
    if cached:
        try:
            rows = json.loads(cached)
            return [
                CatalogItem(
                    name=row["name"],
                    slot=row["slot"],
                    aliases=frozenset(row["aliases"]),
                    hub=row.get("hub") or "",
                )
                for row in rows
            ]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    lock = _CATALOG_LOCKS.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = await redis.get(cache_key)
        if cached:
            try:
                rows = json.loads(cached)
                return [
                    CatalogItem(
                        name=row["name"],
                        slot=row["slot"],
                        aliases=frozenset(row["aliases"]),
                        hub=row.get("hub") or "",
                    )
                    for row in rows
                ]
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        catalog: list[CatalogItem] = []
        seen: set[str] = set()
        for slug, slot in _equipment_hubs(class_name):
            for row in await _read_hub(
                redis, slug, ttl_seconds, allow_scrape=allow_scrape
            ):
                name = (row.get("name") or "").strip()
                if not name or _SKIP_NAME.search(name) or _LE_CLONE.search(name):
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                catalog.append(catalog_item(name, slot, hub=slug))
        payload = [
            {
                "name": item.name,
                "slot": item.slot,
                "aliases": sorted(item.aliases),
                "hub": item.hub,
            }
            for item in catalog
        ]
        if payload:
            await redis.setex(cache_key, ttl_seconds, json.dumps(payload))
        return catalog


async def _skip_st_for_shiny(
    redis: aioredis.Redis,
    hit: str,
    *,
    query: str,
    catalog: list[CatalogItem],
) -> Optional[str]:
    item = await read_cached_item(redis, hit)
    if not item or not _is_st_item(item):
        return hit
    if _norm(query) == _norm(item.name):
        return None
    return await resolve_place_slot(redis, query, catalog, want_shiny=True)


async def resolve_item_query(
    redis: aioredis.Redis,
    query: str,
    *,
    ttl_seconds: int,
    class_name: Optional[str] = None,
    slot_hint: Optional[str] = None,
    allow_scrape: bool = True,
    prefer_shiny_ut: bool = False,
) -> Optional[str]:
    """Map a typed name or nickname to a wiki title."""
    raw = (query or "").strip()
    if not raw:
        return None
    community = community_canonical(raw)
    if community:
        return community

    catalog = await load_item_catalog(
        redis,
        ttl_seconds=ttl_seconds,
        class_name=class_name,
        allow_scrape=allow_scrape,
    )
    if not catalog and class_name:
        catalog = await load_item_catalog(
            redis,
            ttl_seconds=ttl_seconds,
            class_name=None,
            allow_scrape=False,
        )
    hit = resolve_against_catalog(raw, catalog, slot_hint=slot_hint)
    if not hit:
        cached = await read_cached_item(redis, raw)
        if cached:
            hit = cached.name
    if not hit:
        hit = await resolve_place_slot(
            redis, raw, catalog, want_shiny=prefer_shiny_ut
        )
    if hit:
        hit = await prefer_original_name(redis, hit, query=raw)
    if hit and prefer_shiny_ut:
        hit = await _skip_st_for_shiny(redis, hit, query=raw, catalog=catalog)
    if hit and hit.lower() != raw.lower():
        logger.bind(query=raw, canonical=hit, class_name=class_name).info(
            "Resolved item nickname"
        )
    return hit


# No real RotMG item name runs longer than this many words (the longest
# tiered names - "Ring of Transcendent Attack", "Staff of Ancient Antiquity"
# - top out around 4-5). Used as a final sanity ceiling below: past this
# length, a "name" is virtually certain to be leftover free text a
# regex-based extractor glued onto (or mistook for) a real item name, not an
# actual title RealmEye could ever have a page for.
MAX_PLAUSIBLE_ITEM_NAME_WORDS = 6


async def resolve_item_query_with_trim(
    redis: aioredis.Redis,
    query: str,
    *,
    ttl_seconds: int,
    class_name: Optional[str] = None,
    slot_hint: Optional[str] = None,
    min_words: int = 2,
    prefer_shiny_ut: bool = False,
) -> Optional[str]:
    """Like resolve_item_query, but when the full string doesn't resolve,
    retry against progressively shorter prefixes (drop one trailing word at
    a time) before giving up.

    This is the durable fix for a whole class of bug found live repeatedly
    on Sep 14: every regex-based extractor that pulls an "item name" out of
    free chat text (stored_answers._shiny_divine_item_name and friends)
    only knows where the name *starts*, not reliably where it *ends* - a
    trailing question with no clear punctuation/verb boundary
    ("...ring is the awakened enchantment good?") gets glued onto the real
    name no matter how many specific stop-words get added to those regexes
    one incident at a time. Real item names are a closed, known set (the
    item catalog, built from RealmEye's own hub/listing pages) - instead of
    guessing *which* trailing words are junk, this asks the catalog "does
    ANY prefix of this text name a real item," which needs no per-incident
    regex tuning: "snake eye ring is the awakened enchantment good" fails
    whole, then fails at 6 words, ... down to "snake eye ring" (3 words),
    which resolves cleanly because all three tokens are real words in a
    real catalog item's name - see score_nickname's `all(token in
    name_words ...)` scoring. Returns the canonical title for the longest
    resolving prefix, or None if nothing resolves even down to `min_words`.
    """
    raw = (query or "").strip()
    if not raw:
        return None
    community = community_canonical(raw)
    if community:
        return community

    catalog = await load_item_catalog(
        redis, ttl_seconds=ttl_seconds, class_name=class_name, allow_scrape=False
    )
    if not catalog and class_name:
        catalog = await load_item_catalog(
            redis, ttl_seconds=ttl_seconds, class_name=None, allow_scrape=False
        )
    if not catalog:
        return None

    words = raw.split()
    for end in range(len(words), max(min_words, 1) - 1, -1):
        candidate = " ".join(words[:end])
        if not candidate:
            continue
        hit = resolve_against_catalog(candidate, catalog, slot_hint=slot_hint)
        if hit and prefer_shiny_ut:
            hit = await _skip_st_for_shiny(
                redis, hit, query=candidate, catalog=catalog
            )
        if hit:
            if end != len(words):
                logger.bind(query=raw, trimmed_to=candidate, canonical=hit).info(
                    "Resolved item nickname by trimming trailing text"
                )
            return hit
    return None


async def retrieve_set_visualizer(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int,
    class_name: Optional[str] = None,
    stat: Optional[str] = None,
    allow_scrape: bool = True,
    forced_names: Optional[list[str]] = None,
    history: Optional[list[str]] = None,
) -> str:
    """Slot-agent report: nickname → [item:Wiki Title] for a named set, or
    (found live Sep 14, see is_stat_class_shiny_divine_query) the best
    weapon/ability/armor/ring for a class+stat build when no items are
    named at all - "show me full shiny divine attack huntress" gets the
    same item-circle loadout as naming all four items would, instead of a
    wall of build-brief text.
    """
    names = list(forced_names or [])
    derived_from_build = False
    if not names:
        names = extract_set_item_names(message)
    if not names:
        names = last_set_names_from_history(history)
    if not names and class_name and stat:
        shiny, rarity = set_visualize_flags(message)
        if shiny or rarity:
            picks = await top_build_items(
                redis, class_name, stat, ttl_seconds=ttl_seconds,
                cache_only=not allow_scrape,
            )
            names = [picks[slot] for slot in SET_SLOTS if slot in picks]
            derived_from_build = True
    if not names:
        return ""
    shiny, rarity = set_visualize_flags(message)
    flags = [part for part in (("shiny" if shiny else ""), rarity or "") if part]

    rows: list[tuple[str, str, Optional[str], str, str]] = []
    catalog: list[CatalogItem] = []
    if derived_from_build:
        # Already real wiki titles from top_build_items (read straight off
        # the warmed hub data) - resolving them again through the nickname
        # catalog would be redundant and risks a miss on an item the
        # catalog hasn't indexed under its exact wiki title yet.
        for i, name in enumerate(names):
            slot = SET_SLOTS[i] if i < len(SET_SLOTS) else "item"
            kind = _item_kind(None, slot, class_name)
            rows.append((name, slot, name, kind, item_wiki_url(name)))
    else:
        catalog = await load_item_catalog(
            redis,
            ttl_seconds=ttl_seconds,
            class_name=class_name,
            allow_scrape=allow_scrape,
        )
        if class_name and not any(item.hub for item in catalog):
            wider = await load_item_catalog(
                redis,
                ttl_seconds=ttl_seconds,
                class_name=None,
                allow_scrape=False,
            )
            if wider:
                catalog = wider
        for index, raw in enumerate(names):
            canonical = resolve_against_catalog(raw, catalog)
            item = _find_catalog_item(catalog, canonical)
            slot = (
                item.slot
                if item and item.slot in SET_SLOTS
                else SET_SLOTS[index] if index < len(SET_SLOTS) else "item"
            )
            kind = _item_kind(item, slot, class_name)
            title = canonical or raw
            url = item_wiki_url(title)
            try:
                profile = await read_cached_item(redis, title)
            except Exception:
                profile = None
            if profile:
                if profile.type:
                    kind = profile.type.strip().lower() or kind
                if profile.wiki_url:
                    url = profile.wiki_url
                if profile.name:
                    canonical = canonical or profile.name
            rows.append((raw, slot, canonical or raw, kind, url))

    by_slot: dict[str, str] = {}
    extras: list[str] = []
    for _raw, slot, canonical, _kind, _url in rows:
        if not canonical:
            continue
        if slot in SET_SLOTS and slot not in by_slot:
            by_slot[slot] = canonical
        elif canonical not in by_slot.values():
            extras.append(canonical)
    token_line = " ".join(
        f"[item:{by_slot[slot]}]" for slot in SET_SLOTS if slot in by_slot
    )
    if extras:
        token_line = (token_line + " " + " ".join(f"[item:{name}]" for name in extras)).strip()
    flag_token = " ".join(flags)
    if derived_from_build:
        lines = [
            "SET VISUALIZER. The user asked for the best build for "
            f"{stat} {class_name}, shown as a set (no items named "
            "directly) - these are the top weapon/ability/armor/ring for "
            "that build, already picked for you.",
            "Copy the flags and wiki titles below. Do not substitute other items.",
            "Keep the reply to a short confirmation naming each slot's item.",
            f"[loadout {flag_token}]".strip() if flag_token else "[loadout]",
            token_line,
            "Picked for this build:",
        ]
    else:
        lines = [
            "SET VISUALIZER. The user asked to show this exact named set.",
            "Copy the flags and wiki titles below. Do not substitute other items.",
            "Keep the reply to a short confirmation that uses each item's "
            "real wiki title and the slot kind listed (bow, lute, robe, "
            "ring). Never call a bow a sword. Crown means The Forgotten "
            "Crown. Cite the RealmEye wiki URLs below under Sources. Do "
            "not cite RealmShark; these sprites come from RealmEye.",
            f"[loadout {flag_token}]".strip() if flag_token else "[loadout]",
            token_line,
            "Resolved nicknames:",
        ]
    wiki_urls: list[str] = []
    for raw, slot, canonical, kind, url in rows:
        if canonical:
            lines.append(
                f"  {slot}: {raw} → [item:{canonical}] ({kind}). {url}"
            )
            wiki_urls.append(url)
        else:
            lines.append(
                f"  {slot}: {raw} → unresolved; do not guess a different item"
            )
    if wiki_urls:
        lines.append("RealmEye sources:")
        for url in dict.fromkeys(wiki_urls):
            lines.append(f"  {url}")
    if class_name:
        lines.append(
            f"Class context: {class_name}. Off-class abilities are allowed "
            "when the user named them (e.g. QOT on Huntress)."
        )
    return "\n".join(lines)
