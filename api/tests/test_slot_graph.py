"""route_slots: which slot agents run for a given message/class/stat.

A named shiny/divine set ("full shiny divine Crown, Robe, Bow, and Ring")
already routed to the single "set" agent. A shiny/divine class+stat ask
with no items named ("full shiny divine attack huntress") must route the
same way - found live Sep 14, right after "attack huntress" stopped being
misread as a literal item name (stored_answers._shiny_divine_item_name's
bare-stat-and-class guard): the message correctly stopped 404ing, but
route_slots still sent it down the generic weapon/ability/armor/ring
brief path instead of the set visualizer the wording actually asked for.
"""
from __future__ import annotations

from api.services.slot_graph import route_slots


def test_named_shiny_divine_set_routes_to_set_agent_only():
    slots, depth = route_slots(
        "full shiny divine Crown, Robe, Bow, and Ring of Decades",
        None,
        None,
    )
    assert slots == ["set"]
    assert depth == "deep"


def test_shiny_divine_class_stat_with_no_named_items_routes_to_set_agent():
    slots, depth = route_slots(
        "Show me full shiny divine attack huntress", "Huntress", "Attack"
    )
    assert slots == ["set"]
    assert depth == "deep"


def test_plain_build_ask_with_no_shiny_divine_wording_stays_on_gear_agents():
    """Baseline: must not regress the ordinary balanced-loadout path."""
    slots, depth = route_slots("best items for a dex huntress", "Huntress", "Dexterity")
    assert set(slots) == {"weapon", "ability", "armor", "ring", "enchantment"}
    assert depth == "brief"


def test_shiny_divine_with_no_resolved_class_stat_does_not_force_set_agent():
    slots, _depth = route_slots("shiny divine please", None, None)
    assert "set" not in slots


def test_enchant_comparison_of_two_nicknames_also_routes_dps():
    slots, depth = route_slots(
        "is cbow awakening or lbow awakening better", None, None
    )
    assert slots == ["enchantment", "dps"]
    assert depth == "deep"


def test_skin_followup_with_history_routes_to_skin_agent():
    slots, depth = route_slots(
        "And small sentinel cloth too",
        "Archer",
        None,
        history=[
            "What does Vampire Slayer Archer look like with sentinel cloth?",
        ],
    )
    assert slots == ["skin"]
    assert depth == "deep"
