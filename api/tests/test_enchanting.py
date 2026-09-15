"""Enchant recommendations should infer a stat from an item's own base
stats when the player doesn't name one, same as the pricing/backlog work
this file accompanies. See BACKLOG.md for the product ask: a +20 Attack
item implies an Attack build, so recommend Attack-focused enchants."""
from __future__ import annotations

import json

from api.models.item import ItemProfile
from api.services import enchanting, realmshark, wiki_scaling


def _rolls_store() -> dict:
    return {
        "rolls": [
            {
                "name": "Attack Bonus",
                "eligible": "ALL",
                "effects": "+1 ATT",
                "category": "Attack",
            },
            {
                "name": "Dexterity Bonus",
                "eligible": "ALL",
                "effects": "+1 DEX",
                "category": "Dexterity",
            },
        ]
    }


def test_infer_item_base_stat_reads_on_equip_bonus():
    item = ItemProfile(
        name="Cackling Straitjacket",
        tier="UT",
        stats={"On Equip": "+20 ATT"},
    )
    assert wiki_scaling.infer_item_base_stat(item) == "Attack"


def test_infer_item_base_stat_ignores_scaling_only_items():
    item = ItemProfile(
        name="Grandmaster Mace",
        tier="7",
        stats={"Damage": "275-305 (+5.2 for every WIS above 55)"},
    )
    assert wiki_scaling.infer_item_base_stat(item) is None


def test_infer_item_base_stat_returns_none_on_tie():
    item = ItemProfile(
        name="Dual Stat Trinket",
        tier="UT",
        stats={"On Equip": "+8 ATT, +8 DEX"},
    )
    assert wiki_scaling.infer_item_base_stat(item) is None


def test_infer_class_primary_stat_picks_most_common_scaling():
    payload = {
        "abilities": [
            {"name": "A", "scales": {"Dexterity": "..."}},
            {"name": "B", "scales": {"Dexterity": "..."}},
            {"name": "C", "scales": {"Wisdom": "..."}},
        ]
    }
    assert wiki_scaling.infer_class_primary_stat(payload) == "Dexterity"


def test_infer_class_primary_stat_none_on_tie_or_empty():
    assert wiki_scaling.infer_class_primary_stat({"abilities": []}) is None
    assert wiki_scaling.infer_class_primary_stat(None) is None
    tied = {
        "abilities": [
            {"name": "A", "scales": {"Dexterity": "..."}},
            {"name": "B", "scales": {"Wisdom": "..."}},
        ]
    }
    assert wiki_scaling.infer_class_primary_stat(tied) is None


def test_awakened_row_without_eligible_cell_is_never_slot_generic():
    """Regression: RealmEye's Awakened Enchantments table has no
    Eligible/slot column at all (each one only rolls on one or a few named
    items, e.g. Infernal Anger is exclusive to Berserker's Breastplate).
    _normalize_row used to default the missing cell to ALL, so it looked
    generically eligible for any weapon/armor/ability/ring. Found live
    Sep 14: recommended for a generic Attack Kensei build."""
    row = [
        "Infernal Anger",
        "Gain 6 Attack and take 5% less damage.",
        "AWAKENEDATTACKSINGLESTATDURABILITYDAMAGERESISTANCE",
        "AWAKENEDATTACKSINGLESTATDURABILITYDAMAGERESISTANCE",
    ]
    parsed = enchanting._normalize_row(row, "Awakened Enchantments")
    assert parsed is not None
    assert parsed["eligible"] != "ALL"
    # Never a generic match, even when the caller doesn't know the slot yet.
    assert enchanting._eligible_ok(parsed["eligible"], None) is False
    assert enchanting._eligible_ok(parsed["eligible"], "armor") is False
    assert enchanting._eligible_ok(parsed["eligible"], "weapon") is False


def test_basic_enchant_row_missing_eligible_cell_still_defaults_to_all():
    """Only Awakened rows get the item-locked treatment - a stray row from
    a normal table missing its eligible cell keeps the old ALL default."""
    row = ["Attack Bonus", "+1 ATT"]
    parsed = enchanting._normalize_row(row, "Basic Enchantments")
    assert parsed is not None
    assert parsed["eligible"] == "ALL"


