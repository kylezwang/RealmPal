"""Enchantment specialist: RealmEye roll tables + UmiEnjoyers BIS notes.

Chat reads Redis only. Weekly refresh / warm_specialists scrape
https://www.realmeye.com/wiki/enchanting. Umi general-tab BIS is
supplementary — RealmEye is the source of truth for numbers.
"""
from __future__ import annotations

import json
import re
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from ..models.build import PLAYER_STATS, STAT_ALIASES
from .scraper import REALMEYE_BASE, ScraperError, scrape_enchanting_page
from .wiki_scaling import infer_item_base_stat, read_cached_item, retrieve_umi_bis

CACHE_KEY = "wiki:enchanting:v1"
SOURCE_URL = f"{REALMEYE_BASE}/wiki/enchanting"
MAX_ROLLS = 36

_ENCHANT_WORD = re.compile(
    r"\b(enchant(?:s|ed|ing|ments?)?|enchanter|rerolls?|awakened|awakenings?)\b",
    re.I,
)
_STAT_ROLL = re.compile(
    r"\b(?:best|what|which)\s+"
    r"(?:hp|mp|att|atk|dex|def|spd|vit|wis|life|mana|attack|defense|"
    r"defence|speed|dexterity|vitality|wisdom)\s+rolls?\b",
    re.I,
)
_ROLLS_ON = re.compile(r"\brolls?\s+on\b", re.I)
_ON_ITEM = re.compile(
    r"\b(?:on|for|for a|for the)\s+(?:the\s+)?(.+?)\s*$",
    re.I,
)
_ELIGIBLE = re.compile(
    r"^(ALL|WEAPON|ABILITY|ARMOR|RING|WEAPONRING|ABILITYRING|ARMORRING)$",
    re.I,
)
_STAT_TOKEN: dict[str, re.Pattern[str]] = {
    "HP": re.compile(r"\b(?:hp|life)\b", re.I),
    "MP": re.compile(r"\b(?:mp|mana)\b", re.I),
    "Attack": re.compile(r"\b(?:att(?:ack)?|atk)\b", re.I),
    "Defense": re.compile(r"\b(?:def(?:en[cs]e)?)\b", re.I),
    "Speed": re.compile(r"\b(?:spd|speed)\b", re.I),
    "Dexterity": re.compile(r"\b(?:dex(?:terity)?)\b", re.I),
    "Vitality": re.compile(r"\b(?:vit(?:ality)?)\b", re.I),
    "Wisdom": re.compile(r"\b(?:wis(?:dom)?)\b", re.I),
}
_DPS_MOD = re.compile(r"weapon damage|fire\s*rate", re.I)
_CONVERSION = re.compile(r"^(.+?)\s+to\s+(.+?)\s+bonus$", re.I)
_TRADEOFF = re.compile(r"^(\S+)\s+.+\s+tradeoff$", re.I)
_WEAPON_HINT = re.compile(
    r"\b(bows?|daggers?|staves|staff|wands?|swords?|katanas?|blades?)\b",
    re.I,
)
_ABILITY_HINT = re.compile(
    r"\b(quiver|lute|cloak|spell|tome|helm|shield|seal|poison|skull|"
    r"trap|orb|prism|scepter|star|wakizashi|mace|sheath|sigil|qot)\b",
    re.I,
)
_ARMOR_HINT = re.compile(r"\b(robe|leather|heavy|armor|armour)\b", re.I)
_RING_HINT = re.compile(r"\b(rings?|amulet|bracer|scarf|mask)\b", re.I)


def is_enchant_query(message: str) -> bool:
    text = message or ""
    if _ENCHANT_WORD.search(text):
        return True
    if _STAT_ROLL.search(text) or _ROLLS_ON.search(text):
        return True
    return False


def infer_gear_slot(name: str) -> Optional[str]:
    blob = name or ""
    if _WEAPON_HINT.search(blob):
        return "weapon"
    if _ABILITY_HINT.search(blob):
        return "ability"
    if _ARMOR_HINT.search(blob):
        return "armor"
    if _RING_HINT.search(blob):
        return "ring"
    return None


def extract_enchant_item(message: str) -> Optional[str]:
    """Best-effort item mention after on/for, else a trailing proper name."""
    from .item_aliases import community_canonical, extract_mentioned_items

    text = (message or "").strip()
    mentioned = extract_mentioned_items(text)
    if mentioned:
        return mentioned[0]
    match = _ON_ITEM.search(text)
    candidate = (match.group(1) if match else "").strip(" ?.!")
    if candidate:
        canonical = community_canonical(candidate)
        if canonical:
            return canonical
        if 1 < len(candidate.split()) <= 6 and not is_enchant_query(candidate):
            return candidate
        if candidate.lower() in {"qot", "leaf bow"}:
            return community_canonical(candidate) or candidate
        if match and len(candidate.split()) <= 4:
            return community_canonical(candidate) or candidate
    for token in re.findall(r"\b[A-Za-z][A-Za-z']+\b", text):
        canonical = community_canonical(token)
        if canonical:
            return canonical
    return None


