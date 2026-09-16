from api.services.dungeon_guide import (
    _SHATTERS_PORTAL_FALLBACK,
    _SOURCE_SPRITE_FALLBACK,
    _focus_text,
    _merge_media,
    extract_dungeon_query,
    match_index_pages,
    portal_for_dungeon,
)


def test_extract_dungeon_query_recognizes_how_to_do_phrasing():
    """Regression: "how to do X" was previously invisible to the dungeon
    specialist because _GUIDE_RE only recognized complete/beat/clear/finish
    as guide-request verbs, not "do" - found live Sep 14 asking "How to do
    moonlight village?" and getting a generic "I don't have dungeon guide
    data" reply instead of the real specialist firing."""
    assert extract_dungeon_query("How to do moonlight village?") == "moonlight village"
    assert extract_dungeon_query("how do i do the shatters") == "the shatters"


def test_extract_dungeon_query_recognizes_run_and_solo_phrasing():
    assert extract_dungeon_query("guide to run oryx sanctuary") == "oryx sanctuary"
    assert extract_dungeon_query("how to solo lost halls") == "lost halls"


def test_extract_dungeon_query_still_recognizes_original_verbs():
    assert extract_dungeon_query("how to beat the shatters") == "the shatters"
    assert extract_dungeon_query("how do i complete moonlight village") == "moonlight village"
    assert extract_dungeon_query("guide to clear wine cellar") == "wine cellar"


def test_shatters_guide_uses_real_portal_not_ice():
    assert portal_for_dungeon("The Shatters") == _SHATTERS_PORTAL_FALLBACK
    assert portal_for_dungeon("Guide to complete The Shatters") == _SHATTERS_PORTAL_FALLBACK
    assert portal_for_dungeon("The Shatters - the RotMG Wiki") == _SHATTERS_PORTAL_FALLBACK


def test_hardmode_shatters_uses_source_dome():
    assert portal_for_dungeon("Hardmode Shatters") == _SOURCE_SPRITE_FALLBACK
    assert portal_for_dungeon("The Shatters Hard Mode") == _SOURCE_SPRITE_FALLBACK


def test_merge_media_prefers_index_difficulty_over_page_grave_count():
    pages = [
        {
            "title": "Cultist Hideout",
            "url": "https://www.realmeye.com/wiki/cultist-hideout",
            "difficulty": 3,
            "layouts": [],
            "drops": [],
        }
    ]
    matches = [
        {
            "title": "Cultist Hideout",
            "difficulty": 9,
            "portal_url": "https://example.com/portal.png",
        }
    ]
    media = _merge_media(pages, matches)
    assert media["difficulty"] == 9


def test_hardmode_focus_can_skip_the_regular_lead():
    body = (
        "The Shatters is an extremely dangerous and lengthy dungeon.\n\n"
        "Hard Mode\n"
        "Kill the Source and then fight Valen, Nox, and Azamoth.\n"
    )
    with_lead = _focus_text(body, "Hardmode Shatters")
    assert "extremely dangerous" in with_lead
    player = _focus_text(body, "Hardmode Shatters", include_lead=False)
    assert "extremely dangerous" not in player
    assert "Kill the Source" in player


def test_hardmode_focus_skips_the_contents_listing():
    body = (
        "Hard Mode\n"
        "Drops of Interest\n"
        "History\n\n"
        "The Shatters is an extremely dangerous and lengthy dungeon.\n\n"
        "Hard Mode\n\n"
        "In Exalt Version 2.3.0.0 a secret Hard Mode was added.\n"
        "Kill the Source and then fight Valen, Nox, and Azamoth.\n"
    )
    player = _focus_text(body, "Hardmode Shatters", include_lead=False)
    assert "extremely dangerous" not in player
    assert "secret Hard Mode was added" in player
    assert "Kill the Source" in player


def test_one_letter_dungeon_typos_still_match_the_index():
    assert extract_dungeon_query("how to do moonlite village") == "moonlite village"
    assert extract_dungeon_query("how to do shaters") == "shaters"
    entries = [
        {"title": "Moonlight Village", "slug": "moonlight-village", "kind": "guide"},
        {"title": "The Shatters", "slug": "the-shatters", "kind": "guide"},
    ]
    mv = match_index_pages("moonlite village", entries)
    assert mv and mv[0]["title"] == "Moonlight Village"
    shatts = match_index_pages("shaters", entries)
    assert shatts and shatts[0]["title"] == "The Shatters"
