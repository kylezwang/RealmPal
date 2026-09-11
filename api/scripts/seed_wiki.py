"""
Seed the foundational RealmEye equipment wiki hubs into Qdrant.

Run from repo root:
  cd api && ..\\.venv\\Scripts\\python.exe -m scripts.seed_wiki
  (or set PYTHONPATH to repo root and run: python -m api.scripts.seed_wiki)
"""
import asyncio
import sys
from pathlib import Path

# Allow running as `python api/scripts/seed_wiki.py` from repo root.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qdrant_client import AsyncQdrantClient

from api.config import get_settings
from api.services.ingestion import seed_wiki_hubs


async def main() -> None:
    settings = get_settings()
    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    # Optional positional slugs let us seed only newly-added sources without
    # re-scraping and re-embedding every existing hub:
    #   python api/scripts/seed_wiki.py daggers dual-blades
    requested_slugs = tuple(sys.argv[1:])
    counts = await seed_wiki_hubs(client, requested_slugs) if requested_slugs else await seed_wiki_hubs(client)
    print(f"Seeded {len(counts)} wiki hubs: {', '.join(counts.keys())}")


if __name__ == "__main__":
    asyncio.run(main())
