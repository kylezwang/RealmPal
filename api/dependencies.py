from functools import lru_cache
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends
from qdrant_client import AsyncQdrantClient

from .config import Settings, get_settings


@lru_cache
def _get_redis(redis_url: str) -> aioredis.Redis:
    return aioredis.from_url(redis_url, decode_responses=True)


@lru_cache
def _get_qdrant(qdrant_url: str, qdrant_api_key: str) -> AsyncQdrantClient:
    if qdrant_api_key:
        return AsyncQdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    return AsyncQdrantClient(url=qdrant_url)


async def get_redis(settings: Annotated[Settings, Depends(get_settings)]) -> aioredis.Redis:
    return _get_redis(settings.redis_url)


async def get_qdrant(settings: Annotated[Settings, Depends(get_settings)]) -> AsyncQdrantClient:
    return _get_qdrant(settings.qdrant_url, settings.qdrant_api_key)
