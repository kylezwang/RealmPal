from functools import lru_cache
from typing import Annotated, Optional

import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException
from loguru import logger
from qdrant_client import AsyncQdrantClient

from .config import Settings, get_settings
from .identity import AuthenticatedUser, IdentityError, bearer_token, verify_access_token
from .redis_namespace import namespaced


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
    if not token or not settings.auth_configured:
        return None
    try:
        return await verify_access_token(token, settings)
    except IdentityError as exc:
        logger.bind(reason=str(exc)).debug("Ignoring unverifiable access token")
        return None


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
