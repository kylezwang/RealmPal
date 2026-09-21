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


def test_hardmode_shatters_matches_core_pages_when_index_is_empty():
    """Found live Sep 18: after an API restart the dungeon index was empty,
    cache-only chat only merged biomes + Keyper, and Claude was told the
    RealmEye indexes have no Hardmode Shatters page."""
    from api.services.dungeon_guide import _index_with_fallbacks

    assert extract_dungeon_query("Guide to complete Hardmode Shatters") == (
        "Hardmode Shatters"
    )
    hits = match_index_pages("Hardmode Shatters", _index_with_fallbacks([]))
    assert hits
    assert any(row.get("slug") == "the-shatters" for row in hits)


async def test_hardmode_shatters_guide_does_not_claim_missing_index(
    redis_client, monkeypatch
):
    from api.services import dungeon_guide

    async def fake_wiki(redis, slug, *, ttl_seconds, force=False, cache_only=False):
        if slug != "the-shatters":
            return None
        return {
            "title": "The Shatters",
            "slug": "the-shatters",
            "url": "https://www.realmeye.com/wiki/the-shatters",
            "text": "Hard Mode\n\nKill the Source then Valen, Nox, and Azamoth.\n",
        }

    monkeypatch.setattr(dungeon_guide, "get_or_scrape_wiki", fake_wiki)
    text = await dungeon_guide.retrieve_dungeon_guide(
        redis_client, "Hardmode Shatters", ttl_seconds=60, cache_only=True
    )
    assert "no page that matches" not in text
    assert "Kill the Source" in text


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


def test_extract_drop_source_query_keyper_shinies():
    from api.services.dungeon_guide import extract_drop_source_query, merge_event_entries

    parsed = extract_drop_source_query("Can the Keyper drop shinies?")
    assert parsed is not None
    names, shiny = parsed
    assert names == ["Keyper"]
    assert shiny is True
    assert extract_drop_source_query("best attack bard") is None
    entries = merge_event_entries([])
    hits = match_index_pages("Keyper", entries)
    assert hits and hits[0]["slug"] == "the-keyper"


def test_extract_drop_source_query_bosses_and_missing_does():
    from api.services.dungeon_guide import extract_drop_source_query

    parsed = extract_drop_source_query(
        "what Nox the wild shadow and the twilight archmage drops"
    )
    assert parsed is not None
    names, shiny = parsed
    assert shiny is False
    assert [name.lower() for name in names] == [
        "nox the wild shadow",
        "twilight archmage",
    ]
    single = extract_drop_source_query("what does Nox the wild shadow drop")
    assert single is not None
    assert single[0] == ["Nox the wild shadow"]


def test_extract_drop_source_query_does_not_treat_enemy_as_the_source():
    from api.services.dungeon_guide import extract_drop_source_query

    parsed = extract_drop_source_query("what enemy drops ocean trench")
    assert parsed is not None
    names, shiny = parsed
    assert shiny is False
    assert [name.lower() for name in names] == ["ocean trench"]
    assert extract_drop_source_query("what enemies in hardmode shatters drop")[0][
        0
    ].lower() == "hardmode shatters"


def test_group_drops_by_enemy_keeps_boss_order():
    from api.services.dungeon_guide import group_drops_by_enemy

    grouped = group_drops_by_enemy(
        [
            {"name": "Valen Helm", "drops_from": "Valen the Unbreakable"},
            {"name": "Nox Cloak", "drops_from": "Nox the Wild Shadow"},
            {"name": "Valen Ring", "drops_from": "Valen the Unbreakable"},
        ]
    )
    assert [source for source, _items in grouped] == [
        "Valen the Unbreakable",
        "Nox the Wild Shadow",
    ]
    assert grouped[0][1] == ["Valen Helm", "Valen Ring"]


def test_mentions_drop_source_matches_boss_cells():
    from api.services.dungeon_guide import mentions_drop_source

    assert mentions_drop_source("Nox the Wild Shadow", "Nox the wild shadow")
    assert mentions_drop_source("Twilight Archmage", "the twilight archmage")
    assert not mentions_drop_source("Valen the Unbreakable", "Nox the wild shadow")
