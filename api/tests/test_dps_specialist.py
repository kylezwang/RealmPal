"""DPS specialist: RealmShark numbers are truth; wiki formula scales swaps."""
from __future__ import annotations

import json

import pytest

from api.models.build import (
    AbilityScalingEdge,
    EquipmentSlot,
    ItemEnchant,
    Loadout,
    StatScalingGraph,
)
from api.models.item import ItemProfile
from api.models.player import CharacterStats, CharacterSummary, EquipmentItem, PlayerProfile
from api.services import dps_specialist, realmshark, wiki_scaling
from api.services.dps_specialist import (
    classify_enchant,
    combat_shoot_deltas,
    dps_subject_from_history,
    enchants_from_tooltip,
    estimate_weapon_dps,
    format_dps_derivation,
    format_enchant_channel,
    format_reconstruction,
    format_set_effects,
    format_slot_contributions,
    gear_stat_contribution,
    ideal_ability_enchants,
    inspect_worn_set,
    is_dps_follow_up,
    is_dps_query,
    is_stat_number_query,
    merge_named_enchants,
    parse_ability_formula,
    parse_damage_range,
    parse_gear_procs,
    parse_status_grants,
    reconstruct_ability_damage,
    reconstruct_weapon_damage,
    scale_shark_weapon,
    sheet_stats_named,
    stat_mod_multiplier,
    weapon_enchant_multipliers,
)
from api.services.realmshark import GRAPH_CACHE_KEY, LOADOUT_CACHE_PREFIX, loadouts_from_rows
from api.services.slot_graph import route_slots
from api.services.player_lookup import PLAYER_CACHE_PREFIX, extract_player_ign
from api.services.wiki_scaling import CLASS_MAXSTATS_PREFIX, ITEM_CACHE_PREFIX


def test_max_defense_necro_is_a_number_query_not_a_set_ask():
    assert is_dps_query("What's the max defense for necromancer?")
    assert is_stat_number_query("What's the max defense for necromancer?")
    assert is_stat_number_query(
        "How much defense a necromancer could have? I dont want builds, only numbers."
    )
    assert is_stat_number_query("how much dps does coral bow do?")


def test_best_dps_set_still_counts_as_a_set_ask():
    assert is_dps_query("best dps necro set")
    assert is_stat_number_query("best dps necro set") is False
    assert is_stat_number_query("best defense necro") is False


def test_route_slots_max_defense_necro_is_dps_only():
    slots, depth = route_slots(
        "What's the max defense for necromancer?", "Necromancer", "Defense"
    )
    assert slots == ["dps"]
    assert depth == "deep"


def test_plain_build_ask_still_uses_gear_agents():
    slots, depth = route_slots("best items for a dex huntress", "Huntress", "Dexterity")
    assert set(slots) == {"weapon", "ability", "armor", "ring", "enchantment"}
    assert depth == "brief"


def test_best_dps_set_appends_dps_to_gear_agents():
    slots, _depth = route_slots("best dps necro set", "Necromancer", "Attack")
    assert "dps" in slots
    assert "weapon" in slots


def test_screenshot_player_dps_prompts_are_numbers_only():
    for msg in (
        "What's the DPS for Turbine's bard?",
        "How much potential DPS does Turbine's bard have?",
    ):
        assert is_dps_query(msg)
        assert is_stat_number_query(msg)
        assert extract_player_ign(msg) == "Turbine"
        slots, depth = route_slots(msg, "Bard", None, player_ign="Turbine")
        assert slots == ["dps"]
        assert depth == "deep"
        assert "weapon" not in slots
        assert "set" not in slots
    assert extract_player_ign("What's the max defense for necromancer?") is None
    assert extract_player_ign("how much dps does coral bow do?") is None
    assert extract_player_ign("look up player Turbine") == "Turbine"


def test_tooltip_enchants_parse_flattened_html_and_unique_lines():
    names = lambda text: [enc.name.lower() for enc in enchants_from_tooltip(text)]
    assert "flurry of blows iv" in names("Divine Thousand Shot UT\nFlurry of Blows IV")
    assert "flurry of blows iv" in names("Divine Warmonger UT Flurry of Blows IV")
    assert "flurry of blows iv" in names("Divine Warmonger UT<br>Flurry of Blows IV")
    assert "stat mod multiplier iv" in names(
        "Divine The Triangle UT<br>Stat Mod Multiplier IV"
    )
    unique = names("Divine Vesture of Duality UT<br>OnHit Berserk")
    assert any("berserk" in n for n in unique)


def test_named_enchants_in_the_message_land_on_the_weapon():
    slots = [("weapon", "Warmonger", []), ("ability", "The Triangle", [])]
    merged = merge_named_enchants(slots, "Turbine's bard with Flurry of Blows IV")
    weapon = next(enc.name.lower() for _slot, _name, encs in merged if _slot == "weapon" for enc in encs)
    assert "flurry of blows iv" in weapon


def test_sheet_stat_tradeoffs_are_not_fire_rate_enchants():
    """Any 8/8-stat tradeoff is a sheet change, not APS, regardless of which pair."""
    from api.models.build import ItemEnchant, PLAYER_STATS

    pairs = (
        "Vitality -Speed Tradeoff III",
        "Attack Defense Tradeoff II",
        "DEX SPD Tradeoff I",
        "Wisdom HP Tradeoff IV",
        "Life Mana Tradeoff II",
    )
    for name in pairs:
        enc = ItemEnchant(name=name, value=name)
        assert classify_enchant(enc) == "sheet_stat", name
        assert weapon_enchant_multipliers({}, [enc]) == (1.0, 1.0), name
        named = sheet_stats_named(name)
        assert named, name
        assert all(stat in PLAYER_STATS for stat in named), name


def test_fire_rate_and_damage_tradeoffs_still_change_the_weapon_shot():
    from api.models.build import ItemEnchant

    fire = ItemEnchant(name="Fire Rate Tradeoff III", value="Fire Rate Tradeoff III")
    damage = ItemEnchant(name="Damage Tradeoff IV", value="Damage Tradeoff IV")
    flurry = ItemEnchant(name="Flurry of Blows IV", value="Flurry of Blows IV")
    assert classify_enchant(fire) == "weapon_shot"
    assert classify_enchant(damage) == "weapon_shot"
    assert classify_enchant(flurry) == "weapon_shot"
    fire_dmg, fire_rof = weapon_enchant_multipliers({}, [fire])
    assert fire_rof > 1.0
    assert fire_dmg < 1.0
    dmg, rof = weapon_enchant_multipliers({}, [damage])
    assert dmg > 1.0
    assert rof < 1.0


def test_projectile_speed_is_not_damage_or_fire_rate():
    from api.models.build import ItemEnchant

    enc = ItemEnchant(name="Projectile Speed Bonus II", value="Projectile Speed Bonus II")
    assert classify_enchant(enc) == "projectile_travel"
    assert weapon_enchant_multipliers({}, [enc]) == (1.0, 1.0)


def test_an_ability_that_scales_with_speed_uses_the_sheet_speed():
    """Sheet-stat enchants are not ignored when that stat is the scaling stat."""
    formula = {
        "stat": "Speed",
        "avg": 100.0,
        "per": 2.0,
        "threshold": 50.0,
        "shots": 1.0,
        "scales": True,
        "evidence": "test",
    }
    low = reconstruct_ability_damage(
        formula, stats={"Speed": 50, "Attack": 90, "Dexterity": 70}
    )
    high = reconstruct_ability_damage(
        formula, stats={"Speed": 80, "Attack": 90, "Dexterity": 70}
    )
    assert high is not None and low is not None
    assert high > low


def test_sheet_stat_channel_names_every_reconstruct_feed():
    from api.models.build import ItemEnchant

    vit_spd = ItemEnchant(
        name="Vitality -Speed Tradeoff III", value="Vitality -Speed Tradeoff III"
    )
    unused = format_enchant_channel(vit_spd, ability_stat="Wisdom")
    assert "sheet Vitality/Speed" in unused
    assert "does not read this stat" in unused
    assert "scales with Speed" not in unused
    used = format_enchant_channel(vit_spd, ability_stat="Speed")
    assert "scales with Speed" in used
    dex_spd = ItemEnchant(name="DEX SPD Tradeoff I", value="DEX SPD Tradeoff I")
    both = format_enchant_channel(dex_spd, ability_stat="Speed")
    assert "scales with Speed" in both
    assert "sheet Dexterity is what APS reads" in both


def test_slot_contributions_name_all_four_pieces():
    from api.models.build import ItemEnchant

    slots = [
        (
            "weapon",
            "Warmonger",
            [
                ItemEnchant(
                    name="Vitality -Speed Tradeoff III",
                    value="Vitality -Speed Tradeoff III",
                )
            ],
        ),
        ("ability", "The Triangle", []),
        ("armor", "Vesture of Duality", []),
        ("ring", "Ring of Unbound Attack", []),
    ]
    text = format_slot_contributions(
        slots, {}, {"procs": [], "grants": {}}, ability_stat="Wisdom"
    )
    for slot in ("weapon", "ability", "armor", "ring"):
        assert f"- {slot}:" in text
    assert "[item:Vesture of Duality]" in text
    assert "[item:Ring of Unbound Attack]" in text
    assert "Vitality -Speed Tradeoff III" in text
    assert "fire rate ×" not in text


