"""Wiki name list is compiled from cache and matched without a scrape."""
from __future__ import annotations

import json

import pytest

from api.models.build import CLASS_ALIASES
from api.services.dungeon_guide import PAGE_CACHE_PREFIX
from api.services.game_names import (
    GAME_NAMES_KEY,
    compile_index,
    match_message_terms,
    match_terms,
    rebuild_game_names,
)
from api.services.wiki_scaling import HUB_PREFIX


def test_unique_boss_token_matches_and_shared_words_do_not():
    index = compile_index(
        bosses=[
            {"name": "Thessal the Mermaid Goddess", "where": "Ocean Trench"},
            {"name": "The Forgotten King", "where": "The Shatters"},
            {"name": "The Puppet Master", "where": "The Shatters"},
        ],
        classes=list(CLASS_ALIASES.items()),
    )
    assert index["thessal"]["kind"] == "boss"
    assert index["thessal"]["where"] == "Ocean Trench"
    assert "king" not in index
    assert "spell" not in index
    assert index["wizard"]["kind"] == "class"
    assert index["wiz"]["name"] == "Wizard"
    hits = match_terms("who is thessal", index)
    assert hits[0]["name"] == "Thessal the Mermaid Goddess"
    assert match_terms("how much damage does my staff do", index) == []


def test_longest_phrase_wins():
    index = compile_index(
        dungeons=[{"title": "Ocean Trench", "aliases": ["ocean", "trench"]}]
    )
    hits = match_terms("loot from ocean trench", index)
    assert len(hits) == 1
    assert hits[0]["matched"] == "ocean trench"
    assert hits[0]["kind"] == "dungeon"


@pytest.mark.asyncio
async def test_rebuild_reads_cache_and_does_not_scrape(redis_client, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("game name rebuild must not scrape")

    monkeypatch.setattr("api.services.scraper.scrape_wiki_article", boom)
    monkeypatch.setattr("api.services.scraper.scrape_dungeon_indexes", boom)
    monkeypatch.setattr("api.services.scraper.scrape_player_profile", boom)
    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}ocean-trench",
        json.dumps(
            {
                "title": "Ocean Trench",
                "drops": [
                    {"name": "Coral Bow", "drops_from": "Thessal the Mermaid Goddess"}
                ],
            }
        ),
    )
    await redis_client.set(
        f"{HUB_PREFIX}:staves",
        json.dumps([{"name": "Staff of Extreme Prejudice"}]),
    )
    counts = await rebuild_game_names(redis_client)
    assert counts["boss"] >= 1
    assert counts["item"] >= 1
    assert counts["class"] >= 16
    assert await redis_client.get(GAME_NAMES_KEY)
    hits = await match_message_terms(redis_client, "who is thessal")
    assert hits[0]["kind"] == "boss"
    assert hits[0]["where"] == "Ocean Trench"
    staff = await match_message_terms(
        redis_client, "is Staff of Extreme Prejudice worth it"
    )
    assert staff[0]["kind"] == "item"
    assert await match_message_terms(redis_client, "how much damage does my staff do") == []