def _looks_header(row: list[str]) -> bool:
    joined = " ".join(row).lower()
    return "enchantment" in joined and ("eligible" in joined or "effect" in joined)


def _normalize_row(row: list[str], heading: str) -> Optional[dict]:
    cells = [c.strip() for c in row if (c or "").strip()]
    if len(cells) < 2 or _looks_header(cells):
        return None
    eligible = ""
    name = ""
    effects = ""
    labels = ""
    incompatible = ""
    remaining = list(cells)
    for i, cell in enumerate(cells):
        if _ELIGIBLE.match(cell.replace(" ", "")):
            eligible = cell.replace(" ", "").upper()
            remaining = cells[:i] + cells[i + 1 :]
            break
    if remaining:
        name = remaining[0]
        rest = remaining[1:]
        if rest:
            effects = rest[0]
        if len(rest) > 1:
            labels = rest[1]
        if len(rest) > 2:
            incompatible = rest[2]
    if not name or name.lower() in {"enchantment name", "enchantment", "name"}:
        return None
    if not eligible and not effects:
        return None
    if not eligible:
        # RealmEye's Awakened Enchantments table has no Eligible/slot column
        # at all (unlike Basic/Unique) - the section intro says these "only
        # specific item(s) can roll", e.g. Infernal Anger is exclusive to
        # Berserker's Breastplate, not "any heavy armor". Defaulting the
        # missing cell to ALL made every awakened enchant look generically
        # eligible for any weapon/armor/ability/ring. Found live Sep 14:
        # Infernal Anger recommended for a generic Attack Kensei build that
        # has nothing to do with Berserker's Breastplate. Use a marker
        # _eligible_ok() never treats as slot-generic instead, so awakened
        # rows only surface via roll_matches()'s item-name-mentioned
        # fallback (the one item they're honestly for), never a blanket
        # stat/slot match.
        eligible = "AWAKENED_ITEM_LOCKED" if "awakened" in (heading or "").lower() else "ALL"
    return {
        "name": name,
        "eligible": eligible,
        "effects": effects,
        "labels": labels,
        "incompatible": incompatible,
        "category": heading,
    }


