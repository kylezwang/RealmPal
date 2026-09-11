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
from typing import Optional

import redis.asyncio as aioredis
from fastapi import Request
from loguru import logger

from ..config import Settings
from ..identity import AuthenticatedUser

USER_SCOPE = "user"
ANONYMOUS_SCOPE = "ip"

# Quota windows roll every 24h.
QUOTA_TTL_SECONDS = 60 * 60 * 24

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


def _hash_identifier(value: str, settings: Settings) -> str:
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
        label = _hash_identifier(user.subject, settings)
        return Quota(
            scope=USER_SCOPE,
            key=f"ratelimit:{USER_SCOPE}:{user.subject}",
            limit=settings.free_message_limit,
            label=label[:12],
        )

    hashed = _hash_identifier(client_ip(request, settings), settings)
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


async def consume(redis: aioredis.Redis, quota: Quota) -> int:
    """Count one request against the quota and return the new total."""
    count = await redis.incr(quota.key)
    if count == 1:
        await redis.expire(quota.key, QUOTA_TTL_SECONDS)
    return int(count)
