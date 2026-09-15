"""Specialists read a full stored wiki hub, not a live first-page scrape."""
from __future__ import annotations

import json

from api.models.item import ItemProfile
from api.services import realmshark, wiki_scaling
from api.models.build import StatScalingGraph


async def test_specialist_store_status_lists_every_class(redis_client):
    await redis_client.set(
        f"{wiki_scaling.CACHE_PREFIX}:huntress",
        json.dumps({"class_name": "Huntress", "abilities": [{"name": "Lotus"}]}),
    )
    rows = await wiki_scaling.specialist_store_status(redis_client)
    by_name = {row["class_name"]: row for row in rows}
    assert set(by_name) == set(wiki_scaling.CLASS_ABILITY_HUB)
    assert by_name["Huntress"]["abilities"] == 1
    assert by_name["Samurai"]["abilities"] == 0


def test_summon_damage_for_every_wis_is_scaling():
    item = ItemProfile(
        name="Grandmaster Mace",
        tier="7",
        stats={"Damage": "275-305 (+5.2 for every WIS above 55)"},
    )
    scales = wiki_scaling.scaling_from_item(item)
    assert "Wisdom" in scales
    assert "5.2" in scales["Wisdom"]


async def test_summoner_store_keeps_wisdom_maces(redis_client, monkeypatch):
    hub = [
        {"name": "Grandmaster Mace", "tier": "T7"},
        {"name": "Crystal Mace", "tier": "UT"},
        {"name": "Mechanical Mace", "tier": "UT"},
    ]

    async def fake_hub(redis, slug, ttl, *, force=False):
        return hub

    async def fake_profiles(redis, names, ttl, *, force=False):
        by_name = {
            "Grandmaster Mace": ItemProfile(
                name="Grandmaster Mace",
                tier="7",
                stats={"Damage": "275-305 (+5.2 for every WIS above 55)"},
            ),
            "Crystal Mace": ItemProfile(
                name="Crystal Mace",
                tier="UT",
                stats={"Damage": "50-70 (+3 per DEX over 32)", "Shots": "5"},
            ),
            "Mechanical Mace": ItemProfile(
                name="Mechanical Mace",
                tier="UT",
                stats={"Reactive Proc(s)": "On Ability use: Summons an Exalted Oryx Eye."},
            ),
        }
        return [by_name[name] for name in names if name in by_name]

    monkeypatch.setattr(wiki_scaling, "_hub_index", fake_hub)
    monkeypatch.setattr(wiki_scaling, "_profiles_for_names", fake_profiles)

    payload = await wiki_scaling.load_class_wiki_scaling(
        redis_client, "Summoner", ttl_seconds=60, force=True
    )
    names = {row["name"] for row in payload["abilities"]}
    assert "Grandmaster Mace" in names
    text = wiki_scaling.format_wiki_scaling(payload, stat="Wisdom")
    assert "Grandmaster Mace" in text


def _dex_trap(name: str) -> ItemProfile:
    return ItemProfile(
        name=name,
        tier="UT",
        stats={"Damage": "675 (+14 per DEX over 32)"},
    )


def _plain_trap(name: str, *, tier: str = "UT") -> ItemProfile:
    return ItemProfile(name=name, tier=tier, stats={"Damage": "200"})


async def test_warm_scrape_keeps_every_dex_trap(redis_client, monkeypatch):
    hub = (
        [{"name": "Coral Venom Trap", "tier": "T7"}]
        + [{"name": f"UT Trap {i}", "tier": "UT"} for i in range(10)]
        + [
            {"name": "Lifebringing Lotus", "tier": "UT"},
            {"name": "Honeytomb Snare", "tier": "UT"},
        ]
    )
    fetched: list[str] = []

    async def fake_hub(redis, slug, ttl, *, force=False):
        return hub

    async def fake_profiles(redis, names, ttl, *, force=False):
        fetched.extend(names)
        items = []
        for name in names:
            if name in {"Lifebringing Lotus", "Honeytomb Snare"}:
                items.append(_dex_trap(name))
            else:
                items.append(
                    _plain_trap(name, tier="T7" if "Coral" in name else "UT")
                )
        return items

    monkeypatch.setattr(wiki_scaling, "_hub_index", fake_hub)
    monkeypatch.setattr(wiki_scaling, "_profiles_for_names", fake_profiles)

    payload = await wiki_scaling.load_class_wiki_scaling(
        redis_client, "Huntress", ttl_seconds=60, force=True
    )
    names = {row["name"] for row in payload["abilities"]}
    assert "Lifebringing Lotus" in names
    assert "Honeytomb Snare" in names
    assert fetched[-2:] == ["Lifebringing Lotus", "Honeytomb Snare"]

    text = wiki_scaling.format_wiki_scaling(payload, stat="Dexterity")
    assert "Lifebringing Lotus" in text
    assert "Honeytomb Snare" in text


