"""Player-lookup specialist helpers.

Detects a RealmEye IGN in chat and formats the scraped account summary
(Fame, Guild, etc.). Character loadouts stay on the UI card — they are
not handed to the model, so it cannot reprint them as a gear table.
"""
from __future__ import annotations

import re
from typing import Optional

import redis.asyncio as aioredis

from ..models.build import CLASS_ALIASES
from ..models.player import PlayerProfile
from .scraper import scrape_player_profile, scrape_player_pet

PLAYER_CACHE_PREFIX = "player:profile:v3:"
PLAYER_PET_CACHE_PREFIX = "player:pet:v1:"
# Wiki specialist stores last a week. A player row must never inherit that
# TTL — fame/gear change constantly and are scraped on lookup.
MAX_PLAYER_CACHE_SECONDS = 15 * 60

PLAYER_LOOKUP_RE = re.compile(
    r"(?:/player|look\s*up\s*player|player)\s+([A-Za-z0-9_]{1,20})\b",
    re.IGNORECASE,
)
EXALT_PLAYER_RE = re.compile(
    r"\bexalt(?:ation)?s?\s+(?:does|do|did)\s+([A-Za-z0-9_]{1,20})\b",
    re.IGNORECASE,
)
POSSESSIVE_EXALT_RE = re.compile(
    r"\b([A-Za-z0-9_]{1,20})(?:'?s)?\s+exalt(?:ation)?s?\b",
    re.IGNORECASE,
)
EXALT_FOR_PLAYER_RE = re.compile(
    r"\bexalt(?:ation)?s?\b[\s\S]{0,40}\b(?:for|of)\s+([A-Za-z0-9_]{1,20})\b",
    re.IGNORECASE,
)
PLAYER_FOLLOWUP_RE = re.compile(
    r"\b(exalt|fame|guild|characters?|pets?|last seen|equipment|gear)\b",
    re.IGNORECASE,
)
POSSESSIVE_IGN_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9_]{0,19})'s\b",
    re.IGNORECASE,
)
_IGN_STOP = {
    "a",
    "an",
    "and",
    "best",
    "build",
    "class",
    "damage",
    "dps",
    "for",
    "from",
    "gear",
    "her",
    "highest",
    "his",
    "how",
    "it",
    "item",
    "its",
    "let",
    "look",
    "max",
    "maximum",
    "much",
    "my",
    "of",
    "or",
    "our",
    "player",
    "potential",
    "set",
    "that",
    "the",
    "their",
    "this",
    "what",
    "with",
    "your",
}
_CLASS_TOKENS = {
    token
    for canon, aliases in CLASS_ALIASES.items()
    for token in (canon.lower(), *aliases)
}


def extract_class_name(message: str) -> Optional[str]:
    """The one RotMG class named in this text, or None if zero or several."""
    text = message or ""
    hits: list[str] = []
    for canonical, aliases in CLASS_ALIASES.items():
        tokens = (canonical.lower(), *aliases)
        if any(re.search(rf"\b{re.escape(token)}\b", text, re.I) for token in tokens):
            hits.append(canonical)
    return hits[0] if len(hits) == 1 else None


def character_equipment_names(
    profile: PlayerProfile, class_name: Optional[str]
) -> list[str]:
    """Weapon, ability, armor, ring from that class row. Bag is skipped."""
    characters = list(profile.characters or [])
    chosen = None
    if class_name:
        needle = class_name.strip().lower()
        chosen = next(
            (
                row
                for row in characters
                if (row.class_name or "").strip().lower() == needle
            ),
            None,
        )
    if chosen is None and len(characters) == 1:
        chosen = characters[0]
    if chosen is None:
        return []
    names: list[str] = []
    for item in (chosen.equipment or [])[:4]:
        name = (item.name or "").strip()
        if name:
            names.append(name)
    return names


def _is_plausible_ign(name: str) -> bool:
    token = (name or "").strip()
    if not token or token.lower() in _IGN_STOP or token.lower() in _CLASS_TOKENS:
        return False
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,19}", token))


