"""extract_set_item_names / is_set_visualize_query: telling a four-slot set
request apart from a single-item shiny/divine request.
"""
from __future__ import annotations

import json

from api.services.item_aliases import (
    CATALOG_PREFIX,
    extract_set_item_names,
    is_set_visualize_query,
    resolve_item_query,
    resolve_item_query_with_trim,
)


async def _seed_catalog(redis_client, items: list[tuple[str, str]]) -> None:
    """Seed the item catalog cache directly (bypassing a live hub scrape),
    same shape load_item_catalog writes: [{name, slot, aliases}, ...]."""
    payload = [{"name": name, "slot": slot, "aliases": []} for name, slot in items]
    await redis_client.set(f"{CATALOG_PREFIX}:all:cached", json.dumps(payload))


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


# --- resolve_item_query_with_trim: the durable fix ---------------------


async def test_trim_resolves_a_real_item_glued_to_a_trailing_question(redis_client, anon_settings):
    """The durable fix, found live Sep 14 (repeatedly): a regex extractor
    only knows where a name starts, not where a punctuation-less trailing
    question ends. "snake eye ring is the awakened enchantment good" has no
    sentence break at all - resolve_item_query alone (whole-string match)
    finds nothing, but trimming trailing words one at a time until a real
    catalog item matches finds "Snake Eye Ring" without needing to know in
    advance that "is"/"the"/"awakened"/etc. were never part of the name."""
    await _seed_catalog(redis_client, [("Snake Eye Ring", "ring")])
    whole = await resolve_item_query(
        redis_client,
        "snake eye ring is the awakened enchantment good",
        ttl_seconds=60,
        allow_scrape=False,
    )
    assert whole is None  # confirms the untrimmed call really does fail

    trimmed = await resolve_item_query_with_trim(
        redis_client, "snake eye ring is the awakened enchantment good", ttl_seconds=60
    )
    assert trimmed == "Snake Eye Ring"


async def test_trim_prefers_the_longest_resolving_prefix(redis_client, anon_settings):
    """Guards against over-trimming: if both "Snake Eye" and "Snake Eye
    Ring" were real catalog items, the longer (more specific) one that
    still resolves should win, not the first short prefix reached."""
    await _seed_catalog(
        redis_client, [("Snake Eye Ring", "ring"), ("Snake Eye", "weapon")]
    )
    resolved = await resolve_item_query_with_trim(
        redis_client, "snake eye ring is good right", ttl_seconds=60
    )
    assert resolved == "Snake Eye Ring"


async def test_trim_returns_none_when_no_prefix_resolves(redis_client, anon_settings):
    await _seed_catalog(redis_client, [("Snake Eye Ring", "ring")])
    resolved = await resolve_item_query_with_trim(
        redis_client, "completely unrelated nonsense text here", ttl_seconds=60
    )
    assert resolved is None


async def test_trim_does_not_resolve_below_min_words(redis_client, anon_settings):
    """A single leading word ("ring") can resolve confidently enough on its
    own to match "Ring of Decades" (verified directly against
    resolve_against_catalog) - but the default min_words=2 stops the
    trim loop one word short of ever trying it, so a message that never
    contains a real 2+-word prefix match falls all the way to None instead
    of guessing off one generic word."""
    await _seed_catalog(redis_client, [("Ring of Decades", "ring")])
    resolved = await resolve_item_query_with_trim(
        redis_client, "ring for my kensei build", ttl_seconds=60
    )
    assert resolved is None