_TURBINE_ASK = "What's the DPS for Turbine's bard?"


def test_breakdown_follow_up_only_counts_as_dps_after_a_dps_turn():
    """The exact turn that made the model disown its own numbers.

    "What do the numbers look like?" names no class, stat, IGN, or DPS, so it
    used to route to the gear agents and arrive with no reconstruct at all.
    """
    for msg in (
        "What do the numbers look like?",
        "Can you give me a breakdown?",
        "show the math",
        "how did you get that number",
        "walk me through it",
        "explain that please",
        "is that accurate?",
    ):
        assert is_dps_query(msg, history=[_TURBINE_ASK]), msg
        assert is_dps_follow_up(msg, history=[_TURBINE_ASK]), msg
        # The same words in a dungeon conversation are not a DPS ask.
        assert not is_dps_query(msg, history=["How do I do Hardmode Shatters?"]), msg
        assert not is_dps_query(msg), msg


def test_what_if_and_comparison_follow_ups_are_dps_turns():
    for msg in (
        "What if he swapped to a Doom Bow?",
        "instead of the Triangle?",
        "how about a Bolt Thrower",
        "How does that compare to the top Bard on the leaderboard?",
        "is that any good?",
        "better than rank 1?",
    ):
        assert is_dps_query(msg, history=[_TURBINE_ASK]), msg
        assert not is_dps_query(msg), msg


def test_dps_follow_up_chain_survives_a_long_conversation():
    """Follow-ups keep the chain alive, so turn 6 still knows it is about DPS."""
    history = [
        _TURBINE_ASK,
        "What do the numbers look like?",
        "Can you give me a breakdown?",
        "What if he swapped to a Doom Bow?",
        "How does that compare to the top Bard?",
    ]
    assert is_dps_follow_up("show the math again", history=history)


def test_an_unrelated_turn_breaks_the_dps_follow_up_chain():
    history = [_TURBINE_ASK, "How do I do Hardmode Shatters?"]
    assert not is_dps_follow_up("explain that", history=history)


def test_dps_subject_recovers_the_player_and_class_from_history():
    assert dps_subject_from_history([_TURBINE_ASK]) == ("Turbine", "Bard")
    assert dps_subject_from_history(
        [_TURBINE_ASK, "What do the numbers look like?"]
    ) == ("Turbine", "Bard")
    # Most recent DPS turn wins when the subject changes mid-conversation.
    assert dps_subject_from_history(
        [_TURBINE_ASK, "what about the dps on Jewo's wizard?"]
    ) == ("Jewo", "Wizard")
    assert dps_subject_from_history(["How do I do Shatters?"]) == (None, None)


def test_breakdown_follow_up_routes_to_the_dps_slot():
    slots, depth = route_slots(
        "Can you give me a breakdown?",
        "Bard",
        None,
        history=[_TURBINE_ASK],
    )
    assert slots == ["dps"]
    assert depth == "deep"


def test_what_if_weapon_swap_stays_on_dps_not_the_skin_visualizer():
    """"what if he swapped to a Doom Bow?" used to route to the dye previewer."""
    slots, depth = route_slots(
        "What if he swapped to a Doom Bow?",
        None,
        None,
        history=[_TURBINE_ASK],
    )
    assert "dps" in slots
    assert "skin" not in slots
    assert "set" not in slots
    # The swapped-in piece's slot rides along so its wiki page can rescale.
    assert "weapon" in slots
    assert depth == "deep"


def test_reconstruct_derivation_spells_out_the_arithmetic():
    """A breakdown has to be answerable from the brief, not re-derived."""
    weapon_steps: dict = {}
    est = estimate_weapon_dps({"Damage": "100-110", "Shots": "2"}, dex=60, att=90)
    weapon_total = reconstruct_weapon_damage(
        est, att=90, dex=60, debug={}, steps=weapon_steps
    )
    ability_steps: dict = {}
    ability_total = reconstruct_ability_damage(
        {"avg": 375.0, "per": 25.0, "threshold": 55.0, "stat": "Attack", "shots": 3},
        stats={"Attack": 96.0},
        debug={},
        steps=ability_steps,
    )
    # Every factor printed has to be the one actually multiplied in.
    assert weapon_steps["total"] == weapon_total
    assert ability_steps["per_shot"] == 375.0 + 25.0 * (96.0 - 55.0)
    assert ability_steps["per_use"] == ability_steps["per_shot"] * 3
    assert ability_steps["total"] == ability_total

    total = weapon_total + ability_total
    text = format_dps_derivation(
        weapon_item=None,
        ability_item=None,
        weapon_steps=weapon_steps,
        ability_steps=ability_steps,
        total=total,
        dps=total / 5.0,
        label="potential DPS",
    )
    assert "HOW THIS RECONSTRUCT WAS BUILT" in text
    assert "attacks/sec" in text
    assert "attack multiplier" in text
    assert "party buffs" in text
    assert "per use" in text
    assert "1400.0" in text  # the per-shot ability figure, shown not asserted
    assert "Total:" in text


MAKAKOYUMI_STATS = {
    "Tier": "UT",
    "Total Damage": "20\u2013800 (average: 830)",
    "Shots": "1",
    "Damage": "800; 20\u201340 (average: 30)",
    "Rate of Fire": "33%; 200%",
}


def test_a_weapon_with_two_firing_rates_counts_both_projectiles():
    """Reported live Sep 17: Makakoyumi, the highest-DPS bow in the game, showed
    a weapon half of 3,063.3 damage over 5s.

    RealmEye lists its two projectiles as `Damage: 800; 20-40` at
    `Rate of Fire: 33%; 200%`. `_RANGE.findall` skipped the bare `800` and only
    matched `20-40`, so we modelled a 30-damage bow, and the single blended rate
    of fire could not have represented the two rates anyway.
    """
    est = estimate_weapon_dps(MAKAKOYUMI_STATS, dex=71, att=125)
    assert est["multi_rof"] is True
    # 800 is a fixed-damage shot so it always rolls 800. 20-40 averages 29.5,
    # not 30: the top of a range is never rolled (see the avg correction test).
    assert [g["avg"] for g in est["groups"]] == [800.0, 29.5]
    assert [g["rof"] for g in est["groups"]] == [pytest.approx(0.33), pytest.approx(2.0)]
    # Each group is counted at its own rate, then summed.
    expected = sum(
        g["avg"] * g["shots"] * dps_specialist.attacks_per_second(dex=71, rof=g["rof"])
        for g in est["groups"]
    )
    assert est["per_second"] == pytest.approx(expected)
    total = reconstruct_weapon_damage(
        est, att=125, dex=71, debug={}, berserk_source=False
    )
    # The old parse produced ~3.1k. The 800-damage shot alone is worth far more.
    assert total > 70_000
    # And it must beat Warmonger on the same character, which is the observation
    # that surfaced the bug.
    warmonger = estimate_weapon_dps(
        {"Damage": "95-110", "Shots": "2", "Rate of Fire": "120%"}, dex=71, att=125
    )
    assert total > reconstruct_weapon_damage(
        warmonger, att=125, dex=71, debug={}, berserk_source=False
    )


def test_a_thousands_separator_does_not_truncate_damage():
    """`\\d+` stops at the comma, so Venerable Doom Bow's "900-1,100" parsed as
    the range 900 to 1. Found by the audit's plausibility check, not by a user."""
    assert parse_damage_range("900\u20131,100 (average: 1,000)") == (900.0, 1100.0)
    est = estimate_weapon_dps(
        {"Damage": "900\u20131,100 (average: 1,000)", "Shots": "1"}, dex=60, att=90
    )
    assert est["avg"] == pytest.approx(999.5)
    # A comma that is not between digits must survive untouched.
    assert parse_damage_range("100\u2013200 (drops from A, B)") == (100.0, 200.0)


def test_one_rate_of_fire_with_side_shots_is_still_a_single_volley():
    """Pattern A must not regress into Pattern B. Aspirant's Bow fires a main
    arrow plus two weaker side arrows at one rate, so the per-shot average
    across all three shots is correct and `multi_rof` stays False."""
    est = estimate_weapon_dps(
        {
            "Damage": "110-120 (average: 115); 35-45 (average: 40)",
            "Shots": "1; 2 (arc gap: 14\u00b0)",
        },
        dex=60,
        att=50,
    )
    assert est["multi_rof"] is False
    assert est["burst"] == pytest.approx(114.5 + 39.5 * 2)
    assert est["shots"] == pytest.approx(3.0)
    # One rate means per_second is exactly the old burst x aps.
    assert est["per_second"] == pytest.approx(est["burst"] * est["aps"])


def test_single_projectile_weapons_take_the_simple_path():
    """The multi-projectile work must not reroute a plain weapon through the
    per-group sum: for one rate of fire the two must be identical."""
    est = estimate_weapon_dps(
        {"Damage": "95-110", "Shots": "2", "Rate of Fire": "120%"}, dex=68, att=96
    )
    assert est["multi_rof"] is False
    assert est["per_second"] == pytest.approx(est["burst"] * est["aps"])
    total = reconstruct_weapon_damage(
        est, att=96, dex=68, debug={}, berserk_source=False
    )
    # 47,452.6 before the "top of the range is never rolled" correction, which
    # takes the 95-110 average from 102.5 to 102.0.
    assert total == pytest.approx(47_221.1, rel=1e-4)


