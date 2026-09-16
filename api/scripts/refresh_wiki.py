"""
Re-scrape RealmEye wiki hubs into Qdrant. Run once a week (cron / Task
Scheduler). Chat requests must not trigger this.

  cd api && ..\\.venv\\Scripts\\python.exe -m scripts.refresh_wiki
"""
import asyncio
import sys
from pathlib import Path

import redis.asyncio as aioredis
from qdrant_client import AsyncQdrantClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.config import get_settings
from api.redis_namespace import namespaced
from api.services.wiki_refresh import refresh_wiki_corpus


async def main() -> None:
    settings = get_settings()
    qdrant = AsyncQdrantClient(
        url=settings.qdrant_url, api_key=settings.qdrant_api_key or None
    )
    redis = namespaced(
        aioredis.from_url(settings.redis_url), settings.redis_key_prefix
    )
    print(f"Redis prefix: {settings.redis_key_prefix or '(none)'}")
    try:
        requested = tuple(sys.argv[1:])
        result = await refresh_wiki_corpus(
            qdrant, redis, settings, requested or None
        )
        specialists = result.get("specialists") or {}
        abilities = specialists.get("abilities") or {}
        print(
            f"Refreshed {len(result['hubs'])} Qdrant hubs and "
            f"{sum(abilities.values()) if isinstance(abilities, dict) else 0} "
            f"stored abilities at {result['refreshed_at']}; "
            f"next due {result['next_due_at']}"
        )
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
