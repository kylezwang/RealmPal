"""
Quota enforcement keyed on something the caller cannot choose.

The MVP keyed the free tier on `session_id`, a UUID the browser generated and
sent in the request body, so clearing localStorage handed out a fresh
allowance. Quotas now resolve in this order:

  1. A verified identity provider `sub` (see api/identity.py).
  2. Otherwise the client IP, for anonymous traffic.

Anonymous callers get a smaller allowance than signed-in ones, which makes
signing in the cheap way to get more rather than something to work around.

Two things worth knowing about the IP path:

  * `X-Forwarded-For` is only consulted when `trust_forwarded_for` is on.
    Anyone can send that header, so trusting it by default would hand back
    the exact bypass we just closed. Behind a proxy, set the hop count so we
    read the entry the proxy itself appended.
  * IPs are stored as keyed hashes, never in the clear, so the quota keys
    aren't a log of who visited.

The server must be started with `--no-proxy-headers`. Uvicorn enables proxy
header handling by default and rewrites `request.client.host` from
`X-Forwarded-For` whenever the peer is in `forwarded_allow_ips`, which would
override the decision made here before this module ever runs. Every launch
path we ship passes the flag; `api/main.py` warns at startup if the
environment looks like it was re-enabled.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
from fastapi import Request
from loguru import logger

from ..config import Settings
from ..identity import AuthenticatedUser

USER_SCOPE = "user"
ANONYMOUS_SCOPE = "ip"
LOOKUP_SCOPE = "lookup"

# Quota windows roll every 24h. Kept as a constant (still the right ceiling
# for a "how long could this TTL possibly be" assertion) even though the
# actual expiry `consume()` sets is no longer a flat 24h - see
# seconds_until_daily_reset().
QUOTA_TTL_SECONDS = 60 * 60 * 24

# Until Sep 14, 2026, a caller's free quota reset 24h after their own first
# message of the window (INCR + EXPIRE QUOTA_TTL_SECONDS on the first hit).
# That meant "when do I get my next 5 free messages" depended on exactly
# when you happened to send your first one - a user who messaged at 11pm
# reset at 11pm the next day, one who messaged at 6am reset at 6am. Reported
# live Sep 14: users expected a single shared daily reset instead. Now every
# free/anonymous quota resets at the same wall-clock instant for everyone:
# 5pm Pacific (America/Los_Angeles, so it tracks PST/PDT automatically).
_PACIFIC = ZoneInfo("America/Los_Angeles")
_DAILY_RESET_HOUR_PT = 17


def seconds_until_daily_reset(now: Optional[datetime] = None) -> int:
    """Seconds from `now` (default: real now) until the next 5pm Pacific."""
    current = (now or datetime.now(timezone.utc)).astimezone(_PACIFIC)
    target = datetime.combine(current.date(), time(_DAILY_RESET_HOUR_PT), tzinfo=_PACIFIC)
    if target <= current:
        target += timedelta(days=1)
    return max(1, int((target - current).total_seconds()))

_UNKNOWN_CLIENT = "unknown"


@dataclass(frozen=True)
class Quota:
    """Which bucket a request counts against, and how big that bucket is."""

    scope: str
    key: str
    limit: int
    # Truncated hash, safe to log. Never the raw IP or full subject.
    label: str

    @property
    def is_anonymous(self) -> bool:
        return self.scope == ANONYMOUS_SCOPE


def hash_identifier(value: str, settings: Settings) -> str:
    """Keyed hash of an identifier, so raw IPs and emails never reach Redis."""
    secret = settings.pii_hash_secret or settings.jwt_secret
    digest = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()[:32]


def client_ip(request: Request, settings: Settings) -> str:
    """
    Best available client address.

    Returns the socket peer unless we've been told a proxy sits in front, in
    which case we read the entry that proxy appended to X-Forwarded-For.
    Entries further left are supplied by the caller and cannot be trusted.
    """
    peer = request.client.host if request.client else None

    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        hops = max(1, settings.forwarded_proxy_hops)
        if len(parts) >= hops:
            return parts[-hops]
        if parts:
            # Fewer hops than configured means the chain isn't what we expect.
            logger.bind(entries=len(parts), expected_hops=hops).warning(
                "X-Forwarded-For shorter than configured proxy hops; using socket peer"
            )

    return peer or _UNKNOWN_CLIENT


def quota_for(
    user: Optional[AuthenticatedUser],
    request: Request,
    settings: Settings,
) -> Quota:
    """Resolve the quota bucket for this caller."""
    if user is not None:
        label = hash_identifier(user.subject, settings)
        return Quota(
            scope=USER_SCOPE,
            key=f"ratelimit:{USER_SCOPE}:{user.subject}",
            limit=settings.free_message_limit,
            label=label[:12],
        )

    hashed = hash_identifier(client_ip(request, settings), settings)
    return Quota(
        scope=ANONYMOUS_SCOPE,
        key=f"ratelimit:{ANONYMOUS_SCOPE}:{hashed}",
        limit=settings.anonymous_message_limit,
        label=hashed[:12],
    )


async def peek(redis: aioredis.Redis, quota: Quota) -> int:
    """Current usage without consuming any."""
    raw = await redis.get(quota.key)
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


async def peek_ttl(redis: aioredis.Redis, quota: Quota) -> int:
    """Seconds until this daily bucket resets, or 0 if it is already fresh."""
    ttl = await redis.ttl(quota.key)
    try:
        seconds = int(ttl)
    except (TypeError, ValueError):
        return 0
    return seconds if seconds > 0 else 0


async def consume(redis: aioredis.Redis, quota: Quota) -> int:
    """Count one request against the quota and return the new total."""
    count = await redis.incr(quota.key)
    if count == 1:
        await redis.expire(quota.key, seconds_until_daily_reset())
    return int(count)


@dataclass(frozen=True)
class WindowedQuota:
    """
    A short-window sibling of `Quota`, for endpoints that aren't a daily
    free-message allowance but still shouldn't be free to hammer.

    Player/item/dungeon/skin lookups scrape RealmEye on a cache miss, which
    means launching a real headless browser. `Quota`'s 24h window is the
    wrong shape for that: a burst of a few hundred requests in one minute is
    the problem, not the day's total. This resolves the same way (verified
    subject, else hashed IP) with its own key namespace and TTL.
    """

    key: str
    limit: int
    window_seconds: int
    label: str


def lookup_quota_for(
    user: Optional[AuthenticatedUser],
    request: Request,
    settings: Settings,
) -> WindowedQuota:
    """Resolve the burst-limit bucket for a scrape-triggering lookup."""
    if user is not None:
        label = hash_identifier(user.subject, settings)
        return WindowedQuota(
            key=f"ratelimit:{LOOKUP_SCOPE}:{USER_SCOPE}:{user.subject}",
            limit=settings.lookup_rate_limit_user,
            window_seconds=settings.lookup_rate_window_seconds,
            label=label[:12],
        )

    hashed = hash_identifier(client_ip(request, settings), settings)
    return WindowedQuota(
        key=f"ratelimit:{LOOKUP_SCOPE}:{ANONYMOUS_SCOPE}:{hashed}",
        limit=settings.lookup_rate_limit_anonymous,
        window_seconds=settings.lookup_rate_window_seconds,
        label=hashed[:12],
    )


async def consume_windowed(redis: aioredis.Redis, quota: WindowedQuota) -> int:
    """Count one request against a short-window quota and return the total."""
    count = await redis.incr(quota.key)
    if count == 1:
        await redis.expire(quota.key, quota.window_seconds)
    return int(count)
