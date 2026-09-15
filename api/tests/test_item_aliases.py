"""extract_set_item_names / is_set_visualize_query: telling a four-slot set
request apart from a single-item shiny/divine request.
"""
from __future__ import annotations

from api.services.item_aliases import extract_set_item_names, is_set_visualize_query


def test_with_phrasing_still_extracts_a_set():
    names = extract_set_item_names(
        "shiny divine set with Crown, Sword of Acclaim, Robe, and Ring of Decades"
    )
    assert names == [
        "Crown",
        "Sword of Acclaim",
        "Robe",
        "Ring of Decades",
    ]


def test_full_shiny_divine_list_without_with_is_recognized_as_a_set():
    """Regression: found live Sep 14 as "Full shiny divine enforcer,
    ballistic star, straitjacket, and lean" - no "with" anywhere, so this
    used to return [] entirely. stored_answers._shiny_divine_item_name's
    single-item guard (`if extract_set_item_names(...): return None`) never
    tripped, so the whole comma list got swallowed as one bogus "item name"
    and sent to a doomed wiki scrape (guaranteed 404, and the frontend's set
    visualizer spun forever waiting on it)."""
    names = extract_set_item_names(
        "Full shiny divine enforcer, ballistic star, straitjacket, and lean"
    )
    assert names == ["enforcer", "ballistic star", "straitjacket", "lean"]


def test_single_item_shiny_request_is_not_treated_as_a_set():
    """A single name after 'shiny' is stored_answers' single-item path's
    job, not this function's - must keep returning [] so that guard doesn't
    misfire on ordinary single-item requests."""
    assert extract_set_item_names("What does shiny snake eye ring look like?") == []
    assert extract_set_item_names("What does divine Crown look like") == []


def test_full_shiny_divine_list_without_with_routes_to_set_visualizer():
    assert is_set_visualize_query(
        "Full shiny divine enforcer, ballistic star, straitjacket, and lean"
    )


def test_plain_sentence_with_no_shiny_divine_or_with_is_not_a_set():
    assert extract_set_item_names("How to do moonlight village?") == []
    assert not is_set_visualize_query("How to do moonlight village?")


def test_with_phrasing_naming_only_one_item_is_not_a_set():
    """Regression: found live Sep 14 as "Shiny divine snake eye ring. Is it
    insane with the awakened enchantment?" - _WITH_ITEMS matched "with the
    awakened enchantment" and returned a one-item list (the >=2 guard used
    to only apply to the _AFTER_SHINY_DIVINE fallback, not this branch).
    That single bogus "item" ("the awakened enchantment") then got scraped
    as a real wiki page (guaranteed 404) and also made
    stored_answers._shiny_divine_item_name wrongly bail out of the real
    single-item shiny/divine path for "snake eye ring"."""
    assert (
        extract_set_item_names(
            "Shiny divine snake eye ring. Is it insane with the awakened enchantment?"
        )
        == []
    )
    assert not is_set_visualize_query(
        "Shiny divine snake eye ring. Is it insane with the awakened enchantment?"
    )