def test_a_multi_rate_derivation_reproduces_its_own_total():
    """The breakdown printed "830.0 damage per volley x 3.16 attacks/sec", which
    multiplies out to ~84,800 rather than the 100,252.7 it also claimed. A
    breakdown whose arithmetic does not reach its own total is the bug the
    derivation block exists to prevent."""
    est = estimate_weapon_dps(MAKAKOYUMI_STATS, dex=71, att=125)
    steps: dict = {}
    total = reconstruct_weapon_damage(
        est, att=125, dex=71, debug={}, steps=steps, berserk_source=False
    )
    text = format_dps_derivation(
        weapon_item=ItemProfile(name="Makakoyumi", stats=MAKAKOYUMI_STATS),
        ability_item=None,
        weapon_steps=steps,
        ability_steps={},
        total=total,
        dps=total / 5.0,
        label="weapon-only DPS",
    )
    assert "projectile groups at different rates of fire" in text
    assert "damage per volley" not in text
    # per_second is the finished rate (multipliers and DEF already inside it,
    # because DEF is per projectile), so the total is just that times the window.
    assert steps["per_second"] * 5 == pytest.approx(total)
    # Each group's printed per-hit figure sums to that rate.
    summed = sum(
        g["hit"] * g["shots"] * dps_specialist.attacks_per_second(dex=71, rof=g["rof"])
        for g in steps["groups"]
    )
    assert summed == pytest.approx(steps["per_second"])


def test_on_equip_penalties_are_parsed_not_discarded():
    """`_BONUS_PAT` required a literal "+", so every stat penalty in the game
    was invisible and a reconstruct kept DEX the character did not have.
    78 of 1444 cached items state at least one negative On Equip modifier."""
    javelin = ItemProfile(
        name="Mad Javelin", stats={"On Equip": "+10 ATT, -3 DEX"}
    )
    assert wiki_scaling.on_equip_bonuses(javelin) == {"Attack": 10, "Dexterity": -3}
    scroll = ItemProfile(
        name="Cobra Serpentis Scroll",
        stats={"On Equip": "-20 HP, +2 ATT, +2 DEF, +4 DEX, -5 VIT"},
    )
    assert wiki_scaling.on_equip_bonuses(scroll) == {
        "HP": -20,
        "Attack": 2,
        "Defense": 2,
        "Dexterity": 4,
        "Vitality": -5,
    }
    # The penalty has to reach the stat sheet, not just the parse.
    assert gear_stat_contribution(javelin)["Dexterity"] == -3


def test_a_flat_damage_ability_still_reconstructs():
    """Requiring the "(+N per STAT over T)" clause returned None for an ability
    that simply does not scale, which dropped the whole ability half and
    labelled the set weapon-only. 58 of 1444 cached items are flat."""
    formula = parse_ability_formula(
        {"MP Cost": "100", "Damage": "320-400 (average: 360)", "Shots": "1"}
    )
    assert formula is not None
    assert formula["avg"] == pytest.approx(360.0)
    assert formula["per"] == 0.0
    assert formula["scales"] is False
    # A flat ability must not gain damage from a high stat.
    low = reconstruct_ability_damage(formula, stats={"Attack": 20.0}, debug={})
    high = reconstruct_ability_damage(formula, stats={"Attack": 99.0}, debug={})
    assert low == pytest.approx(high)
    # And a scaling ability still reports that it scales.
    scaling = parse_ability_formula(
        {"MP Cost": "100", "Damage": "300-450 (+25 per ATT over 55)", "Shots": "3"}
    )
    assert scaling["scales"] is True
    assert scaling["stat"] == "Attack"


def test_both_dps_paths_build_the_same_stat_sheet():
    """A player-set ask and a board-row ask must not disagree about the same gear.

    The player path added `ability_deltas` and `shoot_deltas` across every stat;
    the board path added only `shoot_deltas`, only for Attack and Dexterity, and
    handed the ability reconstructor untouched row stats. So Vesture's on-ability
    +15 ATT counted for a named player and not for a leaderboard row, and a
    Wisdom proc counted for neither ability half consistently.
    """
    vesture = ItemProfile(
        name="Vesture of Duality",
        stats={
            "On Equip": "+12 DEF, +5 SPD, +5 ATT, +40 MP",
            "Reactive Proc": (
                "On Ability Use: ATT Boost (+15 ATT) and DEF Decrease "
                "(-6 DEF) on self for 5 seconds"
            ),
        },
    )
    warmonger = ItemProfile(
        name="Warmonger",
        stats={
            "On Equip": "+5 VIT",
            "Reactive Proc": (
                "On Shoot: When in combat, DEX Decrease (-5 DEX) for 1 second"
            ),
        },
    )
    catalog = inspect_worn_set([warmonger, vesture])
    sheet = {"Attack": 76.0, "Dexterity": 73.0, "Wisdom": 60.0}
    combat = dps_specialist.combat_stat_sheet(sheet, catalog)
    # Vesture's on-ability +15 and Warmonger's on-shoot -5 both land.
    assert combat["Attack"] == pytest.approx(91.0)
    assert combat["Dexterity"] == pytest.approx(68.0)
    # Untouched stats survive, and the caller's sheet is not mutated.
    assert combat["Wisdom"] == pytest.approx(60.0)
    assert sheet["Attack"] == 76.0
    # A penalty-only set lowers the sheet rather than being ignored.
    only_weapon = dps_specialist.combat_stat_sheet(
        {"Dexterity": 73.0}, inspect_worn_set([warmonger])
    )
    assert only_weapon["Dexterity"] == pytest.approx(68.0)


def test_damaging_lifts_the_ability_half_not_just_the_weapon():
    """Damaging is x1.25 on both halves. Berserk is the only weapon-only one.

    Measured against the 133 cached RealmShark rows that carry both stored
    halves: weapon-only Damaging left the ability half a median 26.7% under
    RealmShark, both halves brought it to 8.4%. See
    api/scripts/calibrate_dps_buffs.py.
    """
    formula = {"avg": 100.0, "per": 0.0, "threshold": 0.0, "stat": "Attack", "shots": 1}
    steps: dict = {}
    reconstruct_ability_damage(formula, stats={"Attack": 0.0}, debug={}, steps=steps)
    # Damaging 1.25 x Curse 1.25 x Exposed 1.20 x Vulnerable 1.15.
    assert steps["buff_mult"] == pytest.approx(1.25 * 1.25 * 1.20 * 1.15)
    # Berserk never reaches the ability half.
    assert "berserk" not in steps


def test_berserk_needs_a_source_in_the_worn_set():
    """Regression, found live Sep 17 against RealmShark's own row for Turbine.

    Berserk defaulted on with no source, inflating every player-set reconstruct
    by the full x1.25 APS (23,455.1 vs RealmShark's 21,381.1 for the same
    character), and the model then credited the buff to Vesture of Duality.
    """
    est = estimate_weapon_dps(
        {"Damage": "95-110", "Shots": "2", "Rate of Fire": "120%"}, dex=68, att=96
    )
    plain: dict = {}
    with_zerk: dict = {}
    without = reconstruct_weapon_damage(
        est, att=96, dex=68, debug={}, steps=plain, berserk_source=False
    )
    with_ = reconstruct_weapon_damage(
        est, att=96, dex=68, debug={}, steps=with_zerk, berserk_source=True
    )
    assert plain["berserk"] is False
    assert with_zerk["berserk"] is True
    assert with_ == pytest.approx(without * 1.25)
    # RealmShark's own figure for this character is 106,906 damage over 5s.
    # The sourced (correct) branch is the one that lands near it.
    ability = reconstruct_ability_damage(
        {"avg": 375.0, "per": 25.0, "threshold": 55.0, "stat": "Attack", "shots": 3},
        stats={"Attack": 96.0},
        debug={},
    )
    assert abs((without + ability) / 106_906.0 - 1) < abs(
        (with_ + ability) / 106_906.0 - 1
    )


def test_set_grants_berserk_reads_the_set_not_a_guess():
    vesture = ItemProfile(
        name="Vesture of Duality",
        stats={
            "On Equip": "+12 DEF, +5 SPD, +5 ATT, +40 MP",
            "Reactive Proc": (
                "On Ability Use: ATT Boost (+15 ATT) and DEF Decrease "
                "(-6 DEF) on self for 5 seconds"
            ),
        },
    )
    assert dps_specialist.set_grants_berserk([vesture]) is False
    # An OnHit Berserk enchant is a source even though it is a chance roll:
    # the number being reconstructed is a potential ceiling.
    assert dps_specialist.set_grants_berserk(
        [vesture],
        enchant_texts=[
            (
                "Ritual Robe",
                "OnHit Berserk II: On Hit for at least 20 damage 25% chance "
                "to gain Berserk for 5 seconds",
            )
        ],
    ) is True


