"""Replay a DPS conversation turn by turn and report what context each turn got.

Mirrors how api/routers/chat.py builds `user_history` (user messages only,
last 10) so a follow-up can be checked for the DPS brief without spending a
Claude call.

Usage:
    api/.venv/Scripts/python.exe api/scripts/probe_dps_followup.py
"""
from __future__ import annotations

import asyncio
import sys

import redis.asyncio as aioredis

from api.config import Settings
from api.services.dps_specialist import (
    is_dps_follow_up,
    is_dps_query,
    is_stat_number_query,
)
from api.services.player_lookup import extract_player_ign
from api.services.realmshark import parse_query, retrieve_build_knowledge
from api.services.slot_graph import route_slots

TURNS = [
    "What's the DPS for Turbine's bard?",
    "What do the numbers look like?",
    "Can you give me a breakdown?",
    "What if he swapped to a Doom Bow?",
    "How does that compare to the top Bard on the leaderboard?",
]


async def main() -> None:
    turns = sys.argv[1:] or TURNS
    settings = Settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    history: list[str] = []
    try:
        for message in turns:
            class_name, stat, buildish = parse_query(message, history=history)
            ign = extract_player_ign(message, history=history)
            slots, depth = route_slots(
                message, class_name, stat, player_ign=ign, history=history
            )
            ctx = await retrieve_build_knowledge(
                redis,
                message,
                ttl_seconds=settings.wiki_ttl_seconds,
                player_ttl_seconds=120,
                history=history,
            )
            has_player_set = "PLAYER SET DPS" in ctx
            has_recon = "Wiki reconstruct for" in ctx
            print("=" * 78)
            print(f"TURN {len(history) + 1}: {message}")
            print(
                f"  parse_query -> class={class_name} stat={stat} buildish={buildish}"
            )
            print(f"  extract_player_ign -> {ign!r}")
            print(f"  is_dps_query={is_dps_query(message, history=history)} "
                  f"is_stat_number_query="
                  f"{is_stat_number_query(message, history=history)} "
                  f"follow_up={is_dps_follow_up(message, history=history)}")
            print(f"  route_slots -> slots={slots} depth={depth}")
            print(f"  build_ctx chars={len(ctx)} "
                  f"PLAYER_SET_DPS={has_player_set} RECONSTRUCT={has_recon}")
            if has_recon:
                for line in ctx.splitlines():
                    if line.startswith("Wiki reconstruct for"):
                        print(f"  -> {line}")
            history.append(message)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