def test_awakened_enchant_excluded_from_a_generic_attack_build_query():
    rolls = [
        {
            "name": "Infernal Anger",
            "eligible": "AWAKENED_ITEM_LOCKED",
            "effects": "Gain 6 Attack and take 5% less damage.",
            "category": "Awakened Enchantments",
        },
        {
            "name": "Attack Bonus",
            "eligible": "ALL",
            "effects": "+1 ATT",
            "category": "Basic Enchantments",
        },
    ]
    matched = enchanting.filter_rolls(rolls, stat="Attack", slot="weapon")
    names = [r["name"] for r in matched]
    assert "Attack Bonus" in names
    assert "Infernal Anger" not in names


async def test_retrieve_enchanting_brief_infers_stat_from_item(
    redis_client, monkeypatch
):
    await redis_client.set(enchanting.CACHE_KEY, json.dumps(_rolls_store()))
    await wiki_scaling.write_cached_item(
        redis_client,
        ItemProfile(
            name="Cackling Straitjacket",
            tier="UT",
            stats={"On Equip": "+20 ATT"},
        ),
        60,
    )
    monkeypatch.setattr(
        enchanting, "extract_enchant_item", lambda message: "Cackling Straitjacket"
    )

    text = await enchanting.retrieve_enchanting_brief(
        redis_client,
        "what enchants should I get on Cackling Straitjacket",
        ttl_seconds=60,
        cache_only=True,
    )
    assert "No stat was named" in text
    assert "Attack" in text
    assert "Attack Bonus" in text
    assert "Dexterity Bonus" not in text


async def test_retrieve_enchanting_brief_respects_explicit_stat_over_item(
    redis_client, monkeypatch
):
    await redis_client.set(enchanting.CACHE_KEY, json.dumps(_rolls_store()))
    await wiki_scaling.write_cached_item(
        redis_client,
        ItemProfile(
            name="Cackling Straitjacket",
            tier="UT",
            stats={"On Equip": "+20 ATT"},
        ),
        60,
    )
    monkeypatch.setattr(
        enchanting, "extract_enchant_item", lambda message: "Cackling Straitjacket"
    )

    text = await enchanting.retrieve_enchanting_brief(
        redis_client,
        "what dex enchants should I get on Cackling Straitjacket",
        ttl_seconds=60,
        stat="Dexterity",
        cache_only=True,
    )
    assert "No stat was named" not in text
    assert "Requested stat: Dexterity" in text
    assert "Dexterity Bonus" in text
    assert "Attack Bonus" not in text


async def test_full_build_enchant_infers_class_primary_stat_without_named_stat(
    redis_client, monkeypatch
):
    """'Best Kensei build' names no stat; enchants should still target the
    stat Kensei's own abilities scale with instead of being dropped."""
    payload = {
        "class_name": "Kensei",
        "hub_url": "https://www.realmeye.com/wiki/sheaths",
        "abilities": [
            {
                "name": "Test Sheath",
                "wiki_url": "",
                "tier": "UT",
                "scales": {"Dexterity": "Damage: 100 (+5 per DEX over 32)"},
                "effects": "",
            }
        ],
    }
    await redis_client.set(f"{wiki_scaling.CACHE_PREFIX}:kensei", json.dumps(payload))
    await redis_client.set(enchanting.CACHE_KEY, json.dumps(_rolls_store()))

    async def boom(*args, **kwargs):
        raise AssertionError("must not live-scrape")

    from api.models.build import StatScalingGraph

    async def fake_graph(*args, **kwargs):
        return StatScalingGraph(season="test", edges=[])

    monkeypatch.setattr(realmshark, "run_slot_agents", boom)
    monkeypatch.setattr(realmshark, "load_graph", fake_graph)
    monkeypatch.setattr(wiki_scaling, "load_class_wiki_scaling", boom)

    text = await realmshark.retrieve_build_knowledge(
        redis_client,
        "best kensei build",
        ttl_seconds=60,
    )
    assert "No stat was named" in text
    assert "Kensei's abilities mostly scale with Dexterity" in text
    assert "Dexterity Bonus" in text
    assert "Attack Bonus" not in text