async def test_limited_reskin_traps_are_not_stored(redis_client, monkeypatch):
    hub = [
        {"name": "Lifebringing Lotus", "tier": "ST"},
        {"name": "Consecrated Trap", "tier": "ST (Limited)"},
        {"name": "Honeytomb Snare", "tier": "ST"},
    ]

    async def fake_hub(redis, slug, ttl, *, force=False):
        return hub

    async def fake_profiles(redis, names, ttl, *, force=False):
        items = []
        for name in names:
            tier = "ST (Limited)" if name == "Consecrated Trap" else "ST"
            items.append(
                ItemProfile(
                    name=name,
                    tier=tier,
                    stats={"Damage": "675 (+14 per DEX over 32)"},
                )
            )
        return items

    monkeypatch.setattr(wiki_scaling, "_hub_index", fake_hub)
    monkeypatch.setattr(wiki_scaling, "_profiles_for_names", fake_profiles)

    payload = await wiki_scaling.load_class_wiki_scaling(
        redis_client, "Huntress", ttl_seconds=60, force=True
    )
    names = {row["name"] for row in payload["abilities"]}
    assert names == {"Lifebringing Lotus", "Honeytomb Snare"}


async def test_build_knowledge_reads_store_not_live_wiki(redis_client, monkeypatch):
    payload = {
        "class_name": "Huntress",
        "hub_url": "https://www.realmeye.com/wiki/traps",
        "abilities": [
            {
                "name": "Lifebringing Lotus",
                "wiki_url": "",
                "tier": "UT",
                "scales": {"Dexterity": "Damage: 675 (+14 per DEX over 32)"},
                "effects": "Berserk, Healing",
            },
            {
                "name": "Honeytomb Snare",
                "wiki_url": "",
                "tier": "UT",
                "scales": {"Dexterity": "Damage: 400 (+10 per DEX over 32)"},
                "effects": "",
            },
        ],
    }
    await redis_client.set(
        f"{wiki_scaling.CACHE_PREFIX}:huntress", json.dumps(payload)
    )

    called = {"n": 0}

    async def boom(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("chat must not live-scrape the wiki")

    async def fake_graph(*args, **kwargs):
        return StatScalingGraph(season="test", edges=[])

    monkeypatch.setattr(realmshark, "run_slot_agents", boom)
    monkeypatch.setattr(realmshark, "load_graph", fake_graph)
    monkeypatch.setattr(wiki_scaling, "load_class_wiki_scaling", boom)

    text = await realmshark.retrieve_build_knowledge(
        redis_client,
        "Best items for a Dex Huntress",
        ttl_seconds=60,
    )
    assert "Lifebringing Lotus" in text
    assert "Honeytomb Snare" in text
    assert called["n"] == 0


async def test_build_knowledge_routes_shiny_divine_class_stat_to_set_visualizer(
    redis_client, monkeypatch
):
    """Regression: found live Sep 14, right after "attack huntress" stopped
    being misread as a literal item name - "show me full shiny divine
    attack huntress" then fell through to the generic weapon/ability/armor/
    ring text brief (this same function's RealmShark-graph tail) instead of
    the set visualizer's item-circle loadout, which only ever ran for
    explicitly-named sets. Must now route through run_slot_agents (the set
    agent resolves the build's top items itself) same as a named set does,
    not the plain-text graph branch below."""
    called: dict[str, object] = {}

    async def fake_run_slot_agents(redis, message, **kwargs):
        called["message"] = message
        called["class_name"] = kwargs.get("class_name")
        called["stat"] = kwargs.get("stat")
        return "SET VISUALIZER stub"

    async def boom(*args, **kwargs):
        raise AssertionError("must not fall through to the plain-text graph branch")

    monkeypatch.setattr(realmshark, "run_slot_agents", fake_run_slot_agents)
    monkeypatch.setattr(realmshark, "load_graph", boom)

    text = await realmshark.retrieve_build_knowledge(
        redis_client,
        "Show me full shiny divine attack huntress",
        ttl_seconds=60,
    )
    assert text == "SET VISUALIZER stub"
    assert called["class_name"] == "Huntress"
    assert called["stat"] == "Attack"


async def test_ability_brief_cache_only_does_not_scrape(redis_client, monkeypatch):
    await redis_client.set(
        f"{wiki_scaling.CACHE_PREFIX}:huntress",
        json.dumps(
            {
                "class_name": "Huntress",
                "abilities": [
                    {
                        "name": "Lifebringing Lotus",
                        "tier": "UT",
                        "scales": {"Dexterity": "per DEX"},
                    }
                ],
            }
        ),
    )

    async def boom(*args, **kwargs):
        raise AssertionError("ability agent must not live-scrape")

    monkeypatch.setattr(wiki_scaling, "load_class_wiki_scaling", boom)
    text = await wiki_scaling.retrieve_ability_brief(
        redis_client, "Huntress", stat="Dexterity", ttl_seconds=60, cache_only=True
    )
    assert "Lifebringing Lotus" in text


async def test_top_build_items_picks_one_item_per_slot(redis_client, monkeypatch):
    """top_build_items backs the shiny/divine "full build" set visualizer
    (found live Sep 14: "show me full shiny divine attack huntress" landed
    on the multi-paragraph balanced-loadout brief instead of a set
    visualization once "attack huntress" stopped being misread as a literal
    item name). It must read the exact same hub/ability data the text
    briefs already use and pick the #1 item for each gear slot."""
    hub_rows = {
        "bows": [{"name": "Doom Bow", "tier": "UT", "bonus": "+11 ATT"}],
        "longbows": [],
        "leather-armors": [
            {"name": "Puppy's Collar", "tier": "UT", "bonus": "+10 ATT"}
        ],
        "attack-rings": [
            {"name": "Ring of Decades", "tier": "UT", "bonus": "+9 ATT"}
        ],
        "rings": [],
    }

    async def fake_hub_index(redis, slug, ttl, *, cache_only=False, force=False):
        return hub_rows.get(slug, [])

    monkeypatch.setattr(wiki_scaling, "_hub_index", fake_hub_index)

    await redis_client.set(
        f"{wiki_scaling.CACHE_PREFIX}:huntress",
        json.dumps(
            {
                "class_name": "Huntress",
                "abilities": [
                    {
                        "name": "Lifebringing Lotus",
                        "tier": "UT",
                        "scales": {"Attack": "Damage: 400 (+10 per ATT over 46)"},
                        "effects": "Berserk, Healing",
                    }
                ],
            }
        ),
    )

    picks = await wiki_scaling.top_build_items(
        redis_client, "Huntress", "Attack", ttl_seconds=60, cache_only=True
    )
    assert picks["weapon"] == "Doom Bow"
    assert picks["ability"] == "Lifebringing Lotus"
    assert picks["armor"] == "Puppy's Collar"
    # Rings deliberately always lead with T7 (a guaranteed, always-available
    # choice - see retrieve_universal_rings' own header text), regardless of
    # whether a UT in the hub has a technically higher raw bonus.
    assert picks["ring"] == "Ring of Transcendent Attack"


async def test_top_build_items_skips_slots_with_no_data(redis_client, monkeypatch):
    """A class/stat combo with no matching weapon or armor should simply
    omit that slot rather than raise or invent a name."""
    async def empty_hub_index(redis, slug, ttl, *, cache_only=False, force=False):
        return []

    monkeypatch.setattr(wiki_scaling, "_hub_index", empty_hub_index)

    picks = await wiki_scaling.top_build_items(
        redis_client, "Huntress", "Wisdom", ttl_seconds=60, cache_only=True
    )
    assert "weapon" not in picks
    assert "armor" not in picks
    assert "ability" not in picks
    # Every stat has a T7 ring name, so the ring agent's fallback still
    # produces a pick even with a completely empty hub.
    assert picks.get("ring") == "Ring of Transcendent Wisdom"


async def test_dungeon_guide_cache_only_does_not_scrape(redis_client, monkeypatch):
    from api.services import dungeon_guide

    async def boom(*args, **kwargs):
        raise AssertionError("dungeon agent must not live-scrape")

    monkeypatch.setattr(dungeon_guide, "scrape_dungeon_indexes", boom)
    monkeypatch.setattr(dungeon_guide, "scrape_wiki_article", boom)
    text = await dungeon_guide.retrieve_dungeon_guide(
        redis_client, "The Shatters", ttl_seconds=60, cache_only=True
    )
    assert "could not" in text.lower() or "no page" in text.lower() or "no RealmEye" in text