def test_the_brief_never_calls_a_five_second_total_a_dps_number():
    """The halves are 5s damage totals. Presenting them next to "DPS" made the
    model report "Warmonger -> 59,315.7 DPS", which is 5x the real rate."""
    weapon_steps: dict = {}
    est = estimate_weapon_dps({"Damage": "100-110", "Shots": "2"}, dex=60, att=90)
    weapon_total = reconstruct_weapon_damage(
        est, att=90, dex=60, debug={}, steps=weapon_steps, berserk_source=False
    )
    text = format_dps_derivation(
        weapon_item=None,
        ability_item=None,
        weapon_steps=weapon_steps,
        ability_steps={},
        total=weapon_total,
        dps=weapon_total / 5.0,
        label="weapon-only DPS",
    )
    assert "NOT damage per second" in text
    assert "total damage, NOT per second" in text
    assert "only one that is per second" in text
    # And it says why there is no Berserk, so the model cannot invent a source.
    assert "no Berserk (nothing in this set grants it)" in text


def test_board_reconstruction_copy_matches_the_real_formulas():
    """The board-row brief used to say APS(DEX x RoF) and Damaging is
    weapons-only. The model copied both into live Archer breakdowns."""
    row = Loadout(
        rank=1,
        player_name="Turbine",
        dps=28000,
        weapon_name="Bolt Thrower",
        ability_name="Quiver of Shadows",
        weapon_damage=50000,
        ability_damage=80000,
        stats={"Attack": 87, "Dexterity": 58, "Defense": 91},
        debug={"buffs": {"damaging": True, "curse": True, "expose": True, "vulnerable": True}},
    )
    estimate = estimate_weapon_dps(
        {"Damage": "80-102", "Shots": "5", "Rate of Fire": "80%"},
        dex=58,
        att=87,
    )
    reconstructed = reconstruct_weapon_damage(
        estimate, att=87, dex=58, debug=row.debug
    )
    formula = parse_ability_formula(
        {"Damage": "400-500 (+5 per DEF over 9)", "Shots": "6"}
    )
    ability = reconstruct_ability_damage(formula, stats=row.stats, debug=row.debug)
    text = format_reconstruction(
        estimate,
        row,
        reconstructed,
        ability_formula=formula,
        ability_reconstructed=ability,
    )
    assert "1.5 + 6.5" in text
    assert "APS(DEX × Rate of Fire" not in text
    assert "Damaging is weapons-only" not in text
    assert "Berserk is weapon-only" in text
    assert "Damaging × Curse × Exposed × Vulnerable" in text


def test_set_effects_no_longer_claims_berserk_is_a_party_assumption():
    text = format_set_effects(
        [ItemProfile(name="Warmonger", stats={"On Equip": "+5 VIT"})]
    )
    assert "Berserk is NOT a party assumption" in text
    assert "assumes party Damaging, Berserk" not in text
    assert "Damaging x1.25 on BOTH weapon and ability" in text


def test_estimate_weapon_dps_includes_attack_multiplier():
    est = estimate_weapon_dps(
        {"Damage": "155-185", "Shots": "4", "Rate of Fire": "55%"},
        dex=75,
        att=75,
    )
    assert est is not None
    # 155-185 averages 169.5, not 170: the top of the range is never rolled.
    assert est["avg"] == 169.5
    assert est["shots"] == 4
    assert abs(est["aps"] - 4.4) < 0.01
    assert abs(est["att_mult"] - 2.0) < 0.01
    # 5,984.0 before the "top of the range is never rolled" correction.
    assert abs(est["dps"] - 5966.4) < 1.0


def test_scale_shark_weapon_preserves_board_baseline():
    scaled = scale_shark_weapon(123643.47, 100_000.0, 110_000.0)
    assert scaled is not None
    assert abs(scaled - 123643.47 * 1.1) < 0.01


def test_reconstruct_weapon_damage_uses_shark_debug_multipliers():
    est = estimate_weapon_dps(
        {"Damage": "155-185", "Shots": "4", "Rate of Fire": "55%"},
        dex=72,
        att=122,
    )
    assert est is not None
    reconstructed = reconstruct_weapon_damage(
        est,
        att=122,
        dex=72,
        debug={
            "weaponEnchant": {
                "id": "FLURRY_OF_BLOWS",
                "weaponDamageMult": 0.8,
                "weaponRofMult": 1.35,
            },
            "buffs": {
                "damaging": True,
                "berserk": True,
                "curse": True,
                "expose": True,
                "vulnerable": True,
                "armor_broken": True,
            },
        },
    )
    # Reverse-engineered 5s weapon half matches the live Attack Necro
    # board's 123,643 within rounding (Vulnerable is 115%).
    assert 122_000 < reconstructed < 126_000
    assert abs(reconstructed - 123643.47) / 123643.47 < 0.01


def test_en_dash_wiki_damage_range():
    lo, hi = parse_damage_range("155-185 (average: 170 / total: 680)")
    assert lo == 155
    assert hi == 185
    triangle = parse_ability_formula(
        {"Damage": "300-450 (+25 per ATT over 55) (average: 375)", "Shots": "3"}
    )
    assert triangle is not None
    assert triangle["avg"] == 375
    assert triangle["per"] == 25
    assert triangle["stat"] == "Attack"
    assert triangle["shots"] == 3


def test_weapon_enchant_from_damage_tradeoff_when_debug_missing():
    dmg, rof = weapon_enchant_multipliers(
        {},
        [ItemEnchant(name="Damage Tradeoff IV", value="+12.5% Weapon Damage, -5% Fire Rate")],
    )
    assert abs(dmg - 1.125) < 0.0001
    assert abs(rof - 0.95) < 0.0001
    flurry, flurry_rof = weapon_enchant_multipliers(
        {},
        [ItemEnchant(name="Flurry of Blows", value="fire rate +35%, damage -20%")],
    )
    assert abs(flurry - 0.8) < 0.0001
    assert abs(flurry_rof - 1.35) < 0.0001


def test_bolt_thrower_counts_both_shot_groups():
    est = estimate_weapon_dps(
        {
            "Damage": "110-125 (average: 117.5); 80-90 (average: 85)",
            "Shots": "1; 4 (arc gap: 20°)",
            "Rate of Fire": "80%",
        },
        dex=75,
        att=75,
    )
    assert est is not None
    assert abs(est["burst"] - (117.0 + 84.5 * 4)) < 0.01
    assert est["shots"] == 5


def test_warmonger_on_shoot_dex_penalty():
    item = ItemProfile(
        name="Warmonger",
        stats={
            "Damage": "95-110",
            "Shots": "2 (arc gap: 7°)",
            "Rate of Fire": "120%",
            "Reactive Proc": "On Shoot: When in combat, DEX Decrease (-5 DEX) for 1 second",
        },
    )
    deltas = combat_shoot_deltas(item)
    assert deltas["Dexterity"] == -5
    est = estimate_weapon_dps(item.stats or {}, dex=50 + deltas["Dexterity"], att=153)
    reconstructed = reconstruct_weapon_damage(
        est,
        att=153,
        dex=50 + deltas["Dexterity"],
        debug={
            "weaponEnchant": {
                "id": "FLURRY_OF_BLOWS",
                "weaponDamageMult": 0.8,
                "weaponRofMult": 1.35,
            },
            "buffs": {
                "damaging": True,
                "berserk": True,
                "curse": True,
                "expose": True,
                "vulnerable": True,
            },
        },
    )
    # Live Attack Archer weapon half is 69,832 with Warmonger's combat -5 DEX.
    assert 67_000 < reconstructed < 72_000


def test_inspect_worn_set_reads_grants_and_procs_from_every_slot():
    weapon = ItemProfile(
        name="Generic Staff",
        stats={"Reactive Proc": "On Shoot: When in combat, DEX Decrease (-5 DEX)"},
    )
    ability = ItemProfile(
        name="Generic Seal",
        stats={"Effect(s)": "On Use: Healing and Damaging on self for 5 seconds"},
    )
    armor = ItemProfile(
        name="Generic Helm",
        stats={"Effect(s)": "On Use: Berserk on self for 4 seconds"},
    )
    ring = ItemProfile(
        name="Generic Lotus",
        stats={"Effect(s)": "On Ability Use: Heal and Berserk on self"},
    )
    summon = ItemProfile(
        name="Generic Summon",
        stats={
            "Reactive Proc(s)": (
                "On Ability Use: spawn spirits that inflict Curse or Slow, "
                "or Heal allies"
            )
        },
    )
    robe = ItemProfile(
        name="Generic Robe",
        stats={
            "On Equip": "+5 ATT",
            "Reactive Proc(s)": "On Ability Use: ATT Boost(+15 ATT) on self for 5 seconds",
        },
    )
    dagger = ItemProfile(
        name="Generic Dagger",
        stats={
            "Reactive Proc(s)": "On Hit: 20% chance to inflict Curse and +10 ATT"
        },
    )
    catalog = inspect_worn_set(
        [weapon, ability, armor, ring, summon, robe, dagger],
        enchant_texts=[("Generic Staff", "On Shoot: +4 ATT")],
    )
    grants = {flag: [row["source"] for row in rows] for flag, rows in catalog["grants"].items()}
    assert grants["damaging"] == ["Generic Seal"]
    assert "Generic Helm" in grants["berserk"]
    assert "Generic Lotus" in grants["berserk"]
    assert "Generic Seal" in grants["healing"]
    assert "Generic Lotus" in grants["healing"]
    assert "Generic Summon" in grants["healing"]
    assert grants["curse"] == ["Generic Summon", "Generic Dagger"]
    assert grants["slow"] == ["Generic Summon"]
    curse_rows = catalog["grants"]["curse"]
    assert curse_rows[0]["dummy_uptime"] is True
    assert curse_rows[1]["dummy_uptime"] is False
    assert catalog["shoot_deltas"]["Dexterity"] == -5
    assert catalog["shoot_deltas"]["Attack"] == 4
    assert catalog["ability_deltas"]["Attack"] == 15
    assert catalog["on_equip"] == [{"item": "Generic Robe", "bonuses": {"Attack": 5}}]
    hit_procs = [proc for proc in catalog["procs"] if proc["item"] == "Generic Dagger"]
    assert hit_procs
    assert hit_procs[0]["dummy_uptime"] is False
    assert hit_procs[0]["bonuses"]["Attack"] == 10
    assert "Attack" not in catalog["ability_deltas"] or catalog["ability_deltas"]["Attack"] == 15
    text = format_set_effects(
        [weapon, ability, armor, ring, summon, robe, dagger],
        enchant_texts=[("Generic Staff", "On Shoot: +4 ATT")],
    )
    assert "SET EFFECTS from the worn pieces" in text
    assert "[item:Generic Seal]" in text
    assert "[item:Generic Helm]" in text
    assert "[item:Generic Robe] On Ability" in text or "+15" in text
    assert "[item:Generic Dagger] (not 100% dummy)" in text or "not 100% dummy" in text
    assert "Generic Staff enchant" in text or "+4" in text


