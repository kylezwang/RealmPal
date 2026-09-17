"""Daily quest completion bonus: +1 message once per quota window.

Free and guest accounts get one extra daily chat. Paid accounts get one extra
included Claude reply. Claim is idempotent within that window.

The free/guest bonus is deliberately NOT keyed to the UTC calendar day. As of
Sep 14, 2026 the message quota itself (`rate_limit.Quota`) resets for
everyone at the same wall-clock instant, 5pm Pacific
(`rate_limit.seconds_until_daily_reset`) - but a calendar-day bonus key would
still drift out of sync with it, since UTC midnight and 5pm Pacific are two
different, unrelated instants (and the offset between them shifts with
PST/PDT). `claim_daily_bonus` takes the caller's live quota TTL
(`rate_limit.peek_ttl`) and expires the claim/bonus keys at the same moment
the quota resets, so the two can't drift regardless of which wall-clock
instant that is. The paid path is unaffected: it increments a calendar-month
pool (`_paid_bonus_key`), which matches the monthly Claude included-pool it
feeds.

## History

### Until Sep 14, 2026
The message quota was a rolling 24h window that started on a caller's own
first message of the window, not aligned to any shared clock time (INCR +
EXPIRE 86400 on the first hit). Reported live Sep 14: users expected a
single shared daily reset (framed as "5pm Pacific") instead of "24h after
whenever I happened to first message." `seconds_until_daily_reset()`
replaced the flat `QUOTA_TTL_SECONDS` expiry in `rate_limit.consume()`.

Also picks today's dungeon portal and a cached shiny-divine sprite so the
quests modal can show real wiki art instead of empty checkboxes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from ..config import Settings
from .dungeon_guide import load_dungeon_guide
from .rate_limit import hash_identifier, seconds_until_daily_reset
from .wiki_scaling import read_cached_item

BONUS_MESSAGES = 1
_WIKI_TAIL = re.compile(r"\s*[-–—]\s*the RotMG Wiki.*$", re.I)

# Well-known warmed dungeons. One is featured each UTC day.
DUNGEON_ROTATION = (
    "Hardmode Shatters",
    "Moonlight Village",
    "Oryx's Sanctuary",
    "The Nest",
    "Cultist Hideout",
    "Carboniferous",
    "Floral Escape",
    "Sanguine Forest",
    "Runic Tundra",
    "Deep Sea Abyss",
    "The Shatters",
)

# Divine / UT items that usually have a shiny recast in the wiki store.
SHINY_DIVINE_CANDIDATES = (
    "Snake Eye Ring",
    "The Twilight Gemstone",
    "Crown",
    "Ring of the Nile",
    "Bracer of the Guardian",
    "Omnipotence Ring",
    "The Forgotten Crown",
    "Chrysalis of Eternity",
    "Tablet of the King's Avatar",
    "Sentinel's Sidearm",
)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def identity_key(subject: str, settings: Settings) -> str:
    return hash_identifier((subject or "").strip().lower(), settings)


def _claimed_key(bucket: str) -> str:
    # No date suffix: this key's TTL (set at claim time from the caller's
    # live quota TTL) is what defines "today", not the calendar.
    return f"quest:claimed:{bucket}"


def _free_bonus_key(bucket: str) -> str:
    return f"quest:bonus:free:{bucket}"


def _paid_bonus_key(bucket: str) -> str:
    return f"quest:bonus:paid:{bucket}:{_month()}"


async def peek_free_bonus(redis: aioredis.Redis, subject: str, settings: Settings) -> int:
    bucket = identity_key(subject, settings)
    raw = await redis.get(_free_bonus_key(bucket))
    return BONUS_MESSAGES if raw else 0


async def peek_paid_bonus(redis: aioredis.Redis, email: str, settings: Settings) -> int:
    bucket = identity_key(email, settings)
    raw = await redis.get(_paid_bonus_key(bucket))
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _seed(stamp: str) -> int:
    value = 0
    for char in stamp:
        value = (value * 31 + ord(char)) & 0xFFFFFFFF
    return value


def todays_dungeon_name(stamp: Optional[str] = None, shift: int = 0) -> str:
    day = stamp or _today()
    index = (_seed(day) + max(0, shift)) % len(DUNGEON_ROTATION)
    return DUNGEON_ROTATION[index]


@dataclass(frozen=True)
class QuestArt:
    dungeon_name: str
    dungeon_prompt: str
    dungeon_portal_url: Optional[str]
    shiny_name: str
    shiny_sprite_url: Optional[str]


async def todays_quest_art(
    redis: aioredis.Redis,
    settings: Settings,
    shift: int = 0,
) -> QuestArt:
    """Portal + shiny sprite from Redis only. Never scrape for the modal."""
    stamp = _today()
    seed = _seed(stamp) + max(0, shift)
    dungeon_name = todays_dungeon_name(stamp, shift)
    portal_url = None
    try:
        guide = await load_dungeon_guide(
            redis,
            dungeon_name,
            ttl_seconds=settings.wiki_ttl_seconds,
            cache_only=True,
        )
        if guide:
            cleaned = _WIKI_TAIL.sub("", guide.get("title") or "").strip()
            featured = dungeon_name.lower()
            title = cleaned.lower()
            if title and (featured in title or title in featured):
                dungeon_name = cleaned
                portal_url = guide.get("portal_url")
    except Exception:
        portal_url = None

    shiny_name = SHINY_DIVINE_CANDIDATES[seed % len(SHINY_DIVINE_CANDIDATES)]
    shiny_url = None
    start = seed % len(SHINY_DIVINE_CANDIDATES)
    for offset in range(len(SHINY_DIVINE_CANDIDATES)):
        candidate = SHINY_DIVINE_CANDIDATES[(start + offset) % len(SHINY_DIVINE_CANDIDATES)]
        try:
            item = await read_cached_item(redis, candidate)
        except Exception:
            item = None
        if item and (item.shiny_sprite_url or item.sprite_url):
            shiny_name = item.name
            shiny_url = item.shiny_sprite_url or item.sprite_url
            break

    dungeon_name = _WIKI_TAIL.sub("", dungeon_name or "").strip() or dungeon_name
    shiny_name = _WIKI_TAIL.sub("", shiny_name or "").strip() or shiny_name
    return QuestArt(
        dungeon_name=dungeon_name,
        dungeon_prompt=f"Guide to complete {dungeon_name}",
        dungeon_portal_url=portal_url,
        shiny_name=shiny_name,
        shiny_sprite_url=shiny_url,
    )


async def claim_daily_bonus(
    redis: aioredis.Redis,
    subject: str,
    settings: Settings,
    *,
    paid: bool,
    quota_ttl_seconds: int = 0,
) -> bool:
    """Grant this window's +1 if it has not already been claimed.

    `quota_ttl_seconds` should be the caller's live message-quota TTL
    (`rate_limit.peek_ttl`) for the free/guest path, so the claim and the
    bonus it grants expire at the same instant the quota itself resets. Pass
    0 (or omit) when the quota key doesn't exist yet, e.g. the caller hasn't
    sent a message on this window yet, in which case the time until the next
    shared 5pm-Pacific reset is used instead. Returns True if this call
    actually granted a new bonus.
    """
    bucket = identity_key(subject, settings)
    ttl = quota_ttl_seconds if quota_ttl_seconds > 0 else seconds_until_daily_reset()
    first = await redis.set(_claimed_key(bucket), "1", nx=True, ex=ttl)
    if not first:
        return False
    if paid:
        key = _paid_bonus_key(bucket)
        await redis.incr(key)
        await redis.expire(key, 40 * 24 * 3600)
    else:
        await redis.set(_free_bonus_key(bucket), "1", ex=ttl)
    return True
