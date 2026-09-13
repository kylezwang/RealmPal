from api.services.dungeon_guide import (
    _SHATTERS_PORTAL_FALLBACK,
    _SOURCE_SPRITE_FALLBACK,
    _focus_text,
    _merge_media,
    portal_for_dungeon,
)


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
