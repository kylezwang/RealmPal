"""Veteran biome potion farms and wiki drop locations."""
from __future__ import annotations

import json

from api.services.biomes import (
    SURVEY_NAME,
    compose_biome_brief,
    extract_biome_query,
    merge_biome_entries,
    named_biome,
    potions_from_text,
)
from api.services.dungeon_guide import (
    PAGE_CACHE_PREFIX,
    extract_dungeon_query,
    match_index_pages,
)
from api.services.stored_answers import try_stored_reply

FLORAL_LEAD = (
    "Floral Escape is a Veteran biome in the northern portion of the realm. "
    "Potions of Life, Speed and Vitality drop often in this biome. "
    "The biome UT obtainable from Floral Escape is Pollen Incendiary."
)
SANGUINE_LEAD = (
    "Sanguine Forest is a Veteran biome in the northern portion of the realm. "
    "Life, Attack and Wisdom potions are easily obtainable in this biome."
)
CARBON_LEAD = (
    "The Carboniferous is a Veteran biome found in the uppermost half of the Realm. "
    "The enemies within this biome are a rich source of Potions of Vitality, "
    "Wisdom, Speed, Dexterity, Defense, and Mana."
)


def test_named_biome_and_carniferous_typo():
    assert named_biome("Guide to complete Carboniferous") == "Carboniferous"
    assert named_biome("what potions in carniferous") == "Carboniferous"
    assert named_biome("Floral Escape life pots") == "Floral Escape"
    assert named_biome("Sanguine Forest") == "Sanguine Forest"
    assert named_biome("best attack bard") is None
    assert named_biome("Abyss of Demons") is None


def test_extract_biome_survey_from_live_question():
    query = extract_biome_query("What veteran biomes drop what potions")
    assert query is not None
    assert query.survey is True
    assert query.name == SURVEY_NAME
    assert query.potion is None


def test_extract_named_biome_potion_ask():
    query = extract_biome_query("what potions drop in floral escape")
    assert query is not None
    assert query.name == "Floral Escape"
    assert query.survey is False


def test_dungeon_extract_sees_biome_without_guide_verb():
    assert extract_dungeon_query("floral escape potions") == "Floral Escape"
    assert extract_dungeon_query("how to do carboniferous") == "carboniferous"


def test_potions_from_wiki_leads():
    assert potions_from_text(FLORAL_LEAD) == ["Life", "Speed", "Vitality"]
    assert potions_from_text(SANGUINE_LEAD) == ["Life", "Attack", "Wisdom"]
    assert potions_from_text(CARBON_LEAD) == [
        "Mana",
        "Defense",
        "Speed",
        "Dexterity",
        "Vitality",
        "Wisdom",
    ]


def test_merge_biome_entries_lets_index_match_carboniferous():
    entries = merge_biome_entries([])
    matches = match_index_pages("Carboniferous", entries)
    assert matches
    assert matches[0]["slug"] == "carboniferous"
    carn = match_index_pages("carniferous", entries)
    assert carn
    assert carn[0]["slug"] == "carboniferous"


def test_item_scraper_reads_infobox_drop_rows():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "services" / "scraper.py").read_text(
        encoding="utf-8"
    )
    assert "obtained from" in source
    assert "drops from|obtained through|dropped by|obtained from" in source
    assert "loot table" in source
    assert "drop locations?" in source
    assert "drop locations?|loot table" in source
    assert "reskin of" in source


async def test_stored_biome_survey_lists_floral_potions(redis_client, anon_settings):
    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}floral-escape",
        json.dumps(
            {
                "title": "Floral Escape",
                "text": FLORAL_LEAD,
                "url": "https://www.realmeye.com/wiki/floral-escape",
                "drops": [{"name": "Pollen Incendiary"}],
            }
        ),
    )
    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}sanguine-forest",
        json.dumps(
            {
                "title": "Sanguine Forest",
                "text": SANGUINE_LEAD,
                "url": "https://www.realmeye.com/wiki/sanguine-forest",
                "drops": [],
            }
        ),
    )
    reply = await try_stored_reply(
        redis_client,
        "What veteran biomes drop what potions",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert reply is not None
    assert reply.kind == "biome"
    assert "Floral Escape" in reply.text
    assert "Life" in reply.text
    assert "Sanguine Forest" in reply.text
    assert "Attack" in reply.text


async def test_compose_named_biome_keeps_ut(redis_client, anon_settings):
    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}floral-escape",
        json.dumps(
            {
                "title": "Floral Escape",
                "text": FLORAL_LEAD,
                "url": "https://www.realmeye.com/wiki/floral-escape",
                "drops": [{"name": "Pollen Incendiary"}],
            }
        ),
    )
    query = extract_biome_query("floral escape")
    brief = await compose_biome_brief(
        redis_client,
        query,
        ttl_seconds=anon_settings.wiki_ttl_seconds,
        cache_only=True,
    )
    assert brief
    assert "Pollen Incendiary" in brief
    assert "Life" in brief
