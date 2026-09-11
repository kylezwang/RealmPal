"""
Seed RealmShark DPS ability-scaling graph + top-5 loadouts into Qdrant.

Run from repo root:
  python -m api.scripts.seed_dps
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qdrant_client import AsyncQdrantClient

from api.config import get_settings
from api.services.ingestion import seed_dps_knowledge


async def main() -> None:
    settings = get_settings()
    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    count = await seed_dps_knowledge(client)
    print(f"Seeded {count} RealmShark DPS builds into Qdrant")


if __name__ == "__main__":
    asyncio.run(main())