def test_parse_status_grants_is_name_agnostic():
    item = ItemProfile(
        name="Any Ability",
        stats={"Effect(s)": "On Use: Exposed and Vulnerable on enemies"},
    )
    grants = parse_status_grants(item)
    assert "expose" in grants
    assert "vulnerable" in grants


def test_parse_ability_formula_reads_per_stat_over_threshold():
    skull = parse_ability_formula(
        {"Damage": "565 (+2 for every ATT above 55)", "Shots": "3", "MP Cost": "120"}
    )
    assert skull is not None
    assert skull["avg"] == 565
    assert skull["per"] == 2
    assert skull["stat"] == "Attack"
    assert skull["threshold"] == 55
    assert skull["shots"] == 3
    assert skull["mp_cost"] == 120
    mace = parse_ability_formula(
        {"Damage": "275-305 (+5.2 for every WIS above 55)"}
    )
    assert mace is not None
    assert mace["stat"] == "Wisdom"
    assert abs(mace["avg"] - 290) < 0.01
    assert mace["per"] == 5.2
    trap = parse_ability_formula({"Damage": "675 (+14 per DEX over 32)"})
    assert trap is not None
    assert trap["stat"] == "Dexterity"
    assert trap["per"] == 14


def test_ability_damage_comes_from_the_damage_row_not_an_effect_boost():
    """RealmEye lists Effect(s) before Damage, and boosts share the shape."""
    triangle = parse_ability_formula(
        {
            "Tier": "UT",
            "MP Cost": "100",
            "On Equip": "+3 ATT, +3 WIS",
            "Effect(s)": (
                "Self Only: On use, quadruples shot speed for 4 seconds.\n"
                "ATT Boost: +5 (+1 per 8 WIS over 75) ATT\n"
                "ATT Boost Range: 4 (+0.1 per WIS over 75) tiles\n"
                "ATT Boost Duration: 4 seconds"
            ),
            "Shots": "3",
            "Damage": "300-450 (+25 per ATT over 55) (average: 375)",
            "Total Damage": "900-1,350 (average: 1,125)",
        }
    )
    assert triangle is not None
    assert triangle["stat"] == "Attack"
    assert triangle["avg"] == 375
    assert triangle["per"] == 25
    assert triangle["threshold"] == 55
    assert triangle["shots"] == 3
    assert triangle["mp_cost"] == 100


def test_per_n_stat_scaling_divides_by_the_step():
    """'+1 per 8 WIS over 75' is +0.125 per point, not +1."""
    formula = parse_ability_formula(
        {"Damage": "100 (+1 per 8 WIS over 75)", "Shots": "1"}
    )
    assert formula is not None
    assert formula["stat"] == "Wisdom"
    assert abs(formula["per"] - 0.125) < 1e-9


def test_total_damage_row_is_never_used_as_the_ability_formula():
    formula = parse_ability_formula(
        {"Total Damage": "900 (+75 per ATT over 55)", "Shots": "3"}
    )
    assert formula is None


def test_stat_mod_iv_multiplies_the_scaling_stat():
    formula = parse_ability_formula(
        {"Damage": "565 (+2 for every ATT above 55)", "Shots": "3"}
    )
    assert formula is not None
    base = reconstruct_ability_damage(
        formula,
        stats={"Attack": 100},
        debug={"abilityStatModMult": 1, "effectiveAbilityCount": 8, "buffs": {}},
        enchants=[],
    )
    boosted = reconstruct_ability_damage(
        formula,
        stats={"Attack": 100},
        debug={"effectiveAbilityCount": 8, "buffs": {}},
        enchants=[
            ItemEnchant(
                name="Stat Mod Multiplier IV",
                value="Increases Stat Mod value for this ability by +15%",
            )
        ],
    )
    assert base is not None and boosted is not None
    # 100 ATT -> 115 effective at IV. Over 55 that is 45 vs 60 extra ATT.
    assert boosted > base
    assert abs(stat_mod_multiplier({}, [
        ItemEnchant(name="Stat Mod Multiplier IV", value="+15%")
    ]) - 1.15) < 0.001


def test_ideal_ability_enchants_skip_stat_mod_when_no_scaling():
    formula = parse_ability_formula(
        {"Damage": "565 (+2 for every ATT above 55)", "Shots": "1"}
    )
    text = ideal_ability_enchants(formula)
    assert "Stat Mod Multiplier" in text
    assert "Mana Regeneration" in text
    skip = ideal_ability_enchants(None)
    assert "Skip Stat Mod Multiplier" in skip
    assert "Mana Regeneration" in skip


def test_losing_vesture_attack_proc_drops_ability_reconstruct():
    formula = parse_ability_formula(
        {"Damage": "565 (+2 for every ATT above 55)", "Shots": "3"}
    )
    enchants = [
        ItemEnchant(name="Stat Mod Multiplier IV", value="+15%"),
    ]
    with_proc = reconstruct_ability_damage(
        formula,
        stats={"Attack": 122},
        debug={"effectiveAbilityCount": 8, "buffs": {}},
        enchants=enchants,
    )
    without_proc = reconstruct_ability_damage(
        formula,
        stats={"Attack": 102},
        debug={"effectiveAbilityCount": 8, "buffs": {}},
        enchants=enchants,
    )
    assert with_proc is not None and without_proc is not None
    assert without_proc < with_proc
    scaled = scale_shark_weapon(55171.88, with_proc, without_proc)
    assert scaled is not None
    assert scaled < 55171.88


def test_vesture_on_ability_proc_counts_as_plus_15_attack():
    item = ItemProfile(
        name="Vesture of Duality",
        stats={
            "On Equip": "+12 DEF, +5 SPD, +5 ATT, +40 MP",
            "Reactive Proc(s)": (
                "On Ability Use: ATT Boost(+15 ATT) and DEF Decrease(-6 DEF) "
                "on self for 5 seconds"
            ),
        },
    )
    procs = parse_gear_procs(item)
    assert procs
    assert procs[0]["trigger"] == "ability"
    assert procs[0]["bonuses"]["Attack"] == 15
    assert procs[0]["bonuses"]["Defense"] == -6
    contrib = gear_stat_contribution(item)
    assert contrib["Attack"] == 20
    assert contrib["Defense"] == 6
    assert contrib["Speed"] == 5
    assert contrib["MP"] == 40


