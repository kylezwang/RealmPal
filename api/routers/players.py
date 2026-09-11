"""
Player lookup endpoint.

GET /players/{username}
  - Checks if player data in Qdrant (scraped within TTL)
  - If stale or missing: scrapes Realmeye (which includes the pet's sprite
    sheet crop info directly | see scraper.scrape_player_profile) and
    ingests to Qdrant, returns profile
"""
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from qdrant_client import AsyncQdrantClient

from ..config import Settings, get_settings
from ..dependencies import get_redis, get_qdrant
from ..models.player import PlayerProfile
from ..services.scraper import ScraperError
from ..services.ingestion import ingest_player
from ..services.player_lookup import get_or_scrape_player

router = APIRouter(prefix="/players", tags=["players"])


@router.get("/{username}", response_model=PlayerProfile)
async def get_player(
    username: str,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    qdrant: Annotated[AsyncQdrantClient, Depends(get_qdrant)],
) -> PlayerProfile:
    """Look up a player by username. Scrapes on demand with TTL caching."""
    try:
        profile = await get_or_scrape_player(
            redis, username, ttl_seconds=settings.scrape_ttl_hours * 3600
        )
    except ScraperError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        logger.exception("Unexpected error scraping player (debug)")
        raise

    # Ingest to Qdrant | embeddings backend being down (e.g. Ollama not
    # running) must not stop us from returning the profile we already
    # successfully scraped.
    try:
        await ingest_player(qdrant, profile)
    except Exception as e:
        logger.bind(username=username, error=str(e)).warning(
            "Could not ingest player profile into RAG store"
        )

    logger.bind(username=username).info("Player profile fetched and cached")
    return profile