def extract_player_ign(
    message: str,
    history: Optional[list[str]] = None,
) -> Optional[str]:
    """Pull an IGN from this turn, or from a prior lookup on a follow-up."""
    direct = PLAYER_LOOKUP_RE.search(message or "")
    if direct and _is_plausible_ign(direct.group(1)):
        return direct.group(1)

    if re.search(r"\bexalt", message or "", re.IGNORECASE):
        for pattern in (EXALT_PLAYER_RE, POSSESSIVE_EXALT_RE, EXALT_FOR_PLAYER_RE):
            match = pattern.search(message)
            if match and _is_plausible_ign(match.group(1)):
                return match.group(1)

    possessive_hits: list[tuple[int, str]] = []
    for match in POSSESSIVE_IGN_RE.finditer(message or ""):
        name = match.group(1)
        if not _is_plausible_ign(name):
            continue
        rest = (message or "")[match.end() : match.end() + 32].lower()
        followed_by_class = any(
            re.match(rf"\s+{re.escape(token)}\b", rest) for token in _CLASS_TOKENS
        )
        possessive_hits.append((1 if followed_by_class else 0, name))
    if possessive_hits:
        possessive_hits.sort(key=lambda row: row[0], reverse=True)
        return possessive_hits[0][1]

    if history and PLAYER_FOLLOWUP_RE.search(message or ""):
        for prev in reversed(history):
            found = extract_player_ign(prev)
            if found:
                return found
    return None


async def get_or_scrape_player(
    redis: aioredis.Redis,
    username: str,
    *,
    ttl_seconds: int,
) -> PlayerProfile:
    """Redis-cached RealmEye profile; same key the /players route uses."""
    cache_key = f"{PLAYER_CACHE_PREFIX}{username.lower()}"
    if ttl_seconds > 0:
        ttl_seconds = min(int(ttl_seconds), MAX_PLAYER_CACHE_SECONDS)
        cached = await redis.get(cache_key)
        if cached:
            return PlayerProfile.model_validate_json(cached)
    profile = await scrape_player_profile(username)
    if ttl_seconds > 0:
        await redis.setex(cache_key, ttl_seconds, profile.model_dump_json())
    return profile


async def get_or_scrape_player_pet(
    redis: aioredis.Redis,
    username: str,
    *,
    ttl_seconds: int,
) -> PlayerProfile:
    """Redis-cached compact pet lookup for the sidebar IGN field."""
    cache_key = f"{PLAYER_PET_CACHE_PREFIX}{username.lower()}"
    if ttl_seconds > 0:
        ttl_seconds = min(int(ttl_seconds), MAX_PLAYER_CACHE_SECONDS)
        cached = await redis.get(cache_key)
        if cached:
            return PlayerProfile.model_validate_json(cached)
    profile = await scrape_player_pet(username)
    if ttl_seconds > 0:
        await redis.setex(cache_key, ttl_seconds, profile.model_dump_json())
    return profile


def format_player_brief(profile: PlayerProfile) -> str:
    """Account-summary bullets for the model. Character gear stays in the UI card."""
    return "\n".join(
        [
            "Copy these summary bullets exactly, then go straight to ## Sources. "
            "Each fact must be its own markdown list item on its own line, "
            "starting with '- '. Never join them onto one line.",
            "Do not list characters. Do not write a gear/loadout table. Do not "
            "name weapons, abilities, armors, or rings. The UI Characters "
            "section already shows portraits, fame, rank, and worn items "
            "from the scrape.",
            "",
            *format_player_fact_lines(profile),
        ]
    )


def format_player_stored_reply(profile: PlayerProfile) -> str:
    """Same facts as the model brief, without the copy-this instructions."""
    return "\n".join(format_player_fact_lines(profile))


def format_player_fact_lines(profile: PlayerProfile) -> list[str]:
    guild = profile.guild or "No guild"
    if profile.guild and profile.guild_rank:
        guild = f"{profile.guild} ({profile.guild_rank})"
    fame = f"{profile.fame:,}" if profile.fame is not None else "unknown"
    account_fame = (
        f"{profile.account_fame:,}"
        if profile.account_fame is not None
        else "unknown"
    )
    exalts = (
        f"{profile.total_exaltations:,}"
        if profile.total_exaltations is not None
        else "unknown"
    )
    pet = profile.top_pet.name if profile.top_pet else "unknown"
    seen = profile.last_seen or "unknown"
    return [
        f"- Fame: **{fame}**",
        f"- Account fame: **{account_fame}**",
        f"- Guild: **{guild}**",
        f"- Total exaltations: **{exalts}**",
        f"- Top pet: **{pet}**",
        f"- Last seen: **{seen}**",
    ]
