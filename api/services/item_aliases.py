"""Resolve RotMG item nicknames to RealmEye wiki titles.

Players type QOT, Vest, Vile, Snake Ring, Lean — not the full wiki name.
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
from .wiki_scaling import HUB_PREFIX, _hub_index, _SKIP_NAME

SET_SLOT_COUNT = 4
SET_SLOTS = ("weapon", "ability", "armor", "ring")
CATALOG_PREFIX = "item:alias-catalog:v7"

# Overlay for names that are ambiguous, too short, or not in the title
# letters (Lean, Cult staff). Letter nicknames still generate from hubs.
COMMUNITY_ALIASES: dict[str, str] = {
    "lean": "Chrysalis of Eternity",
    "oreo": "Seal of Blasphemous Prayer",
    "tablet": "Tablet of the King's Avatar",
    "vest": "Vest of Abandoned Shadows",
    "vesture": "Vesture of Duality",
    "scythe": "Jailer's Scythe",
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
    "gem": "The Twilight Gemstone",
    "gemstone": "The Twilight Gemstone",
    "bracer": "Bracer of the Guardian",
    "poop sock": "Bracer of the Guardian",
    "poopsock": "Bracer of the Guardian",
    "banner": "Battalion Banner",
    "omni": "Omnipotence Ring",
    "kage": "Kagenohikari",
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
}

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

_SET_INTENT = re.compile(
    r"\b(?:set|loadout|build me|show me|visualize|equip(?:ped)?)\b",
    re.I,
)
_SHINY = re.compile(r"\b(?:all\s+)?shiny\b", re.I)
_DIVINE = re.compile(r"\b(?:all\s+)?divine\b", re.I)
_WITH_ITEMS = re.compile(r"\bwith\s+([\s\S]+?)(?:[.!?]|$)", re.I)
# "Full shiny divine A, B, C, and D" names a four-slot set without ever
# saying "with" - see extract_set_item_names' fallback below.
_AFTER_SHINY_DIVINE = re.compile(
    r"\b(?:all\s+)?(?:shiny\s+divine|divine\s+shiny|shiny|divine)\b\s+(.+?)(?:[.!?]|$)",
    re.I,
)
_LOOK_LIKE_TAIL = re.compile(r"\s+looks?\s+like\b.*$", re.I)
_NAME_SPLIT = re.compile(r",\s*(?:and\s+)?|\s+and\s+", re.I)
_SHINY_DIVINE_WORDS = re.compile(r"\b(?:all\s+)?(?:shiny|divine)\b", re.I)
_LEADING_AND = re.compile(r"^(?:and|&)\s+", re.I)
_CATALOG_LOCKS: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True)
class CatalogItem:
    name: str
    slot: str
    aliases: frozenset[str]


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


def catalog_item(name: str, slot: str) -> CatalogItem:
    return CatalogItem(name=name, slot=slot, aliases=generated_aliases(name))


def community_canonical(query: str) -> Optional[str]:
    key = _norm(query)
    for candidate in (key, _stem(key)):
        if candidate in COMMUNITY_ALIASES:
            return COMMUNITY_ALIASES[candidate]
    compact = _compact(query)
    for nick, canonical in COMMUNITY_ALIASES.items():
        if _compact(nick) == compact or _compact(nick) == _compact(_stem(key)):
            return canonical
    return None


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
        if q_tokens and all(token in name_words for token in q_tokens):
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
        cleaned = _LEADING_AND.sub("", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if 3 <= len(cleaned) <= 60:
            names.append(cleaned)
    if match is None and len(names) < 2:
        return []
    return names[:SET_SLOT_COUNT]


def is_set_visualize_query(message: str) -> bool:
    text = message or ""
    if not extract_set_item_names(text):
        return False
    shiny = bool(_SHINY.search(text))
    divine = bool(_DIVINE.search(text))
    wants_set = bool(_SET_INTENT.search(text))
    return bool((wants_set or (shiny and divine)) and (shiny or divine))


def set_visualize_flags(message: str) -> tuple[bool, bool]:
    text = message or ""
    return bool(_SHINY.search(text)), bool(_DIVINE.search(text))


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
                if not name or _SKIP_NAME.search(name):
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                catalog.append(catalog_item(name, slot))
        payload = [
            {
                "name": item.name,
                "slot": item.slot,
                "aliases": sorted(item.aliases),
            }
            for item in catalog
        ]
        if payload:
            await redis.setex(cache_key, ttl_seconds, json.dumps(payload))
        return catalog


async def resolve_item_query(
    redis: aioredis.Redis,
    query: str,
    *,
    ttl_seconds: int,
    class_name: Optional[str] = None,
    slot_hint: Optional[str] = None,
    allow_scrape: bool = True,
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
    if hit and hit.lower() != raw.lower():
        logger.bind(query=raw, canonical=hit, class_name=class_name).info(
            "Resolved item nickname"
        )
    return hit


async def retrieve_set_visualizer(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int,
    class_name: Optional[str] = None,
    allow_scrape: bool = True,
) -> str:
    """Slot-agent report: nickname → [item:Wiki Title] for a named set."""
    names = extract_set_item_names(message)
    if not names:
        return ""
    shiny, divine = set_visualize_flags(message)
    flags = [flag for flag, on in (("shiny", shiny), ("divine", divine)) if on]
    catalog = await load_item_catalog(
        redis,
        ttl_seconds=ttl_seconds,
        class_name=class_name,
        allow_scrape=allow_scrape,
    )
    resolved: list[tuple[str, str, Optional[str]]] = []
    for index, raw in enumerate(names):
        slot = SET_SLOTS[index] if index < len(SET_SLOTS) else None
        canonical = resolve_against_catalog(raw, catalog, slot_hint=slot)
        resolved.append((raw, slot or "item", canonical))

    token_line = " ".join(
        f"[item:{canonical}]" for _raw, _slot, canonical in resolved if canonical
    )
    flag_token = " ".join(flags)
    lines = [
        "SET VISUALIZER. The user asked to show this exact named set.",
        "Copy the flags and wiki titles below. Do not substitute other items.",
        "Keep the reply to a short confirmation.",
        f"[loadout {flag_token}]".strip() if flag_token else "[loadout]",
        token_line,
        "Resolved nicknames:",
    ]
    for raw, slot, canonical in resolved:
        if canonical:
            lines.append(f"  {slot}: {raw} → [item:{canonical}]")
        else:
            lines.append(
                f"  {slot}: {raw} → unresolved; do not guess a different item"
            )
    if class_name:
        lines.append(
            f"Class context: {class_name}. Off-class abilities are allowed "
            "when the user named them (e.g. QOT on Huntress)."
        )
    return "\n".join(lines)