def rolls_from_tables(tables: list[dict]) -> list[dict]:
    rolls: list[dict] = []
    seen: set[str] = set()
    for table in tables:
        heading = (table.get("heading") or "").strip()
        if re.search(r"\b(history|trivia|notes|enchanter|dusts?|artifacts?)\b", heading, re.I):
            if "enchantment" not in heading.lower():
                continue
        for row in table.get("rows") or []:
            parsed = _normalize_row(list(row), heading)
            if not parsed:
                continue
            key = parsed["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            rolls.append(parsed)
    return rolls


def store_from_scrape(raw: dict) -> dict:
    rolls = list(raw.get("rolls") or [])
    if not rolls:
        rolls = rolls_from_tables(list(raw.get("tables") or []))
    return {
        "title": raw.get("title") or "Enchanting",
        "url": raw.get("url") or SOURCE_URL,
        "overview": (raw.get("overview") or "")[:1200],
        "rolls": rolls,
    }


async def load_enchanting_store(
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
        raw = await scrape_enchanting_page()
    except ScraperError as e:
        logger.bind(error=str(e)).warning("RealmEye enchanting page unavailable")
        return {}
    store = store_from_scrape(raw)
    await redis.setex(CACHE_KEY, ttl_seconds, json.dumps(store))
    return store


async def enchanting_store_status(redis: aioredis.Redis) -> dict:
    raw = await redis.get(CACHE_KEY)
    ttl = await redis.ttl(CACHE_KEY)
    rolls = 0
    if raw:
        try:
            rolls = len(store_from_scrape(json.loads(raw)).get("rolls") or [])
        except json.JSONDecodeError:
            rolls = 0
    return {
        "stored": 1 if rolls else 0,
        "rolls": rolls,
        "ttl_seconds": max(0, int(ttl or 0)),
    }


async def warm_enchanting_store(
    redis: aioredis.Redis,
    *,
    ttl_seconds: int,
    force: bool = False,
) -> dict:
    store = await load_enchanting_store(
        redis, ttl_seconds=ttl_seconds, cache_only=False, force=force
    )
    rolls = len(store.get("rolls") or [])
    return {"stored": 1 if rolls else 0, "rolls": rolls}


_KNOWN_ELIGIBLE_TOKENS = frozenset(
    {"ALL", "WEAPON", "ABILITY", "ARMOR", "RING", "WEAPONRING", "ABILITYRING", "ARMORRING"}
)


def _eligible_ok(eligible: str, slot: Optional[str]) -> bool:
    token = (eligible or "ALL").replace(" ", "").upper()
    if token not in _KNOWN_ELIGIBLE_TOKENS:
        # AWAKENED_ITEM_LOCKED (see _normalize_row) or anything else outside
        # the real slot vocabulary is never a generic match, even when the
        # caller doesn't know the slot yet - unlike a real slot code, "no
        # slot known" must not default to "fine everywhere" here.
        return False
    if not slot or token == "ALL":
        return True
    return slot.upper() in token


def _asked_stat(stat: Optional[str]) -> Optional[str]:
    if not stat:
        return None
    return STAT_ALIASES.get(stat.lower(), stat if stat in PLAYER_STATS else None)


def roll_matches(
    roll: dict,
    *,
    stat: Optional[str] = None,
    slot: Optional[str] = None,
    item_name: Optional[str] = None,
) -> bool:
    """Keep matching-stat / matching-slot rolls. Drop other-stat flats."""
    if not _eligible_ok(roll.get("eligible") or "", slot):
        if item_name and item_name.lower() in (
            f"{roll.get('name')} {roll.get('effects')}".lower()
        ):
            return True
        return False
    asked = _asked_stat(stat)
    if not asked:
        return True
    name = roll.get("name") or ""
    blob = f"{name} {roll.get('effects') or ''} {roll.get('labels') or ''}"
    conv = _CONVERSION.match(name.strip())
    if conv:
        dest = _asked_stat(conv.group(2))
        return dest == asked
    trade = _TRADEOFF.match(name.strip())
    if trade:
        gained = _asked_stat(trade.group(1))
        return gained == asked
    if asked in {"Attack", "Dexterity"} and _DPS_MOD.search(blob):
        return True
    this_hit = bool(_STAT_TOKEN[asked].search(blob))
    if not this_hit:
        return False
    # Single-stat flats for a different stat (Mana Bonus on an Attack ask).
    for other in PLAYER_STATS:
        if other == asked:
            continue
        other_pat = _STAT_TOKEN[other]
        if (
            re.search(rf"^{other}\s+bonus$", name, re.I)
            or re.search(rf"^relative {other}\s+bonus$", name, re.I)
        ):
            return False
        if other_pat.search(name) and not _STAT_TOKEN[asked].search(name):
            if "to" not in name.lower():
                return False
    return this_hit


def filter_rolls(
    rolls: list[dict],
    *,
    stat: Optional[str] = None,
    slot: Optional[str] = None,
    item_name: Optional[str] = None,
    limit: int = MAX_ROLLS,
) -> list[dict]:
    matched = [
        roll
        for roll in rolls
        if roll_matches(roll, stat=stat, slot=slot, item_name=item_name)
    ]

    def rank(roll: dict) -> tuple[int, str]:
        category = (roll.get("category") or "").lower()
        name = (roll.get("name") or "").lower()
        if "unique" in category or "unique" in (roll.get("labels") or "").lower():
            score = 0
        elif "awakened" in category:
            score = 1
        elif "tradeoff" in name:
            score = 3
        elif "relative" in name:
            score = 2
        else:
            score = 2
        return (score, name)

    matched.sort(key=rank)
    return matched[:limit]


def format_enchant_table(rolls: list[dict]) -> str:
    if not rolls:
        return ""
    lines = [
        "| Enchantment | Eligible | Effect(s) |",
        "| --- | --- | --- |",
    ]
    for roll in rolls:
        name = (roll.get("name") or "").replace("|", "/")
        eligible = roll.get("eligible") or "ALL"
        effects = (roll.get("effects") or "").replace("|", "/")
        lines.append(f"| {name} | {eligible} | {effects} |")
    return "\n".join(lines)


def umi_enchant_excerpt(text: str, *, item_name: Optional[str] = None) -> str:
    if not text:
        return ""
    blocks: list[str] = []
    current: list[str] = []
    capturing = False
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^enchantments?:?\s*$", stripped, re.I):
            capturing = True
            current = ["Enchantments:"]
            continue
        if capturing:
            if not stripped or re.match(r"^#{1,4}\s", stripped):
                if len(current) > 1:
                    blocks.append("\n".join(current))
                capturing = False
                current = []
                continue
            current.append(stripped)
            if len(current) > 8:
                blocks.append("\n".join(current))
                capturing = False
                current = []
    if capturing and len(current) > 1:
        blocks.append("\n".join(current))
    if not blocks and re.search(r"enchant", text, re.I):
        # Keep a short window around the first Enchantments mention.
        idx = re.search(r"enchant", text, re.I)
        if idx:
            start = max(0, idx.start() - 80)
            return text[start : start + 900].strip()
    excerpt = "\n\n".join(blocks[:8])
    if item_name and excerpt:
        lowered = excerpt.lower()
        if item_name.lower() not in lowered:
            return excerpt
    return excerpt.strip()


async def retrieve_enchanting_brief(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int,
    class_name: Optional[str] = None,
    stat: Optional[str] = None,
    cache_only: bool = True,
) -> str:
    store = await load_enchanting_store(
        redis, ttl_seconds=ttl_seconds, cache_only=cache_only
    )
    rolls = list((store or {}).get("rolls") or [])
    item_name = extract_enchant_item(message)
    mentioned = []
    try:
        from .item_aliases import extract_mentioned_items

        mentioned = extract_mentioned_items(message)
    except Exception:
        mentioned = [item_name] if item_name else []
    if mentioned:
        item_name = mentioned[0]
    if item_name:
        from .item_aliases import community_canonical, resolve_item_query

        resolved = community_canonical(item_name) or await resolve_item_query(
            redis,
            item_name,
            ttl_seconds=ttl_seconds,
            class_name=class_name,
            allow_scrape=False,
        )
        if resolved:
            item_name = resolved
            mentioned[0] = resolved

    if len(mentioned) > 1:
        extra = []
        for name in mentioned[1:]:
            resolved = community_canonical(name) or await resolve_item_query(
                redis,
                name,
                ttl_seconds=ttl_seconds,
                class_name=class_name,
                allow_scrape=False,
            )
            extra.append(resolved or name)
        mentioned = [item_name, *extra] if item_name else extra

    # No stat named ("what enchants on Cackling Straitjacket")? Infer one
    # from the item's own On Equip bonus | a +20 Attack robe implies an
    # Attack build, so recommend Attack-focused enchants unless the user
    # asked for a different stat outright.
    inferred_stat = False
    inferred_from = ""
    if not stat and item_name:
        item = await read_cached_item(redis, item_name)
        if item:
            guess = infer_item_base_stat(item)
            if guess:
                stat = guess
                inferred_stat = True
                inferred_from = item.stats.get("On Equip") or next(
                    (v for k, v in (item.stats or {}).items() if "on equip" in k.lower()),
                    "",
                )

    slot = infer_gear_slot(item_name or message)
    matched = filter_rolls(rolls, stat=stat, slot=slot, item_name=item_name)
    parts = [
        "ENCHANTMENT AGENT — RealmEye /wiki/enchanting tables. "
        "Copy numbers from this chunk only. One unique enchant per item; "
        "single-stat flats cannot stack with another single-stat flat. "
        "Awakened enchants (e.g. Infernal Anger, Hellfire Edge) each only "
        "roll on one or a few specific named items, never a whole slot - "
        "don't recommend one unless the table row or item context here "
        "names this exact item as eligible for it. "
        f"Source: {store.get('url') or SOURCE_URL}"
    ]
    if item_name:
        parts.append(f"Item: {item_name}" + (f" ({slot})" if slot else ""))
    if len(mentioned) > 1:
        names = ", ".join(f"[item:{name}]" for name in mentioned)
        parts.append(
            f"Compare awakened / unique enchants across these items: {names}. "
            "Name a winner only from the table rows in this chunk."
        )
    if inferred_stat:
        parts.append(
            f"No stat was named. {item_name}'s own On Equip bonus is "
            f"{inferred_from or stat}, which implies a {stat} build | "
            f"recommend {stat}-focused enchants to match. Say so briefly, "
            "then only recommend other-stat flats if the user asks for a "
            "different build on this item."
        )
    elif stat:
        parts.append(f"Requested stat: {stat}. Do not recommend other-stat flats.")
    table = format_enchant_table(matched)
    if table:
        parts.append(table)
    elif rolls:
        parts.append(
            "No matching enchant rows for this slot/stat in the stored tables."
        )
    else:
        parts.append("Enchanting store is empty. Do not invent roll values.")
        return "\n".join(parts)

    if class_name:
        umi = await retrieve_umi_bis(
            redis, class_name, ttl_seconds=ttl_seconds, cache_only=True
        )
        excerpt = umi_enchant_excerpt(umi, item_name=item_name)
        if excerpt:
            parts.append(
                "SUPPLEMENTARY — UmiEnjoyers BIS enchant notes "
                "(community picks, not RealmEye numbers).\n" + excerpt
            )
    return "\n".join(parts)