def test_loadouts_from_rows_keeps_enchants_and_damage_split():
    rows = loadouts_from_rows(
        {
            "rows": [
                {
                    "rank": 1,
                    "playerName": "Aifumi",
                    "dps": 35763.07,
                    "totalDamage": 178815.35,
                    "weaponDamage": 123643.47,
                    "abilityDamage": 55171.88,
                    "weaponName": "Staff of Unholy Sacrifice",
                    "abilityName": "Demon Lord's Skull",
                    "equipment": [
                        {
                            "slot": "Weapon",
                            "itemName": "Staff of Unholy Sacrifice",
                            "rarity": "Divine",
                            "enchants": [
                                {
                                    "slot": 3,
                                    "enchantName": "Flurry of Blows",
                                    "value": "Increases weapon fire rate by 35%",
                                }
                            ],
                        }
                    ],
                    "stats": {"attack": 122, "defense": 46, "dexterity": 72},
                    "debug": {
                        "weaponEnchant": {
                            "id": "FLURRY_OF_BLOWS",
                            "weaponDamageMult": 0.8,
                            "weaponRofMult": 1.35,
                        }
                    },
                }
            ]
        }
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.weapon_damage == 123643.47
    assert row.ability_damage == 55171.88
    assert row.stats["Defense"] == 46
    assert row.equipment[0].enchants[0].name == "Flurry of Blows"
    assert row.debug["weaponEnchant"]["weaponDamageMult"] == 0.8


def _atk_necro_loadout() -> Loadout:
    return Loadout(
        rank=1,
        player_name="Aifumi",
        dps=35763.07,
        weapon_name="Staff of Unholy Sacrifice",
        ability_name="Demon Lord's Skull",
        total_damage=178815.35,
        weapon_damage=123643.47,
        ability_damage=55171.88,
        stats={
            "HP": 830,
            "MP": 455,
            "Attack": 122,
            "Defense": 46,
            "Speed": 60,
            "Dexterity": 72,
            "Vitality": 45,
            "Wisdom": 80,
        },
        equipment=[
            EquipmentSlot(
                slot="Weapon",
                item_name="Staff of Unholy Sacrifice",
                rarity="Divine",
                enchants=[
                    ItemEnchant(slot=3, name="Flurry of Blows", value="fire rate +35%")
                ],
            ),
            EquipmentSlot(
                slot="Ability",
                item_name="Demon Lord's Skull",
                rarity="Rare",
                enchants=[
                    ItemEnchant(
                        name="Stat Mod Multiplier IV",
                        value="Increases Stat Mod value for this ability by +15%",
                    ),
                    ItemEnchant(
                        name="Percentage Mana Regeneration IV",
                        value="Increases Mana Regeneration by 1.5% of your maximum Mana per second.",
                    ),
                ],
            ),
            EquipmentSlot(slot="Armor", item_name="Vesture of Duality", rarity="Divine"),
            EquipmentSlot(slot="Ring", item_name="Ring of Unbound Attack", rarity="Divine"),
        ],
        debug={
            "weaponEnchant": {
                "id": "FLURRY_OF_BLOWS",
                "weaponDamageMult": 0.8,
                "weaponRofMult": 1.35,
            },
            "buffs": {
                "damaging": True,
                "berserk": True,
                "curse": True,
                "expose": True,
                "vulnerable": True,
            },
        },
    )


async def _seed_necro_board(redis) -> None:
    graph = StatScalingGraph(
        season="s30",
        edges=[
            AbilityScalingEdge(
                class_name="Necromancer",
                stat="Attack",
                ability_names=["Demon Lord's Skull"],
                build_id="atk-necro",
                label="Attack Necromancer",
            )
        ],
    )
    await redis.set(GRAPH_CACHE_KEY, graph.model_dump_json())
    stub = StatScalingGraph(top_loadouts={"atk-necro": [_atk_necro_loadout()]})
    await redis.set(f"{LOADOUT_CACHE_PREFIX}:atk-necro", stub.model_dump_json())
    await redis.set(
        f"{CLASS_MAXSTATS_PREFIX}:necromancer",
        json.dumps(
            {
                "class_name": "Necromancer",
                "rows": [
                    {
                        "stat": "Defense",
                        "items": ["Candy-Coated Armor"],
                        "total": 66,
                    }
                ],
            }
        ),
    )
    item = ItemProfile(
        name="Staff of Unholy Sacrifice",
        wiki_url="https://www.realmeye.com/wiki/staff-of-unholy-sacrifice",
        stats={"Damage": "155-185", "Shots": "4", "Rate of Fire": "55%"},
    )
    await redis.set(
        f"{ITEM_CACHE_PREFIX}:staff of unholy sacrifice",
        item.model_dump_json(),
    )
    skull = ItemProfile(
        name="Demon Lord's Skull",
        wiki_url="https://www.realmeye.com/wiki/demon-lords-skull",
        stats={
            "Damage": "565 (+2 for every ATT above 55)",
            "Shots": "3",
            "MP Cost": "120",
        },
    )
    await redis.set(
        f"{ITEM_CACHE_PREFIX}:demon lord's skull",
        skull.model_dump_json(),
    )
    vesture = ItemProfile(
        name="Vesture of Duality",
        stats={
            "On Equip": "+12 DEF, +5 SPD, +5 ATT, +40 MP",
            "Reactive Proc(s)": (
                "On Ability Use: ATT Boost(+15 ATT) and DEF Decrease(-6 DEF) "
                "on self for 5 seconds"
            ),
        },
    )
    await redis.set(
        f"{ITEM_CACHE_PREFIX}:vesture of duality",
        vesture.model_dump_json(),
    )
    diplomatic = ItemProfile(
        name="Diplomatic Robe",
        stats={"On Equip": "+10 ATT, +5 WIS"},
    )
    await redis.set(
        f"{ITEM_CACHE_PREFIX}:diplomatic robe",
        diplomatic.model_dump_json(),
    )


async def test_max_defense_necro_brief_leads_with_numbers(redis_client):
    await _seed_necro_board(redis_client)
    text = await dps_specialist.retrieve_dps_brief(
        redis_client,
        "What's the max defense for necromancer?",
        ttl_seconds=60,
        class_name="Necromancer",
        stat="Defense",
        cache_only=True,
    )
    assert "REALMSHARK SOURCE OF TRUTH" in text
    assert "Do not recommend a set" in text
    assert "**46**" in text
    assert "wiki total for Necromancer Defense: **66**" in text
    assert "35763.1" in text or "35,763.1" in text
    assert "SET VISUALIZER PICKS" not in text
    assert "Wiki ability scaling" in text
    assert "Stat Mod Multiplier" in text
    assert "SET EFFECTS from the worn pieces" in text
    assert "[item:Vesture of Duality]" in text
    assert "On ability:" in text or "On Ability" in text or "+15" in text


async def test_swap_vesture_for_diplomatic_scales_weapon_and_ability(redis_client):
    await _seed_necro_board(redis_client)
    text = await dps_specialist.retrieve_dps_brief(
        redis_client,
        "what's my dps if i swap vesture for diplomatic",
        ttl_seconds=60,
        class_name="Necromancer",
        stat="Attack",
        cache_only=True,
    )
    assert "swap armor for [item:Diplomatic Robe]" in text
    assert "Scaled RealmShark" in text
    assert "weapon 123,643.5" in text or "123643" in text
    assert "ability 55,171.9" in text or "55171" in text
    assert "Estimated potential DPS" in text
    assert "This is a scaled RealmShark number" in text
    assert "On Ability" in text or "On ability" in text or "+15" in text


async def test_numbers_only_build_knowledge_skips_set_visualizer(
    redis_client, monkeypatch
):
    await _seed_necro_board(redis_client)

    async def boom(*args, **kwargs):
        raise AssertionError("gear extras must not run on a numbers ask")

    monkeypatch.setattr(wiki_scaling, "top_build_items", boom)
    text = await realmshark.retrieve_build_knowledge(
        redis_client,
        "What's the max defense for necromancer?",
        ttl_seconds=60,
    )
    assert "REALMSHARK SOURCE OF TRUTH" in text
    assert "SET VISUALIZER PICKS" not in text
    assert "SLOT ALTERNATIVES" not in text


def test_class_max_stats_format_includes_wiki_total():
    text = wiki_scaling.format_class_max_stats(
        {
            "class_name": "Necromancer",
            "rows": [
                {
                    "stat": "Defense",
                    "items": ["Candy-Coated Armor"],
                    "total": 66,
                }
            ],
        },
        stat="Defense",
    )
    assert "wiki total 66" in text
    assert "[item:Candy-Coated Armor]" in text


def test_on_equip_bonuses_reads_each_stat():
    item = ItemProfile(name="Vesture of Duality", stats={"On Equip": "+16 ATT, +6 DEX"})
    assert wiki_scaling.on_equip_bonuses(item) == {"Attack": 16, "Dexterity": 6}


async def _seed_turbine_bard(redis) -> None:
    profile = PlayerProfile(
        username="Turbine",
        characters=[
            CharacterSummary(
                class_name="Wizard",
                fame=10,
                equipment=[],
            ),
            CharacterSummary(
                class_name="Bard",
                fame=400,
                stats_maxed="8/8",
                stats=CharacterStats(
                    hp=670,
                    mp=385,
                    attack=80,
                    defense=25,
                    speed=55,
                    dexterity=70,
                    vitality=40,
                    wisdom=75,
                ),
                equipment=[
                    EquipmentItem(
                        name="Thousand Shot",
                        tooltip="Divine Thousand Shot UT\nFlurry of Blows IV",
                    ),
                    EquipmentItem(name="Lute of the Necropolis", tooltip="Divine Lute"),
                    EquipmentItem(
                        name="Vesture of Duality",
                        tooltip="Divine Vesture of Duality",
                    ),
                    EquipmentItem(
                        name="Ring of Unbound Attack",
                        tooltip="Untiered Ring of Unbound Attack",
                    ),
                ],
            ),
        ],
    )
    await redis.set(f"{PLAYER_CACHE_PREFIX}turbine", profile.model_dump_json())
    bow = ItemProfile(
        name="Thousand Shot",
        stats={"Damage": "90-110", "Shots": "5", "Rate of Fire": "50%"},
    )
    await redis.set(f"{ITEM_CACHE_PREFIX}:thousand shot", bow.model_dump_json())
    lute = ItemProfile(
        name="Lute of the Necropolis",
        stats={
            "Damage": "200 (+3 for every WIS above 50)",
            "Shots": "1",
            "MP Cost": "110",
        },
    )
    await redis.set(f"{ITEM_CACHE_PREFIX}:lute of the necropolis", lute.model_dump_json())
    vesture = ItemProfile(
        name="Vesture of Duality",
        stats={
            "On Equip": "+12 DEF, +5 SPD, +5 ATT, +40 MP",
            "Reactive Proc(s)": (
                "On Ability Use: ATT Boost(+15 ATT) and DEF Decrease(-6 DEF) "
                "on self for 5 seconds"
            ),
        },
    )
    await redis.set(
        f"{ITEM_CACHE_PREFIX}:vesture of duality",
        vesture.model_dump_json(),
    )
    ring = ItemProfile(
        name="Ring of Unbound Attack",
        stats={"On Equip": "+10 ATT"},
    )
    await redis.set(
        f"{ITEM_CACHE_PREFIX}:ring of unbound attack",
        ring.model_dump_json(),
    )


async def test_player_bard_dps_uses_scraped_character_gear(redis_client):
    await _seed_turbine_bard(redis_client)
    text = await dps_specialist.retrieve_dps_brief(
        redis_client,
        "What's the DPS for Turbine's bard?",
        ttl_seconds=60,
        class_name="Bard",
        player_ign="Turbine",
        player_ttl_seconds=120,
        cache_only=True,
    )
    assert "PLAYER SET DPS" in text
    assert "Turbine" in text
    assert "Bard" in text
    assert "[item:Thousand Shot]" in text
    assert "[item:Lute of the Necropolis]" in text
    assert "[item:Vesture of Duality]" in text
    assert "potential DPS" in text
    assert "This is not a RealmShark leaderboard row" in text
    assert "Copy the player-set reconstruct above" in text
    assert "Do not invent this character's gear" not in text
    assert "character row" in text
    assert "HOW EACH WORN PIECE" in text
    assert "ring: [item:Ring of Unbound Attack]" in text
    assert "1.5 + 6.5" in text
    assert "Flurry of Blows IV" in text
    assert "WIKI ITEM DATA" not in text


async def test_build_knowledge_player_bard_dps_does_not_hide_gear(redis_client):
    await _seed_turbine_bard(redis_client)
    for msg in (
        "What's the DPS for Turbine's bard?",
        "How much potential DPS does Turbine's bard have?",
    ):
        text = await realmshark.retrieve_build_knowledge(
            redis_client,
            msg,
            ttl_seconds=60,
            player_ttl_seconds=120,
        )
        assert "PLAYER SET DPS" in text, msg
        assert "[item:Thousand Shot]" in text, msg
        assert "SET VISUALIZER PICKS" not in text
        assert "Redwood Bow" not in text
        assert "The Triangle" not in text
        assert "Do not list characters" not in text
        assert "character row" in text, msg
        assert "HOW EACH WORN PIECE" in text, msg


async def _bard_dps(redis) -> str:
    return await dps_specialist.retrieve_dps_brief(
        redis,
        "What's the DPS for Turbine's bard?",
        ttl_seconds=60,
        class_name="Bard",
        player_ign="Turbine",
        player_ttl_seconds=120,
        cache_only=True,
    )


async def test_worn_gear_missing_from_the_store_is_scraped_for_the_reconstruct(
    redis_client, monkeypatch
):
    """One un-warmed worn piece used to sink the whole reconstruct to no numbers."""
    await _seed_turbine_bard(redis_client)
    await redis_client.delete(f"{ITEM_CACHE_PREFIX}:thousand shot")
    asked: list[list[str]] = []

    async def fake_batch(names):
        asked.append(list(names))
        return [
            ItemProfile(
                name="Thousand Shot",
                stats={"Damage": "90-110", "Shots": "5", "Rate of Fire": "50%"},
            )
        ]

    monkeypatch.setattr(wiki_scaling, "scrape_items_batch", fake_batch)
    text = await _bard_dps(redis_client)
    assert asked == [["Thousand Shot"]]
    assert "No stored wiki profile for [item:Thousand Shot]" not in text
    assert "Not enough stored wiki shot/ability data" not in text
    assert "potential DPS" in text


async def test_worn_gear_with_no_wiki_page_is_remembered_not_rescraped(
    redis_client, monkeypatch
):
    await _seed_turbine_bard(redis_client)
    await redis_client.delete(f"{ITEM_CACHE_PREFIX}:thousand shot")
    calls: list[list[str]] = []

    async def empty_batch(names):
        calls.append(list(names))
        return []

    monkeypatch.setattr(wiki_scaling, "scrape_items_batch", empty_batch)
    first = await _bard_dps(redis_client)
    assert "No stored wiki profile for [item:Thousand Shot]" in first
    assert await wiki_scaling.is_item_marked_missing(redis_client, "Thousand Shot")

    await _bard_dps(redis_client)
    assert calls == [["Thousand Shot"]]


async def test_unreconstructable_ability_is_not_called_potential_dps(redis_client):
    """A summon/tick ability has no Damage row, so the total is a floor."""
    await _seed_turbine_bard(redis_client)
    summon = ItemProfile(
        name="Lute of the Necropolis",
        stats={
            "MP Cost": "110",
            "Effect(s)": "On Ability Use: Summons 4 portals which deal 350 damage",
        },
    )
    await redis_client.set(
        f"{ITEM_CACHE_PREFIX}:lute of the necropolis",
        summon.model_dump_json(),
    )
    text = await _bard_dps(redis_client)
    assert "weapon-only DPS" in text
    assert "The ability half ([item:Lute of the Necropolis])" in text
    assert "not the ceiling" in text
    assert "potential DPS **" not in text


async def test_worn_gear_scrape_failure_still_returns_the_scraped_profile(
    redis_client, monkeypatch
):
    """A dead scraper must not lose the pieces already in the store."""
    await _seed_turbine_bard(redis_client)
    await redis_client.delete(f"{ITEM_CACHE_PREFIX}:thousand shot")

    async def boom(names):
        raise RuntimeError("playwright is down")

    monkeypatch.setattr(wiki_scaling, "scrape_items_batch", boom)
    text = await _bard_dps(redis_client)
    assert "[item:Lute of the Necropolis]" in text
    assert "No stored wiki profile for [item:Thousand Shot]" in text
    assert "potential DPS" in text


def _makakoyumi() -> ItemProfile:
    """The real cached rows: one bow shot plus a summon shot, in one Damage row."""
    return ItemProfile(
        name="Makakoyumi",
        stats={
            "Shots": "1",
            "Damage": "800; 20\u201340 (average: 30)",
            "Rate of Fire": "33%; 200%",
            "Effect(s)": "Shots hit multiple targets\nShots pass through obstacles",
            "Summon Effect(s)": "Shots hit multiple targets\nIgnores defense of target",
        },
    )


def test_a_summons_piercing_does_not_exempt_the_wielders_own_shot():
    """Piercing belongs to a projectile, not to the weapon.

    Makakoyumi's 800 damage shot is the bow's and pays DEF in full; the 20-40 at
    200% is the summon's and ignores it. Reading `Summon Effect(s)` as if it
    described the whole weapon exempted 96 cached weapons from enemy DEF.
    """
    est = dps_specialist.estimate_weapon_dps(
        _makakoyumi().stats, dex=71, att=125
    )
    assert [g["pierces"] for g in est["groups"]] == [False, True]
    assert est["armor_piercing"] is False  # not ALL shots pierce
    assert est["any_piercing"] is True

    steps: dict = {}
    dps_specialist.reconstruct_weapon_damage(
        est, att=125, dex=71, debug={}, steps=steps, enemy_def=15.0
    )
    bow, summon = steps["groups"]
    # The bow's hit is reduced by DEF, the summon's is not.
    assert bow["hit"] < 800 * est["att_mult"] * steps["buff_mult"]
    assert summon["hit"] == pytest.approx(
        29.5 * est["att_mult"] * steps["buff_mult"], rel=1e-6
    )


def test_enemy_def_comes_off_each_projectile_not_the_total():
    """DEF is subtracted per shot, so it punishes a multi-shot weapon harder."""
    stats = {"Damage": "95-110", "Shots": "3", "Rate of Fire": "100%"}
    est = dps_specialist.estimate_weapon_dps(stats, dex=50, att=50)
    clean = dps_specialist.reconstruct_weapon_damage(
        est, att=50, dex=50, debug={}, enemy_def=0.0
    )
    shielded = dps_specialist.reconstruct_weapon_damage(
        est, att=50, dex=50, debug={}, enemy_def=20.0
    )
    steps: dict = {}
    dps_specialist.reconstruct_weapon_damage(
        est, att=50, dex=50, debug={}, steps=steps, enemy_def=20.0
    )
    # Three shots per volley means three subtractions, not one. Only the
    # post-DEF buffs (Curse, Exposed, Vulnerable) scale the loss; Damaging sits
    # before the subtraction.
    post_def = 1.25 * 1.20 * 1.15
    lost_per_volley = (clean - shielded) / (steps["seconds"] * steps["aps"])
    assert lost_per_volley == pytest.approx(20.0 * 3 * post_def, rel=1e-6)


def test_def_can_never_take_a_hit_below_ten_percent():
    """Wiki: DEF caps out at 90% reduction, however much armor the target has."""
    stats = {"Damage": "10-10", "Shots": "1", "Rate of Fire": "100%"}
    est = dps_specialist.estimate_weapon_dps(stats, dex=50, att=50)
    steps: dict = {}
    dps_specialist.reconstruct_weapon_damage(
        est, att=50, dex=50, debug={}, steps=steps, enemy_def=9999.0
    )
    floor_free = dps_specialist.reconstruct_weapon_damage(
        est, att=50, dex=50, debug={}, enemy_def=0.0
    )
    assert steps["per_second"] > 0
    assert dps_specialist.reconstruct_weapon_damage(
        est, att=50, dex=50, debug={}, enemy_def=9999.0
    ) == pytest.approx(floor_free * 0.10, rel=1e-6)


def test_damaging_applies_before_def_and_curse_after():
    """The order matters the moment enemy DEF is not zero."""
    stats = {"Damage": "100-100", "Shots": "1", "Rate of Fire": "100%"}
    est = dps_specialist.estimate_weapon_dps(stats, dex=50, att=50)
    steps: dict = {}
    total = dps_specialist.reconstruct_weapon_damage(
        est, att=50, dex=50, debug={}, steps=steps, enemy_def=30.0
    )
    att_m = est["att_mult"]
    base = 100.0 * att_m * 1.25  # Damaging, pre-DEF
    expected_hit = (base - 30.0) * (1.25 * 1.20 * 1.15)  # Curse/Exposed/Vulnerable
    assert total == pytest.approx(
        expected_hit * steps["aps"] * steps["seconds"], rel=1e-6
    )


def test_one_items_long_cooldown_does_not_veto_another_items_curse():
    """Sustainability is a per-line judgement.

    Turbine's Huntress wears a trap that inflicts Curse and, separately, an
    amulet with a 1800 second cooldown. Judging the set's combined text let that
    cooldown suppress the trap's Curse and dropped the dummy figure by 25%.
    """
    trap = ItemProfile(
        name="Trap of the Vile Spirit",
        stats={
            "MP Cost": "100",
            "Damage": "1300 (+16 per ATT over 46)",
            "Shots": "1",
            "Effect(s)": "On enemies: Inflicts Curse for 2 (+0.1 per ATT over 46) seconds.",
        },
    )
    amulet = ItemProfile(
        name="Amulet of Restoration",
        stats={
            "Reactive Proc": (
                "Soul Concentration: On taking damage when below 20% HP gain "
                "Invulnerable\nSoul Concentration Cooldown: 1800 seconds"
            )
        },
    )
    assert dps_specialist.set_inflicted_debuffs([trap, amulet]) == {
        "curse": True,
        "expose": False,
        "vulnerable": False,
        "damaging": False,
    }


def test_a_resistance_line_is_not_a_debuff_the_set_inflicts():
    """"Cannot be Cursed" protects the wearer; it is not free damage."""
    robe = ItemProfile(
        name="Immunity Robe",
        stats={"Effect(s)": "Cannot be Cursed\nImmune to Exposed"},
    )
    assert dps_specialist.set_inflicted_debuffs([robe]) == {
        "curse": False,
        "expose": False,
        "vulnerable": False,
        "damaging": False,
    }


def test_the_dummy_figure_is_lower_than_the_ceiling_and_says_why():
    """The brief has to carry a number a solo player can actually measure."""
    bow = _makakoyumi()
    trap = ItemProfile(
        name="Trap of the Vile Spirit",
        stats={
            "MP Cost": "100",
            "Damage": "1300 (+16 per ATT over 46)",
            "Shots": "1",
            "Effect(s)": "On enemies: Inflicts Curse for 2 seconds.",
        },
    )
    est = dps_specialist.estimate_weapon_dps(bow.stats, dex=71, att=125)
    formula = dps_specialist.parse_ability_formula(trap.stats)
    text = dps_specialist.format_practice_dummy(
        est,
        formula,
        att=125,
        dex=71,
        stats={"Attack": 125.0},
        worn_items=[bow, trap],
        ceiling=124_183.6,
    )
    assert "15 DEF" in text
    assert "Curse" in text  # the one debuff this set puts up on its own
    assert "[item:Trap of the Vile Spirit]" in text
    assert "no party buffs" in text
    # It must not read as the headline number.
    assert "124,183.6" in text


def test_flavor_cursed_is_not_the_curse_status():
    """Vesture's description is 'This cursed robe'. That is not inflicting Curse.

    The follow-up on Turbine's Bard copied 'except Curse from your own procs'
    from the Huntress turn even though no Bard piece inflicts Curse. Matching
    the adjective `cursed` would have produced the same lie in the specialist
    brief itself.
    """
    vesture = ItemProfile(
        name="Vesture of Duality",
        stats={
            "On Equip": "+12 DEF, +5 SPD, +5 ATT, +40 MP",
            "Reactive Proc": (
                "On Ability Use: ATT Boost (+15 ATT) and DEF Decrease "
                "(-6 DEF) on self for 5 seconds"
            ),
            "Description": "This cursed robe overwhelms the wearer.",
        },
    )
    triangle = ItemProfile(
        name="The Triangle",
        stats={
            "On Equip": "+3 ATT, +3 WIS",
            "Effect(s)": (
                "Self Only: On use, quadruples shot speed for 4 seconds.\n"
                "ATT Boost: +5 (+1 per 8 WIS over 75) ATT"
            ),
            "Damage": "300-450 (+25 per ATT over 55) (average: 375)",
            "Shots": "3",
            "MP Cost": "100",
        },
    )
    warmonger = ItemProfile(
        name="Warmonger",
        stats={
            "Damage": "95-110",
            "Shots": "2",
            "Rate of Fire": "120%",
            "Reactive Proc": "On Shoot: When in combat, DEX Decrease (-5 DEX) for 1 second",
        },
    )
    gem = ItemProfile(
        name="The Twilight Gemstone",
        stats={"On Equip": "+110 MP, +8 DEF, +5 SPD, +5 WIS"},
    )
    bard = [warmonger, triangle, vesture, gem]
    assert dps_specialist.set_inflicted_debuffs(bard) == {
        "curse": False,
        "expose": False,
        "vulnerable": False,
        "damaging": False,
    }
    assert "curse" not in dps_specialist.parse_status_grants(vesture)
    text = dps_specialist.format_practice_dummy(
        dps_specialist.estimate_weapon_dps(warmonger.stats, dex=68, att=96),
        dps_specialist.parse_ability_formula(triangle.stats),
        att=96,
        dex=68,
        stats={"Attack": 96.0},
        worn_items=bard,
        ceiling=119_671.1,
    )
    assert "none of Curse, Exposed, Vulnerable, or Damaging" in text
    assert "Never write 'except Curse from your own procs'" in text
    assert "Curse from [item:" not in text


def test_working_stats_name_both_ability_attack_procs():
    """Sheet ATT 76 plus Triangle +5 plus Vesture +15 is 96, and both items
    have to appear in the brief so a reader can check the working Attack."""
    vesture = ItemProfile(
        name="Vesture of Duality",
        stats={
            "Reactive Proc": (
                "On Ability Use: ATT Boost (+15 ATT) and DEF Decrease "
                "(-6 DEF) on self for 5 seconds"
            )
        },
    )
    triangle = ItemProfile(
        name="The Triangle",
        stats={
            "Effect(s)": (
                "Self Only: On use, quadruples shot speed for 4 seconds.\n"
                "ATT Boost: +5 (+1 per 8 WIS over 75) ATT"
            )
        },
    )
    warmonger = ItemProfile(
        name="Warmonger",
        stats={
            "Reactive Proc": "On Shoot: When in combat, DEX Decrease (-5 DEX) for 1 second"
        },
    )
    catalog = dps_specialist.inspect_worn_set([warmonger, triangle, vesture])
    sheet = {"Attack": 76.0, "Dexterity": 73.0, "Wisdom": 67.0}
    working = dps_specialist.combat_stat_sheet(sheet, catalog)
    assert working["Attack"] == pytest.approx(96.0)
    assert working["Dexterity"] == pytest.approx(68.0)
    text = dps_specialist.format_working_stats(sheet, catalog, working)
    assert "[item:The Triangle]" in text
    assert "[item:Vesture of Duality]" in text
    assert "On ability +5" in text
    assert "On ability +15" in text
    assert "[item:Warmonger]" in text
    assert "On shoot -5" in text
    assert "Attack:" in text and "= 96" in text


def test_a_zero_damage_row_does_not_hide_the_real_ability_hit():
    """Trap of the Vile Spirit lists Damage: 0 and puts the hit on
    Sticky Bomb Damage. Returning the zero row dropped the ability half."""
    formula = dps_specialist.parse_ability_formula(
        {
            "MP Cost": "90",
            "Damage": "0",
            "Sticky Bomb Damage": "1300 (+16 per ATT over 46)",
            "Sticky Bomb Targets": "1",
            "Shots": "1",
        }
    )
    assert formula is not None
    assert formula["avg"] == 1300
    assert formula["per"] == 16
    assert formula["stat"] == "Attack"
    assert formula["threshold"] == 46

