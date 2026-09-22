"""Forge specialist: shiny forging must not be answered from enchanting."""
from __future__ import annotations

import json

import pytest

from api.services import enchanting, forging, realmshark
from api.services.forging import CACHE_KEY
from api.services.slot_graph import route_slots


def _forge_store() -> dict:
    return {
        "title": "Forge",
        "url": "https://www.realmeye.com/wiki/forge",
        "overview": "The Forge exchanges UT and ST items for others.",
        "sections": [
            {
                "heading": "Materials",
                "text": "UTs use Common, Rare, and Legendary materials.",
                "tables": [],
            },
            {
                "heading": "Forgefire",
                "text": "500 per day, cap 2000.",
                "tables": [],
            },
            {
                "heading": "Upgrading",
                "text": (
                    "Shiny base items cannot be used to craft nonshiny upgrades. "
                    "Spirit Dagger upgrades to Mischief."
                ),
                "tables": [
                    {
                        "rows": [
                            [
                                "Moonlight Village",
                                "Spirit Dagger",
                                "Concentrated Soul Fire",
                                "Mischief",
                            ],
                        ]
                    }
                ],
            },
            {
                "heading": "Exclusive/Limited Items",
                "text": (
                    "Most Shiny Items cannot be forged, and when dismantled provide "
                    "the same Material value as their normal counterparts. "
                    "The only shiny items that can be forged are upgraded versions."
                ),
                "tables": [],
            },
        ],
    }


@pytest.fixture
async def forge_redis(redis_client):
    await redis_client.set(
        CACHE_KEY, json.dumps(_forge_store()), ex=3600
    )
    return redis_client


def test_screenshot_question_is_forge_not_enchant():
    msg = "Is shiny forging possible?"
    assert forging.is_forge_query(msg)
    assert not enchanting.is_enchant_query(msg)


@pytest.mark.parametrize(
    "message",
    [
        "is shiny forgin possible",
        "can the blacksmith make shinies",
        "how much forgefire do I get",
        "how do I dismantl a ut",
    ],
)
def test_forge_query_typos_and_aliases(message: str):
    assert forging.is_forge_query(message)


@pytest.mark.parametrize(
    "message",
    [
        "what enchants on qot",
        "Shiny divine awakened snake eye ring",
        "show me shiny divine huntress set",
    ],
)
def test_forge_query_negative_cases(message: str):
    assert not forging.is_forge_query(message)


def test_enchantment_orb_forge_does_not_dual_route_enchant():
    msg = "how do I forge Enchantment Orb"
    assert forging.is_forge_query(msg)
    assert not forging._enchant_signal_besides_orb(msg)


@pytest.mark.asyncio
async def test_retrieve_forging_brief_shiny_question(forge_redis):
    text = await forging.retrieve_forging_brief(
        forge_redis,
        "Is shiny forging possible?",
        ttl_seconds=60,
        cache_only=True,
    )
    assert "Source: https://www.realmeye.com/wiki/forge" in text
    assert "Source: https://www.realmeye.com/wiki/enchanting" not in text
    assert "cannot be forged" in text.lower() or "Most Shiny" in text
    assert "upgraded" in text.lower() or "only shiny" in text.lower()


@pytest.mark.asyncio
async def test_retrieve_forging_brief_named_upgrade(forge_redis):
    text = await forging.retrieve_forging_brief(
        forge_redis,
        "Can I upgrade Spirit Dagger to Mischief at the forge?",
        ttl_seconds=60,
        cache_only=True,
    )
    assert "Spirit Dagger" in text
    assert "Mischief" in text
    assert "nonshiny" in text.lower() or "non-shiny" in text.lower()


@pytest.mark.asyncio
async def test_retrieve_forging_brief_empty_store(redis_client):
    text = await forging.retrieve_forging_brief(
        redis_client,
        "Is shiny forging possible?",
        ttl_seconds=60,
        cache_only=True,
    )
    assert "empty" in text.lower()
    assert "enchanting" in text.lower()


@pytest.mark.asyncio
async def test_retrieve_build_knowledge_forge_only(forge_redis):
    text = await realmshark.retrieve_build_knowledge(
        forge_redis,
        "Is shiny forging possible?",
        ttl_seconds=60,
    )
    assert "FORGE AGENT" in text
    assert "wiki/forge" in text


def test_route_slots_forge_only():
    slots, depth = route_slots("Is shiny forging possible?", None, None)
    assert slots == ["forge"]
    assert depth == "deep"


def test_route_slots_enchantment_orb_forge_only():
    slots, _depth = route_slots("how do I forge Enchantment Orb", None, None)
    assert slots == ["forge"]
    assert "enchantment" not in slots
