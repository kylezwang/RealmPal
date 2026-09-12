from functools import lru_cache
from typing import Annotated, Optional

import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException, Request
from loguru import logger
from qdrant_client import AsyncQdrantClient

from .auth import session_claims_from_header
from .config import Settings, get_settings
from .identity import AuthenticatedUser, IdentityError, bearer_token, verify_access_token
from .redis_namespace import namespaced
from .services.dev_access import is_debug_unlimited
from .services.rate_limit import consume_windowed, lookup_quota_for


@lru_cache
def _get_redis(redis_url: str) -> aioredis.Redis:
    return aioredis.from_url(redis_url, decode_responses=True)


@lru_cache
def _get_qdrant(qdrant_url: str, qdrant_api_key: str) -> AsyncQdrantClient:
    if qdrant_api_key:
        return AsyncQdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    return AsyncQdrantClient(url=qdrant_url)


async def get_redis(settings: Annotated[Settings, Depends(get_settings)]) -> aioredis.Redis:
    """
    Redis scoped to this deployment. Every key written through this client is
    prefixed, so two environments sharing an instance can't read each other's
    caches or quota counters.
    """
    return namespaced(_get_redis(settings.redis_url), settings.redis_key_prefix)


async def get_qdrant(settings: Annotated[Settings, Depends(get_settings)]) -> AsyncQdrantClient:
    return _get_qdrant(settings.qdrant_url, settings.qdrant_api_key)


async def get_optional_user(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> Optional[AuthenticatedUser]:
    """
    The verified caller, or None for anonymous traffic.

    Endpoints that serve both signed-in and guest users depend on this. An
    invalid token is treated as anonymous rather than an error, so a stale
    token in someone's browser degrades to the free tier instead of a hard
    failure | but it never grants identity.
    """
    token = bearer_token(authorization)
    if not token:
        return None

    if settings.auth_configured:
        try:
            return await verify_access_token(token, settings)
        except IdentityError as exc:
            logger.bind(reason=str(exc)).debug("Ignoring unverifiable access token")

    # Email+password (and magic-link) sessions are HS256 JWTs we signed
    # ourselves. Without this, a registered user still sits on the
    # anonymous IP quota because Entra JWKS is not configured locally.
    claims = session_claims_from_header(authorization, settings)
    email = claims.get("email") if claims else None
    if isinstance(email, str) and email.strip():
        return AuthenticatedUser(
            subject=email.strip().lower(),
            email=email.strip().lower(),
            claims=claims or {},
        )
    return None


async def enforce_lookup_rate_limit(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    user: Annotated[Optional[AuthenticatedUser], Depends(get_optional_user)] = None,
) -> None:
    """
    Throttle players/items/dungeons/skins/sprite lookups.

    A cache miss on any of these launches a real headless browser behind a
    single-Chromium semaphore in api/services/scraper.py. Without a limiter
    here, one caller's flood queues behind itself and delays every other
    visitor's lookup — a free denial-of-service, and real compute cost,
    that the chat quota in api/services/budget.py never covers.

    Fails open on a Redis problem, matching the budget check's philosophy:
    an infra blip should degrade, not take the feature down.
    """
    if await is_debug_unlimited(user, settings):
        return
    quota = lookup_quota_for(user, request, settings)
    try:
        count = await consume_windowed(redis, quota)
    except Exception:
        logger.exception("Could not enforce lookup rate limit")
        return
    if count > quota.limit:
        logger.bind(bucket=quota.label, used=count, limit=quota.limit).info(
            "Lookup rate limit exceeded"
        )
        raise HTTPException(
            status_code=429,
            detail="Too many lookups. Try again in a minute.",
            headers={"Retry-After": str(quota.window_seconds)},
        )


async def require_user(
    user: Annotated[Optional[AuthenticatedUser], Depends(get_optional_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedUser:
    """The verified caller, or 401. Use on anything that must not be anonymous."""
    if not settings.auth_configured:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Sign-in required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
