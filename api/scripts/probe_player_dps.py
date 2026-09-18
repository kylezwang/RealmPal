"""Print the DPS specialist's brief for a named player's class, no Claude call.

Usage (from the repo root, with Redis up):
    api/.venv/Scripts/python.exe api/scripts/probe_player_dps.py Turbine bard necro
"""
from __future__ import annotations

import asyncio
import sys

import redis.asyncio as aioredis

from api.config import Settings
from api.models.build import CLASS_ALIASES
from api.services.dps_specialist import retrieve_dps_brief


def canonical_class(token: str) -> str | None:
    low = token.strip().lower()
    for canon, aliases in CLASS_ALIASES.items():
        if low == canon.lower() or low in {a.lower() for a in aliases}:
            return canon
    return None


async def main() -> None:
    args = sys.argv[1:]
    ign = args[0] if args else "Turbine"
    classes = args[1:] or ["bard"]
    settings = Settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        for token in classes:
            class_name = canonical_class(token)
            message = f"What's the DPS for {ign}'s {token}?"
            print("=" * 78)
            print(f"PROMPT: {message}   (class_name={class_name})")
            print("=" * 78)
            brief = await retrieve_dps_brief(
                redis,
                message,
                ttl_seconds=settings.wiki_ttl_seconds,
                class_name=class_name,
                player_ign=ign,
                player_ttl_seconds=120,
                cache_only=True,
            )
            print(brief or "(empty brief)")
            print()
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
