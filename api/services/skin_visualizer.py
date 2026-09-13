"""Skin / outfit visualizer specialist.

RealmEye's Top Characters with Outfit chooser is Class → Skin → Clothing →
Accessory. Player rows then composite the base skin with packed dye values:

  data-class / data-skin / data-dye1 / data-dye2
  data-clothing-dye-id / data-accessory-dye-id

drawCharacters() paints clothing onto the skin's clothing mask and accessory
onto the accessory mask. This specialist resolves those chooser names, runs
the same composite, and emits a [skin:...] token for the chat UI.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from ..models.build import CLASS_ALIASES
from ..models.skin import DyeChip, SkinPortrait
from .item_aliases import is_set_visualize_query
from .scraper import REALMEYE_BASE, ScraperError, composite_character_portrait, scrape_outfit_catalog

CATALOG_KEY = "outfit:catalog:v1"
PORTRAIT_PREFIX = "outfit:portrait:v1"
CATALOG_TTL = 7 * 24 * 3600

_CATALOG_LOCK = asyncio.Lock()
_PORTRAIT_LOCKS: dict[str, asyncio.Lock] = {}

_EXCLUDE = re.compile(
    r"\bskin count\b|\bhow many skins\b|\bskins?\s+armor\b|\bskin armor\b",
    re.I,
)
_VISUALIZER = re.compile(
    r"\b(?:skins?\s+visuali[sz]e|visuali[sz]e\s+(?:this\s+|the\s+|my\s+)?(?:skin|outfit)|"
    r"skin\s+visuali[sz]er?|outfit\s+visuali[sz]er?)\b",
    re.I,
)
_SHOW_SKIN = re.compile(
    r"\b(?:show|preview|render|wearing)\b.{0,120}\b(?:skin|outfit|dye|cloth)\b|"
    r"\b(?:skin|outfit)\b.{0,80}\b(?:with|clothing|accessory|dye|cloth)\b",
    re.I,
)
_LOOK_LIKE_WITH = re.compile(r"\blook\s+like\s+with\b", re.I)
_WHAT_DOES_LOOK = re.compile(
    r"\bwhat\s+does\s+(.+?)\s+look\s+like\s+"
    r"(?:with|if\s+i\s+(?:use|put|wear|add)\s+)(.+?)(?:[.!?]|$)",
    re.I,
)
_LOOK_LIKE = re.compile(r"\blook\s+like\b", re.I)
_USE_DYE = re.compile(
    r"\b(?:if\s+i\s+)?(?:use|put|wear|add|try)\b.{0,40}\b(?:cloth|dye)\b",
    re.I,
)
_UNRELATED_SKIN = re.compile(
    r"\b(?:where\s+(?:does|do)|drop\s+locations?|best\s+(?:bows?|items?)|guide\s+to)\b",
    re.I,
)
_PRONOUN_SKIN = re.compile(
    r"^(?:it|this|that|the\s+(?:skin|outfit)|what does it)$",
    re.I,
)
_CLOTH_OR_DYE = re.compile(
    r"\b(?:large|small)\s+\S.+\s+cloth\b|\b(?:clothing|accessory)\s+dye\b",
    re.I,
)
_LEAD_IN = re.compile(
    r"^\s*(?:please\s+)?(?:(?:can\s+i|could\s+you)\s+)?"
    r"(?:show(?:\s+me)?|see|visuali[sz]e|preview|render)\s+"
    r"(?:the\s+|this\s+|my\s+)?(?:skin|outfit)?\s*",
    re.I,
)
_COLOR = r"[a-z0-9]+(?:\s+[a-z0-9]+){0,4}"
_DYE_COLOR = (
    r"(?:(?!large\b)(?!small\b)(?!and\b)(?!cloth\b)[a-z0-9]+)"
    r"(?:\s+(?!large\b)(?!small\b)(?!and\b)(?!cloth\b)[a-z0-9]+){0,3}"
)
_LARGE_CLOTH = re.compile(
    rf"\b(large\s+(?!and\b)(?!small\b){_COLOR}\s+cloth)\b", re.I
)
_SMALL_CLOTH = re.compile(
    rf"\b(small\s+(?!and\b)(?!large\b){_COLOR}\s+cloth)\b", re.I
)
_CLOTHING_DYE = re.compile(rf"\b((?:large\s+|small\s+)?{_DYE_COLOR}\s+clothing dye)\b", re.I)
_ACCESSORY_DYE = re.compile(rf"\b((?:large\s+|small\s+)?{_DYE_COLOR}\s+accessory dye)\b", re.I)
_CLOTHING_LABEL = re.compile(
    r"\bclothing(?:\s+dye|\s+cloth)?\s*[:=]\s*([^,;|\n]+)", re.I
)
_ACCESSORY_LABEL = re.compile(
    r"\baccessory(?:\s+dye|\s+cloth)?\s*[:=]\s*([^,;|\n]+)", re.I
)
_WITH_CLAUSE = re.compile(r"\bwith\s+(.+?)(?:[.!?]|$)", re.I)
_NAME_SPLIT = re.compile(r",\s*(?:and\s+)?|\s+and\s+", re.I)
_NONE = re.compile(r"^(?:none|any|undyed|default)$", re.I)
_LEADING_JUNK = re.compile(r"^(?:and|&)\s+", re.I)
_TO_ACCESSORY = re.compile(
    r"\b(?:on|onto|as|to|for)\s+(?:the\s+)?accessory(?:\s+slot)?\b", re.I
)
_TO_CLOTHING = re.compile(
    r"\b(?:on|onto|as|to|for)\s+(?:the\s+)?clothing(?:\s+slot)?\b", re.I
)
_EXCHANGE_SLOTS = re.compile(
    r"\b(?:swap|switch|flip)(?:ped|ed)?\s+"
    r"(?:the\s+)?(?:large\s+and\s+small|small\s+and\s+large|"
    r"clothing\s+and\s+accessory|accessory\s+and\s+clothing|"
    r"cloths?\s+and\s+dyes?|dyes?\s+and\s+cloths?|"
    r"cloths?|dyes?|slots?|them|those)\b",
    re.I,
)
_OUTFIT_FOLLOWUP = re.compile(
    r"\b(?:instead|swap|switch|flip|same skin|same outfit|now with|"
    r"change (?:the )?(?:clothing|accessory|dye|cloth)|"
    r"(?:clothing|accessory) slot)\b",
    re.I,
)
_NOT_SKIN_NAME = re.compile(
    r"^(?:please\s+)?(?:now\s+)?(?:swap|switch|flip|instead)\b",
    re.I,
)
_SWAP_INTENT = re.compile(r"\b(?:now\s+)?(?:swap|switch|flip)(?:ped|ed)?\b", re.I)
_LARGE_CLOTH_NAME = re.compile(r"^large\s+(.+?)\s+cloth$", re.I)
_SMALL_CLOTH_NAME = re.compile(r"^small\s+(.+?)\s+cloth$", re.I)
_CLOTHING_DYE_NAME = re.compile(r"^(.+?)\s+clothing dye$", re.I)
_ACCESSORY_DYE_NAME = re.compile(r"^(.+?)\s+accessory dye$", re.I)
_BARE_DYE_NAME = re.compile(r"^(.+?)\s+dye$", re.I)
_BARE_SIZE_DYE = re.compile(rf"\b((?:large|small)\s+{_DYE_COLOR}\s+dye)\b", re.I)
_BARE_DYE = re.compile(rf"\b((?:large\s+|small\s+)?{_DYE_COLOR}\s+dye)\b", re.I)
_PAIRED_SIZE_CLOTH = re.compile(
    r"\b(?:large\s+and\s+small|small\s+and\s+large)\s+(.+?)\s+(cloths?|dyes?)\b",
    re.I,
)
_DYE_THEN_SLOT = re.compile(
    rf"\b((?:large\s+|small\s+)?{_DYE_COLOR}\s+dye)\s+"
    r"(?:on\s+(?:the\s+)?)?(?:the\s+)?(clothing|accessory)\b",
    re.I,
)
_ON_THE_OTHER = re.compile(
    r"\b(?:on|onto|as|to|for)\s+(?:the\s+)?(?:other|opposite)(?:\s+(?:slot|one|cloth|dye))?\b",
    re.I,
)
_AMBIGUOUS_CLOTH = re.compile(
    rf"\b((?!large\b)(?!small\b)(?!the\b)(?!and\b){_COLOR}\s+cloth)\b", re.I
)
_FOLLOWUP_INTENT = re.compile(
    r"\b(?:let me see|show me|can i see|i want to see|how about|what about|"
    r"try(?:\s+it)?|now(?:\s+with)?|also)\b",
    re.I,
)
_SEE_WITH = re.compile(
    r"\b(?:let me see|show me|can i see|i want to see|how about|what about)\b"
    r"(?:\s+with)?\s+(.+?)(?:[.!?]|$)",
    re.I,
)
_SKIN_TOKEN = re.compile(
    r"\[skin:([^|\]]+)\|([^|\]]*)\|([^|\]]*)\|([^|\]]*)\]", re.I
)
_LEADING_SIZE = re.compile(r"^(?:large|small)\s+", re.I)


@dataclass
class OutfitQuery:
    class_name: Optional[str]
    skin_name: Optional[str]
    clothing: Optional[str]
    accessory: Optional[str]
    other_slot: Optional[str] = None


def is_skin_visualize_query(message: str, history: Optional[list[str]] = None) -> bool:
    if is_set_visualize_query(message):
        return False
    text = message or ""
    if _EXCLUDE.search(text):
        return False
    if _VISUALIZER.search(text):
        return True
    if _SHOW_SKIN.search(text):
        return True
    if _WHAT_DOES_LOOK.search(text):
        return True
    if _LOOK_LIKE.search(text) and re.search(
        r"\b(?:cloth|dye|clothing|accessory)\b", text, re.I
    ):
        return True
    if _LOOK_LIKE_WITH.search(text) and re.search(
        r"\b(?:cloth|dye|clothing|accessory)\b", text, re.I
    ):
        return True
    if _EXCHANGE_SLOTS.search(text) and re.search(
        r"\b(?:cloth|dye|clothing|accessory|skin|outfit)\b", text, re.I
    ):
        return True
    if _CLOTH_OR_DYE.search(text) and re.search(
        r"\b(?:show|visuali[sz]e|preview|skin|outfit|dye)\b", text, re.I
    ):
        return True
    if history and _history_has_outfit(history) and not _UNRELATED_SKIN.search(text):
        if _is_slot_swap(text):
            return True
        if _mentions_outfit_piece(text) and (
            _OUTFIT_FOLLOWUP.search(text)
            or _FOLLOWUP_INTENT.search(text)
            or _SEE_WITH.search(text)
            or _LOOK_LIKE.search(text)
            or _USE_DYE.search(text)
            or _TO_ACCESSORY.search(text)
            or _TO_CLOTHING.search(text)
            or _DYE_THEN_SLOT.search(text)
            or not _looks_like_skin(_extract_outfit_from_text(text).skin_name)
        ):
            return True
    return False


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _class_from_text(text: str) -> Optional[str]:
    lower = (text or "").lower()
    hits: list[str] = []
    for canon, aliases in CLASS_ALIASES.items():
        needles = (canon.lower(),) + tuple(aliases)
        if any(re.search(rf"\b{re.escape(n)}\b", lower) for n in needles):
            hits.append(canon)
    return hits[0] if len(hits) == 1 else None


def _clean_dye(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip(" -:|,.")
    if not text or _NONE.match(text):
        return None
    return text


def _looks_like_skin(name: Optional[str]) -> bool:
    text = (name or "").strip()
    if len(text) < 3:
        return False
    if (
        _NOT_SKIN_NAME.search(text)
        or _EXCHANGE_SLOTS.search(text)
        or _SWAP_INTENT.search(text)
    ):
        return False
    if re.fullmatch(
        r"(?:on|onto|the|slot|with|and|a|an|to|for|as|it|this|that|"
        r"clothing|accessory|cloth|dye|large|small|\s)+",
        text,
        re.I,
    ):
        return False
    if _PRONOUN_SKIN.search(text):
        return False
    if re.search(r"\b(?:what does|look like|if i (?:use|put|wear|add))\b", text, re.I):
        return False
    return True


def _merge_outfit(base: OutfitQuery, overlay: OutfitQuery) -> OutfitQuery:
    skin = overlay.skin_name if _looks_like_skin(overlay.skin_name) else base.skin_name
    return OutfitQuery(
        class_name=overlay.class_name or base.class_name,
        skin_name=skin or base.skin_name,
        clothing=overlay.clothing if overlay.clothing is not None else base.clothing,
        accessory=overlay.accessory if overlay.accessory is not None else base.accessory,
    )


def _outfit_from_skin_token(text: str) -> Optional[OutfitQuery]:
    match = _SKIN_TOKEN.search(text or "")
    if not match:
        return None
    clothing = _clean_dye(match.group(3).strip()) if match.group(3).strip() else None
    accessory = _clean_dye(match.group(4).strip()) if match.group(4).strip() else None
    return OutfitQuery(
        class_name=match.group(1).strip() or None,
        skin_name=match.group(2).strip() or None,
        clothing=clothing,
        accessory=accessory,
    )


def _history_has_outfit(history: list[str]) -> bool:
    for prev in history:
        if _outfit_from_skin_token(prev):
            return True
        prior = _extract_outfit_from_text(prev)
        if prior.skin_name or prior.class_name:
            return True
    return False


def _mentions_outfit_piece(text: str) -> bool:
    if re.search(r"\b(?:cloth|dye|clothing|accessory)s?\b", text or "", re.I):
        return True
    if _ON_THE_OTHER.search(text or ""):
        return True
    if _BARE_SIZE_DYE.search(text or "") or _BARE_DYE.search(text or ""):
        return True
    if _AMBIGUOUS_CLOTH.search(text or ""):
        return True
    return False


def _normalize_ambiguous_cloth(part: str) -> str:
    text = (part or "").strip()
    if re.search(r"\b(?:large|small)\b", text, re.I):
        return text
    match = _AMBIGUOUS_CLOTH.search(text)
    if match:
        return f"Large {match.group(1).strip()}"
    return text


def _assign_size_dye(
    part: str,
    *,
    clothing: Optional[str],
    accessory: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    text = (part or "").strip()
    if not text:
        return clothing, accessory
    if re.match(r"^large\b", text, re.I):
        return clothing or text, accessory
    if re.match(r"^small\b", text, re.I):
        return clothing, accessory or text
    return clothing, accessory


def _parse_cloth_accessory(
    with_part: str,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    text = (with_part or "").strip()
    if _is_slot_swap(text):
        return None, None, None
    if _SWAP_INTENT.search(text) and not (
        _BARE_DYE.search(text)
        or _LARGE_CLOTH.search(text)
        or _SMALL_CLOTH.search(text)
        or _AMBIGUOUS_CLOTH.search(text)
        or _CLOTHING_DYE.search(text)
        or _ACCESSORY_DYE.search(text)
        or _PAIRED_SIZE_CLOTH.search(text)
    ):
        return None, None, None
    paired = _PAIRED_SIZE_CLOTH.search(text)
    if paired:
        color = paired.group(1).strip()
        kind = "dye" if paired.group(2).lower().startswith("dye") else "cloth"
        return f"Large {color} {kind}", f"Small {color} {kind}", None

    slot_dye = _DYE_THEN_SLOT.search(text)
    if slot_dye:
        dye = slot_dye.group(1).strip()
        if slot_dye.group(2).lower() == "accessory":
            return None, dye, None
        return dye, None, None

    on_other = bool(_ON_THE_OTHER.search(text))
    if on_other:
        text = _ON_THE_OTHER.sub("", text)
        text = re.sub(r"\s+", " ", text).strip(" -:|,.")

    clothing = None
    accessory = None
    large = _LARGE_CLOTH.search(text)
    small = _SMALL_CLOTH.search(text)
    c_dye = _CLOTHING_DYE.search(text)
    a_dye = _ACCESSORY_DYE.search(text)
    c_label = _CLOTHING_LABEL.search(text)
    a_label = _ACCESSORY_LABEL.search(text)
    to_accessory = bool(_TO_ACCESSORY.search(text))
    to_clothing = bool(_TO_CLOTHING.search(text))

    if large:
        if to_accessory and not to_clothing:
            accessory = large.group(1).strip()
        else:
            clothing = large.group(1).strip()
    elif c_dye:
        clothing = c_dye.group(1).strip()
    elif c_label:
        clothing = c_label.group(1).strip()

    if small:
        if to_clothing and not to_accessory:
            clothing = clothing or small.group(1).strip()
        else:
            accessory = accessory or small.group(1).strip()
    elif a_dye:
        accessory = accessory or a_dye.group(1).strip()
    elif a_label:
        accessory = accessory or a_label.group(1).strip()

    bare = _BARE_DYE.search(text) or _BARE_SIZE_DYE.search(text)
    if bare:
        clothing, accessory = _assign_size_dye(
            bare.group(1).strip(), clothing=clothing, accessory=accessory
        )
        if not clothing and not accessory:
            clothing = bare.group(1).strip()

    amb = _AMBIGUOUS_CLOTH.search(text)
    if amb and not clothing and not accessory:
        clothing = _normalize_ambiguous_cloth(amb.group(1).strip())

    if not clothing and not accessory:
        parts = [
            _LEADING_JUNK.sub("", p).strip()
            for p in _NAME_SPLIT.split(text)
        ]
        parts = [p for p in parts if 2 <= len(p) <= 60]
        for part in parts:
            if _NONE.match(part):
                continue
            if not clothing and re.search(r"\b(?:large|clothing)\b", part, re.I):
                clothing = _normalize_ambiguous_cloth(part)
            elif not accessory and re.search(r"\b(?:small|accessory)\b", part, re.I):
                accessory = part
            elif not clothing:
                clothing = _normalize_ambiguous_cloth(part)
            elif not accessory:
                accessory = part

    if on_other:
        return None, None, _clean_dye(clothing or accessory)
    return _clean_dye(clothing), _clean_dye(accessory), None


def _extract_outfit_from_text(message: str, class_name: Optional[str] = None) -> OutfitQuery:
    text = (message or "").strip()
    see = _SEE_WITH.search(text)
    if see:
        clothing, accessory, other = _parse_cloth_accessory(see.group(1).strip())
        if clothing or accessory or other:
            return OutfitQuery(
                class_name=None,
                skin_name=None,
                clothing=clothing,
                accessory=accessory,
                other_slot=other,
            )

    what = _WHAT_DOES_LOOK.search(text)
    if what:
        skin_part = what.group(1).strip()
        with_part = what.group(2).strip()
        clothing, accessory, other = _parse_cloth_accessory(with_part)
        if _PRONOUN_SKIN.search(skin_part):
            return OutfitQuery(
                class_name=None,
                skin_name=None,
                clothing=clothing,
                accessory=accessory,
                other_slot=other,
            )
        class_hit = class_name or _class_from_text(skin_part) or _class_from_text(text)
        skin = skin_part
        if class_hit:
            skin = re.sub(rf"\b{re.escape(class_hit)}\b", " ", skin, flags=re.I)
            skin = re.sub(r"\s+", " ", skin).strip(" -:|,.")
        if not _looks_like_skin(skin):
            skin = None
        return OutfitQuery(
            class_name=class_hit,
            skin_name=skin,
            clothing=clothing,
            accessory=accessory,
            other_slot=other,
        )

    clothing, accessory, other = _parse_cloth_accessory(text)
    with_m = _WITH_CLAUSE.search(text)
    rest = text
    if with_m:
        rest = rest[: with_m.start()] + rest[with_m.end() :]
    for label in (clothing, accessory):
        if label:
            rest = re.sub(re.escape(label), " ", rest, flags=re.I)
    rest = _LEAD_IN.sub("", rest)
    rest = re.sub(
        r"\b(?:skin|outfit|visuali[sz]er?|preview|clothing|accessory|dye|cloth)\b",
        " ",
        rest,
        flags=re.I,
    )
    rest = re.sub(r"\s+", " ", rest).strip(" -:|,.")

    class_hit = class_name or _class_from_text(text) or _class_from_text(rest)
    skin = rest
    if class_hit:
        skin = re.sub(rf"\b{re.escape(class_hit)}\b", " ", skin, flags=re.I)
        skin = re.sub(r"\s+", " ", skin).strip(" -:|,.")
        if not skin:
            skin = rest
    if not skin or len(skin) < 3:
        skin = rest or None
    if not _looks_like_skin(skin):
        skin = None
    return OutfitQuery(
        class_name=class_hit,
        skin_name=skin,
        clothing=clothing,
        accessory=accessory,
        other_slot=other,
    )


def _has_size_or_slot(label: Optional[str]) -> bool:
    return bool(re.search(r"\b(?:large|small|clothing|accessory)\b", label or "", re.I))


def _place_followup_slots(prior: OutfitQuery, current: OutfitQuery) -> OutfitQuery:
    clothing = current.clothing
    accessory = current.accessory
    other = current.other_slot
    if other:
        if prior.clothing and not prior.accessory:
            accessory = other
            clothing = None
        elif prior.accessory and not prior.clothing:
            clothing = other
            accessory = None
        elif prior.clothing:
            accessory = other
            clothing = None
        else:
            clothing = other
    elif (
        clothing
        and not accessory
        and not _has_size_or_slot(clothing)
        and prior.clothing
        and not prior.accessory
    ):
        accessory = clothing
        clothing = None
    return _merge_outfit(
        prior,
        OutfitQuery(
            class_name=current.class_name,
            skin_name=current.skin_name,
            clothing=clothing,
            accessory=accessory,
        ),
    )


def _names_a_new_dye(text: str) -> bool:
    return bool(
        _BARE_DYE.search(text)
        or _LARGE_CLOTH.search(text)
        or _SMALL_CLOTH.search(text)
        or _AMBIGUOUS_CLOTH.search(text)
        or _CLOTHING_DYE.search(text)
        or _ACCESSORY_DYE.search(text)
        or _PAIRED_SIZE_CLOTH.search(text)
    )


def _is_slot_swap(message: str) -> bool:
    text = message or ""
    if not _SWAP_INTENT.search(text):
        return False
    if _EXCHANGE_SLOTS.search(text):
        return True
    return not _names_a_new_dye(text)


def _is_outfit_followup(
    message: str,
    current: OutfitQuery,
    history: Optional[list[str]],
) -> bool:
    if _OUTFIT_FOLLOWUP.search(message or "") or _is_slot_swap(message or ""):
        return True
    if not history or not _history_has_outfit(history):
        return False
    piece = bool(
        current.clothing
        or current.accessory
        or current.other_slot
        or _mentions_outfit_piece(message or "")
    )
    if (
        _FOLLOWUP_INTENT.search(message or "")
        or _SEE_WITH.search(message or "")
        or _LOOK_LIKE.search(message or "")
        or _USE_DYE.search(message or "")
    ):
        return piece
    if not current.skin_name and not current.class_name:
        return piece
    return False


def _swap_slot_label(name: Optional[str], target: str) -> Optional[str]:
    """Large cloth becomes Small cloth on accessory, and dyes follow the slot."""
    if not name:
        return None
    color = _color_from_dye_query(name)
    if not color:
        return name
    if re.search(r"\bcloth\b", name, re.I):
        if target == "accessory":
            return f"Small {color} Cloth"
        return f"Large {color} Cloth"
    if target == "accessory":
        return f"{color} Accessory Dye"
    return f"{color} Clothing Dye"


def extract_outfit_query(
    message: str,
    class_name: Optional[str] = None,
    history: Optional[list[str]] = None,
) -> OutfitQuery:
    current = _extract_outfit_from_text(message, class_name)
    followup = _is_outfit_followup(message, current, history)
    merged = current
    if followup and history:
        prior = OutfitQuery(class_name, None, None, None)
        for prev in history:
            token = _outfit_from_skin_token(prev)
            if token:
                prior = _merge_outfit(prior, token)
            else:
                prior = _merge_outfit(prior, _extract_outfit_from_text(prev, class_name))
        merged = _place_followup_slots(prior, current)
    if _is_slot_swap(message or ""):
        return OutfitQuery(
            class_name=merged.class_name,
            skin_name=merged.skin_name,
            clothing=_swap_slot_label(merged.accessory, "clothing"),
            accessory=_swap_slot_label(merged.clothing, "accessory"),
        )
    return merged


def _score_name(query: str, name: str) -> int:
    q = _norm(query)
    n = _norm(name)
    if not q or not n:
        return 0
    if q == n:
        return 120
    if n.startswith(q) or q.startswith(n):
        return 95
    if q in n:
        return 85 + min(len(q), 20)
    if n in q:
        return 80
    stop = {"the", "of", "a", "large", "small", "cloth", "dye", "clothing", "accessory"}
    qtoks = [t for t in q.split() if t not in stop]
    ntoks = [t for t in n.split() if t not in stop]
    all_q = [t for t in q.split() if t not in {"the", "of", "a"}]
    all_n = [t for t in n.split() if t not in {"the", "of", "a"}]
    if not all_q:
        return 0
    overlap = sum(
        1
        for t in all_q
        if any(nt == t or nt.startswith(t) or t.startswith(nt) for nt in all_n)
    )
    score = int(60 * overlap / len(all_q))
    missing = [
        t
        for t in qtoks
        if not any(nt == t or nt.startswith(t) or t.startswith(nt) for nt in ntoks)
    ]
    score -= 30 * len(missing)
    extra = [
        t
        for t in ntoks
        if not any(qt == t or qt.startswith(t) or t.startswith(qt) for qt in qtoks)
    ]
    score -= 8 * len(extra)
    return score


def _pick_name(query: Optional[str], names: list[str], *, extra_bonus: Optional[str] = None) -> Optional[str]:
    if not query or not names:
        return None
    ranked: list[tuple[int, str]] = []
    for name in names:
        score = _score_name(query, name)
        if extra_bonus and extra_bonus.lower() in name.lower():
            score += 8
        ranked.append((score, name))
    ranked.sort(key=lambda row: (-row[0], len(row[1]), row[1].lower()))
    if not ranked or ranked[0][0] < 50:
        return None
    return ranked[0][1]


async def load_outfit_catalog(
    redis: aioredis.Redis, *, ttl_seconds: int, cache_only: bool = False
) -> dict:
    cached = await redis.get(CATALOG_KEY)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass
    if cache_only:
        return {"classes": [], "clothing": [], "accessory": []}
    async with _CATALOG_LOCK:
        cached = await redis.get(CATALOG_KEY)
        if cached:
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                pass
        catalog = await scrape_outfit_catalog()
        await redis.setex(CATALOG_KEY, max(ttl_seconds, CATALOG_TTL), json.dumps(catalog))
        return catalog


def _dye_chip(row: Optional[dict]) -> Optional[DyeChip]:
    if not row:
        return None
    return DyeChip(
        name=row["name"],
        item_id=int(row.get("id") or 0),
        sprite_sheet_url=row.get("sprite_sheet_url"),
        sprite_x=row.get("sprite_x"),
        sprite_y=row.get("sprite_y"),
        sprite_size=48,
    )


def _resolve_class_skin(
    catalog: dict,
    class_query: Optional[str],
    skin_query: Optional[str],
) -> tuple[dict, dict]:
    classes = catalog.get("classes") or []
    class_row = None
    if class_query:
        name = _pick_name(class_query, [c["name"] for c in classes])
        class_row = next((c for c in classes if c["name"] == name), None)
    if class_row is None and skin_query:
        # Skin titles often end with the class ("Mini Royal Crossbowman Archer").
        name = _class_from_text(skin_query)
        if name:
            class_row = next((c for c in classes if c["name"] == name), None)
    if class_row is None and skin_query:
        best: tuple[int, dict, dict] | None = None
        for cls in classes:
            for skin in cls.get("skins") or []:
                score = _score_name(skin_query, skin["name"])
                if best is None or score > best[0]:
                    best = (score, cls, skin)
        if best and best[0] >= 70:
            return best[1], best[2]
    if class_row is None:
        raise ScraperError("Could not tell which class that skin belongs to")

    skins = class_row.get("skins") or []
    skin_names = [s["name"] for s in skins]
    picked = _pick_name(skin_query, skin_names) if skin_query else None
    if picked is None and skin_query and class_row["name"].lower() not in _norm(skin_query):
        picked = _pick_name(f"{skin_query} {class_row['name']}", skin_names)
    if picked is None:
        # Default / Classic skin is id 0, first in the chooser list.
        skin_row = next((s for s in skins if s.get("id") == 0), skins[0] if skins else None)
    else:
        skin_row = next((s for s in skins if s["name"] == picked), None)
    if not skin_row:
        raise ScraperError(f"No skins listed for {class_row['name']}")
    return class_row, skin_row


def _color_from_dye_query(raw: str) -> str:
    text = (raw or "").strip()
    for pat in (
        _LARGE_CLOTH_NAME,
        _SMALL_CLOTH_NAME,
        _CLOTHING_DYE_NAME,
        _ACCESSORY_DYE_NAME,
        _BARE_DYE_NAME,
    ):
        match = pat.match(text)
        if match:
            text = match.group(1).strip()
            break
    return _LEADING_SIZE.sub("", text).strip() or raw.strip()


def _dye_queries(query: str, slot: str) -> list[str]:
    """Map Large/Small cloth and Clothing/Accessory dye onto the requested slot."""
    raw = (query or "").strip()
    if not raw:
        return []
    color = _color_from_dye_query(raw)
    if slot == "clothing":
        variants = [
            raw,
            f"Large {color} Cloth",
            f"{color} Clothing Dye",
            f"{color} Dye",
        ]
    else:
        variants = [
            raw,
            f"Small {color} Cloth",
            f"{color} Accessory Dye",
            f"{color} Dye",
        ]
    seen: set[str] = set()
    out: list[str] = []
    for item in variants:
        key = _norm(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _resolve_dye(query: Optional[str], rows: list[dict], slot: str) -> Optional[dict]:
    if not query or _NONE.match(query.strip()):
        return None
    names = [r["name"] for r in rows]
    picked = None
    best = -1
    for variant in _dye_queries(query, slot):
        hit = _pick_name(variant, names)
        if not hit:
            continue
        score = _score_name(variant, hit)
        if score > best:
            best = score
            picked = hit
    if not picked:
        return None
    return next((r for r in rows if r["name"] == picked), None)


def _portrait_key(class_id: int, skin_id: int, clothing_id: int, accessory_id: int) -> str:
    return f"{PORTRAIT_PREFIX}:{class_id}:{skin_id}:{clothing_id}:{accessory_id}"


def _outfit_url(class_id: int, skin_id: int, clothing_id: int, accessory_id: int) -> str:
    cloth = clothing_id or ""
    acc = accessory_id or ""
    return f"{REALMEYE_BASE}/top-characters-with-outfit/{class_id}/{skin_id}/{cloth}/{acc}"


async def render_skin_portrait(
    redis: aioredis.Redis,
    *,
    class_name: Optional[str],
    skin_name: Optional[str],
    clothing: Optional[str],
    accessory: Optional[str],
    ttl_seconds: int,
    cache_only: bool = False,
) -> SkinPortrait:
    catalog = await load_outfit_catalog(
        redis, ttl_seconds=ttl_seconds, cache_only=cache_only
    )
    class_row, skin_row = _resolve_class_skin(catalog, class_name, skin_name)
    clothing_row = _resolve_dye(clothing, catalog.get("clothing") or [], "clothing")
    accessory_row = _resolve_dye(accessory, catalog.get("accessory") or [], "accessory")
    class_id = int(class_row["id"])
    skin_id = int(skin_row["id"] or 0)
    clothing_id = int((clothing_row or {}).get("id") or 0)
    accessory_id = int((accessory_row or {}).get("id") or 0)

    cache_key = _portrait_key(class_id, skin_id, clothing_id, accessory_id)
    cached = await redis.get(cache_key)
    if cached:
        return SkinPortrait.model_validate_json(cached)

    lock = _PORTRAIT_LOCKS.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = await redis.get(cache_key)
        if cached:
            return SkinPortrait.model_validate_json(cached)
        data_uri = await composite_character_portrait(
            class_id, skin_id, clothing_id, accessory_id
        )
        portrait = SkinPortrait(
            class_name=class_row["name"],
            class_id=class_id,
            skin_name=skin_row["name"],
            skin_id=skin_id,
            clothing=_dye_chip(clothing_row),
            accessory=_dye_chip(accessory_row),
            portrait_data_uri=data_uri,
            realmeye_url=_outfit_url(class_id, skin_id, clothing_id, accessory_id),
        )
        await redis.setex(
            cache_key, max(ttl_seconds, CATALOG_TTL), portrait.model_dump_json()
        )
        return portrait


def _skin_token(portrait: SkinPortrait) -> str:
    clothing = (portrait.clothing.name if portrait.clothing else "") or ""
    accessory = (portrait.accessory.name if portrait.accessory else "") or ""
    return (
        f"[skin:{portrait.class_name}|{portrait.skin_name}|{clothing}|{accessory}]"
    )


def outfit_history_from_messages(messages: list) -> list[str]:
    """User turns plus assistant [skin:...] replies for outfit follow-ups."""
    lines: list[str] = []
    for msg in messages:
        role = getattr(msg, "role", None)
        content = getattr(msg, "content", None) or ""
        if role == "user":
            lines.append(content)
        elif role == "assistant" and "[skin:" in content:
            lines.append(content)
    return lines


async def retrieve_skin_visualizer(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int,
    class_name: Optional[str] = None,
    history: Optional[list[str]] = None,
) -> str:
    query = extract_outfit_query(message, class_name, history)
    if not query.skin_name and not query.class_name:
        return ""
    try:
        portrait = await render_skin_portrait(
            redis,
            class_name=query.class_name or class_name,
            skin_name=query.skin_name,
            clothing=query.clothing,
            accessory=query.accessory,
            ttl_seconds=ttl_seconds,
            cache_only=False,
        )
    except Exception as e:
        logger.bind(error=str(e), skin=query.skin_name).warning(
            "Skin visualizer could not composite that outfit"
        )
        return (
            "SKIN VISUALIZER. Could not render that outfit. Ask the user for "
            "the class, skin name, and optional clothing/accessory dye or cloth."
        )

    clothing_label = portrait.clothing.name if portrait.clothing else "None"
    accessory_label = portrait.accessory.name if portrait.accessory else "None"
    return "\n".join(
        [
            "SKIN VISUALIZER. Copy the [skin:...] token exactly. Short confirmation only.",
            "Do not emit [item:] tokens for the dyes. The UI paints the portrait.",
            _skin_token(portrait),
            f"Class: {portrait.class_name}",
            f"Skin: {portrait.skin_name}",
            f"Clothing: {clothing_label}",
            f"Accessory: {accessory_label}",
            f"RealmEye: {portrait.realmeye_url}",
        ]
    )


SKIN_OK_TEXT = (
    "Composited from RealmEye sprites. Class skin plus clothing and accessory "
    "dyes. That render is code, not a model guess. Ask if you want a different "
    "cloth or dye combo."
)


def _skin_failure_text(query: OutfitQuery) -> str:
    parts: list[str] = []
    if query.skin_name:
        parts.append(f"skin **{query.skin_name}**")
    if query.class_name:
        parts.append(f"class **{query.class_name}**")
    if query.clothing:
        parts.append(f"clothing **{query.clothing}**")
    if query.accessory:
        parts.append(f"accessory **{query.accessory}**")
    detail = ", ".join(parts) if parts else "that outfit"
    return (
        f"I couldn't render {detail} from RealmEye. "
        "Double-check the spellings against the wiki skin and cloth names."
    )


async def compose_skin_stored_reply(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int,
    history: Optional[list[str]] = None,
) -> str:
    """Render the outfit and return a stored chat reply with a [skin:...] token."""
    query = extract_outfit_query(message, history=history)
    if not query.skin_name and not query.class_name:
        return (
            "I need a class skin name and optional cloth or dye. "
            "Try: What does Vampire Slayer Archer look like with Large Crown cloth?"
        )
    try:
        portrait = await render_skin_portrait(
            redis,
            class_name=query.class_name,
            skin_name=query.skin_name,
            clothing=query.clothing,
            accessory=query.accessory,
            ttl_seconds=ttl_seconds,
            cache_only=False,
        )
    except Exception as e:
        logger.bind(error=str(e), skin=query.skin_name).warning(
            "Skin stored reply could not render outfit"
        )
        return _skin_failure_text(query)
    return f"{_skin_token(portrait)}\n\n{SKIN_OK_TEXT}"
