"""Item scaling specialist: multi-stat infobox rows and stat follow-ups."""
from __future__ import annotations

import json

import pytest

from api.models.item import ItemProfile
from api.services import item_scaling, realmshark, wiki_scaling
from api.services.wiki_scaling import write_cached_item


def _devastation_item() -> ItemProfile:
    return ItemProfile(
        name="Scepter of Devastation",
        tier="UT",
        stats={
            "On Equip": "-20 HP, +4 ATT, -5 VIT, +2 WIS",
            "Damage": "200 (+10 per WIS over 50) - 20 for each subsequent target",
            "Targets": "1 (+1 per 15 WIS over 50) targets",
            "Shockblast Damage": "250 (+25 per ATT over 65)",
            "Shockblast Targets": "1 (+1 per 15 ATT over 65) targets",
            "Shockblast Range": "0.5 (+0.05 per ATT over 65) squares",
        },
    )


def test_devastation_scales_both_wisdom_and_attack():
    scales = wiki_scaling.scaling_from_item(_devastation_item())
    assert "Wisdom" in scales
    assert "Attack" in scales
    assert "WIS" in scales["Wisdom"] or "Wis" in scales["Wisdom"]
    assert "ATT" in scales["Attack"] or "Att" in scales["Attack"]


def test_is_item_scaling_query_first_turn():
    assert item_scaling.is_item_scaling_query(
        "Scepter of Devastation does it scale off attack"
    )


def test_is_item_scaling_follow_up_without_repeating_item():
    history = ["Scepter of Devastation does it scale off attack"]
    assert item_scaling.is_item_scaling_query(
        "What about scaling off wis?", history=history
    )


def test_parse_query_follow_up_does_not_inherit_build_class_stat():
    history = [
        "Best attack ninja build",
        "Scepter of Devastation does it scale off attack",
    ]
    class_name, stat, _buildish = realmshark.parse_query(
        "What about scaling off wis?", history=history
    )
    assert class_name is None
    assert stat == "Wisdom"


@pytest.mark.asyncio
async def test_retrieve_item_scaling_brief_wis_follow_up(redis_client):
    item = _devastation_item()
    await write_cached_item(redis_client, item, 3600)
    history = ["Scepter of Devastation does it scale off attack"]
    text = await item_scaling.retrieve_item_scaling_brief(
        redis_client,
        "What about scaling off wis?",
        ttl_seconds=60,
        history=history,
        cache_only=True,
    )
    assert "Scepter of Devastation" in text
    assert "Wisdom" in text
    assert "Attack" in text
    assert "User asked about Wisdom: yes" in text
    assert "item family" in text.lower()


@pytest.mark.asyncio
async def test_retrieve_build_knowledge_item_scale_follow_up(redis_client):
    item = _devastation_item()
    await write_cached_item(redis_client, item, 3600)
    history = ["Scepter of Devastation does it scale off attack"]
    text = await realmshark.retrieve_build_knowledge(
        redis_client,
        "What about scaling off wis?",
        ttl_seconds=60,
        history=history,
    )
    assert "ITEM SCALING AGENT" in text
    assert "Wisdom" in text
