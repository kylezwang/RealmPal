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
    r"^(?:please\s+)?(?:swap|switch|flip|instead)\b", re.I
)
_LARGE_CLOTH_NAME = re.compile(r"^large\s+(.+?)\s+cloth$", re.I)
_SMALL_CLOTH_NAME = re.compile(r"^small\s+(.+?)\s+cloth$", re.I)
_CLOTHING_DYE_NAME = re.compile(r"^(.+?)\s+clothing dye$", re.I)
_ACCESSORY_DYE_NAME = re.compile(r"^(.+?)\s+accessory dye$", re.I)
_BARE_DYE_NAME = re.compile(r"^(.+?)\s+dye$", re.I)
_LEADING_SIZE = re.compile(r"^(?:large|small)\s+", re.I)


@dataclass
class OutfitQuery:
    class_name: Optional[str]
    skin_name: Optional[str]
    clothing: Optional[str]
    accessory: Optional[str]


def is_skin_visualize_query(message: str) -> bool:
    if is_set_visualize_query(message):
        return False
    text = message or ""
    if _EXCLUDE.search(text):
        return False
    if _VISUALIZER.search(text):
        return True
    if _SHOW_SKIN.search(text):
        return True
    if _EXCHANGE_SLOTS.search(text) and re.search(
        r"\b(?:cloth|dye|clothing|accessory|skin|outfit)\b", text, re.I
    ):
        return True
    if _CLOTH_OR_DYE.search(text) and re.search(
        r"\b(?:show|visuali[sz]e|preview|skin|outfit|dye)\b", text, re.I
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
    if _NOT_SKIN_NAME.search(text) or _EXCHANGE_SLOTS.search(text):
        return False
    if re.fullmatch(r"(?:on|onto|the|slot|with|and|a|an|to|for|as|\s)+", text, re.I):
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


def _extract_outfit_from_text(message: str, class_name: Optional[str] = None) -> OutfitQuery:
    text = (message or "").strip()
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

    with_m = _WITH_CLAUSE.search(text)
    if with_m and (not clothing or not accessory):
        parts = [
            _LEADING_JUNK.sub("", p).strip()
            for p in _NAME_SPLIT.split(with_m.group(1))
        ]
        parts = [p for p in parts if 2 <= len(p) <= 60]
        for part in parts:
            if _NONE.match(part):
                continue
            if not clothing and re.search(r"\b(?:large|clothing)\b", part, re.I):
                clothing = part
            elif not accessory and re.search(r"\b(?:small|accessory)\b", part, re.I):
                accessory = part
            elif not clothing:
                clothing = part
            elif not accessory:
                accessory = part

    rest = text
    if with_m:
        rest = rest[: with_m.start()] + rest[with_m.end() :]
    for match in (large, small, c_dye, a_dye, c_label, a_label):
        if match:
            rest = rest.replace(match.group(0), " ")
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
        clothing=_clean_dye(clothing),
        accessory=_clean_dye(accessory),
    )


def extract_outfit_query(
    message: str,
    class_name: Optional[str] = None,
    history: Optional[list[str]] = None,
) -> OutfitQuery:
    current = _extract_outfit_from_text(message, class_name)
    followup = bool(_OUTFIT_FOLLOWUP.search(message or ""))
    merged = current
    if followup and history:
        prior = OutfitQuery(class_name, None, None, None)
        for prev in history:
            prior = _merge_outfit(prior, _extract_outfit_from_text(prev, class_name))
        merged = _merge_outfit(prior, current)
    if _EXCHANGE_SLOTS.search(message or ""):
        return OutfitQuery(
            class_name=merged.class_name,
            skin_name=merged.skin_name,
            clothing=merged.accessory,
            accessory=merged.clothing,
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
            cache_only=True,
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
