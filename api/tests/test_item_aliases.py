"""extract_set_item_names / is_set_visualize_query: telling a four-slot set
request apart from a single-item shiny/divine request.
"""
from __future__ import annotations

import json

from api.services import item_aliases
from api.services.item_aliases import (
    CATALOG_PREFIX,
    CatalogItem,
    community_canonical,
    extract_set_item_names,
    generated_aliases,
    is_set_visualize_query,
    is_stat_class_shiny_divine_query,
    parse_rarity,
    set_visualize_flags,
    resolve_against_catalog,
    resolve_item_query,
    resolve_item_query_with_trim,
    retrieve_set_visualizer,
    score_nickname,
    extract_mentioned_items,
)


async def _seed_catalog(redis_client, items: list[tuple]) -> None:
    """Seed the item catalog cache directly (bypassing a live hub scrape),
    same shape load_item_catalog writes: [{name, slot, aliases, hub}, ...]."""
    payload = []
    for row in items:
        name = row[0]
        slot = row[1]
        hub = row[2] if len(row) > 2 else ""
        payload.append(
            {"name": name, "slot": slot, "aliases": [], "hub": hub}
        )
    await redis_client.set(f"{CATALOG_PREFIX}:all:cached", json.dumps(payload))


def test_with_phrasing_still_extracts_a_set():
    names = extract_set_item_names(
        "shiny divine set with Crown, Sword of Acclaim, Robe, and Ring of Decades"
    )
    assert names == [
        "The Forgotten Crown",
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
    assert names == [
        "Enforcer",
        "ballistic star",
        "Cackling Straitjacket",
        "Chrysalis of Eternity",
    ]


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


def test_single_letter_typo_still_resolves_to_the_real_item():
    """Regression: found live Sep 15 - user intentionally misspelled
    "Bogwood Crook" as "bogwood croak" (a single substituted letter) and
    it failed to resolve at all, so the set visualizer asked for
    clarification instead of rendering. A 1-edit typo on a real 4+ letter
    word should score as strongly as an exact match."""
    item = CatalogItem(name="Bogwood Crook", slot="weapon", aliases=generated_aliases("Bogwood Crook"))
    assert score_nickname("bogwood croak", item) >= 40
    assert resolve_against_catalog("bogwood croak", [item]) == "Bogwood Crook"


def test_short_word_typos_do_not_fuzzy_match_unrelated_items():
    """A coincidental 1-edit hit on a short (<4 char) word is common and
    should not be treated as a typo signal - only 4+ letter words earn
    fuzzy tolerance."""
    orb = CatalogItem(name="Sacred Orb", slot="ability", aliases=generated_aliases("Sacred Orb"))
    assert score_nickname("sacred org", orb) < 40


def test_community_nicknames_for_bows_and_triangle():
    """Sep 16: in-game questions use cbow/lbow/dbow/triangle, and
    extract_enchant_item only consults community_canonical, not the hub
    catalog, so these must live in COMMUNITY_ALIASES."""
    assert community_canonical("cbow") == "Coral Bow"
    assert community_canonical("lbow") == "Leaf Bow"
    assert community_canonical("dbow") == "Doom Bow"
    assert community_canonical("triangle") == "The Triangle"
    assert community_canonical("the triangle") == "The Triangle"
    assert community_canonical("lean crown") == "Chrysalis of Eternity"
    assert community_canonical("crown") == "The Forgotten Crown"
    assert community_canonical("forgotten crown") == "The Forgotten Crown"
    assert community_canonical("gemstone") == "The Twilight Gemstone"
    assert community_canonical("kage") == "Kagenohikari"
    assert community_canonical("snake ring") == "Snake Eye Ring"
    assert community_canonical("enforcer") == "Enforcer"
    assert community_canonical("valor") == "Valor"
    assert community_canonical("tarnished") == "Tools of the Tarnished"
    assert community_canonical("maka") == "Makakoyumi"
    assert community_canonical("lumi") == "Lumiaire"


def test_extract_mentioned_items_returns_cbow_and_lbow():
    """Enchant/DPS comparison needs every nickname, not just the first."""
    assert extract_mentioned_items(
        "is cbow awakening or lbow awakening better"
    ) == ["Coral Bow", "Leaf Bow"]


def test_extract_mentioned_items_does_not_treat_get_as_gem():
    """'get' is 1-edit from the gem nickname; that must not fire."""
    assert extract_mentioned_items(
        "what enchants should I get on Cackling Straitjacket"
    ) == ["Cackling Straitjacket"]


def test_plain_sentence_with_no_shiny_divine_or_with_is_not_a_set():
    assert extract_set_item_names("How to do moonlight village?") == []
    assert not is_set_visualize_query("How to do moonlight village?")


def test_shiny_only_item_list_with_no_set_intent_verb_routes_to_set_visualizer():
    """Regression: found live Sep 15 as "Rare Shiny bogwood croak, rare
    shiny genesis spell, rare diplomatic robe, shiny rare, the twilight
    gemstone" - shiny (no divine) with no "set"/"loadout"/"visualize"/
    "build me"/"show me" verb used to require that verb to trigger the
    visualizer, so this fell through to generic chat, which had no item
    data for these names and asked the user to clarify. Naming 2+ real
    items after a shiny/divine trigger is itself enough signal."""
    message = (
        "Rare Shiny bogwood croak, rare shiny genesis spell, rare diplomatic "
        "robe, shiny rare, the twilight gemstone"
    )
    assert extract_set_item_names(message) == [
        "bogwood croak",
        "genesis spell",
        "diplomatic robe",
        "the twilight gemstone",
    ]
    assert is_set_visualize_query(message)


def test_comma_list_without_with_is_a_named_set():
    names = extract_set_item_names(
        "Rare shiny doom bow, rare shiny vile, rare shiny straitjacket, "
        "legendary shiny ring of skeletal specters"
    )
    lowered = [name.lower() for name in names]
    assert lowered[0] == "doom bow"
    assert "vile" in lowered[1]
    assert "straitjacket" in lowered[2]
    assert "skeletal specters" in lowered[3]


def test_same_set_followup_is_a_visualize_query_with_history():
    from api.services.item_aliases import is_set_followup, last_set_names_from_history

    prior = (
        "Rare shiny doom bow, rare shiny vile, rare shiny straitjacket, "
        "legendary shiny ring of skeletal specters"
    )
    assert is_set_followup("Same set but all divine")
    assert is_set_followup("Show me all shiny divine and awakened")
    assert last_set_names_from_history([prior])[0].lower() == "doom bow"
    assert is_set_visualize_query("Same set but all divine", history=[prior])


def test_parse_rarity_picks_the_highest_tier():
    assert parse_rarity("make it uncommon") == "uncommon"
    assert parse_rarity("make it rare") == "rare"
    assert parse_rarity("make it legendary") == "legendary"
    assert parse_rarity("make it divine") == "divine"
    assert parse_rarity("make it unc") == "uncommon"
    assert parse_rarity("make it leg") == "legendary"
    assert parse_rarity("make it div") == "divine"
    assert parse_rarity("shiny legendary divine straitjacket") == "divine"
    assert parse_rarity("what does shiny snake eye ring look like") is None
    assert set_visualize_flags("make it legendary") == (False, "legendary")
    assert set_visualize_flags("shiny uncommon Crown") == (True, "uncommon")


def test_rarity_word_stripped_from_inside_a_segment_not_just_when_bare():
    """Regression, same live Sep 15 message: "rare genesis spell" and
    "rare diplomatic robe" used to keep their "rare" prefix (only a fully
    bare "rare" segment was dropped), so they never matched the real wiki
    titles ("Genesis Spell", "Diplomatic Robe") downstream. Also covers
    "uncommon"/"legendary" as the user asked these be recognized the same
    way as shiny/divine already were."""
    assert extract_set_item_names(
        "shiny set with legendary war bow, uncommon quiver, rare robe, and divine ring"
    ) == ["war bow", "quiver", "robe", "ring"]


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


# --- is_stat_class_shiny_divine_query / retrieve_set_visualizer's -------
# --- build-derived branch: "show me full shiny divine attack huntress" --

def test_stat_class_shiny_divine_query_needs_shiny_or_divine_and_no_named_items():
    """Regression: found live Sep 14, right after "attack huntress" stopped
    being misread as a literal item name - the message then fell through
    to the generic balanced-loadout brief instead of the set-visualizer
    loadout "full shiny divine X" actually implies."""
    assert is_stat_class_shiny_divine_query(
        "Show me full shiny divine attack huntress", "Huntress", "Attack"
    )
    assert is_stat_class_shiny_divine_query(
        "Show me full legendary attack huntress", "Huntress", "Attack"
    )
    assert is_stat_class_shiny_divine_query(
        "shiny dex huntress please", "Huntress", "Dexterity"
    )
    # No shiny/divine wording at all - a plain build ask stays on the text
    # brief path, this function must not claim it.
    assert not is_stat_class_shiny_divine_query(
        "best items for a dex huntress", "Huntress", "Dexterity"
    )
    # No resolved class+stat - nothing to build a loadout from.
    assert not is_stat_class_shiny_divine_query("shiny divine please", None, None)
    # A real named set always wins over the derived-from-build path.
    assert not is_stat_class_shiny_divine_query(
        "shiny divine set with Crown, Sword of Acclaim, Robe, and Ring of Decades",
        "Huntress",
        "Attack",
    )


async def test_retrieve_set_visualizer_derives_items_from_build_when_none_named(
    redis_client, monkeypatch
):
    async def fake_top_build_items(redis, class_name, stat, *, ttl_seconds, cache_only=True):
        assert class_name == "Huntress"
        assert stat == "Attack"
        return {
            "weapon": "Doom Bow",
            "ability": "Lifebringing Lotus",
            "armor": "Puppy's Collar",
            "ring": "Ring of Transcendent Attack",
        }

    monkeypatch.setattr(item_aliases, "top_build_items", fake_top_build_items)

    text = await retrieve_set_visualizer(
        redis_client,
        "Show me full shiny divine attack huntress",
        ttl_seconds=60,
        class_name="Huntress",
        stat="Attack",
        allow_scrape=False,
    )
    assert "[loadout shiny divine]" in text
    assert "[item:Doom Bow]" in text
    assert "[item:Lifebringing Lotus]" in text
    assert "[item:Puppy's Collar]" in text
    assert "[item:Ring of Transcendent Attack]" in text


async def test_retrieve_set_visualizer_legendary_flags(
    redis_client, monkeypatch
):
    async def fake_top_build_items(redis, class_name, stat, *, ttl_seconds, cache_only=True):
        return {
            "weapon": "Doom Bow",
            "ability": "Lifebringing Lotus",
            "armor": "Puppy's Collar",
            "ring": "Ring of Transcendent Attack",
        }

    monkeypatch.setattr(item_aliases, "top_build_items", fake_top_build_items)

    text = await retrieve_set_visualizer(
        redis_client,
        "Show me full legendary attack huntress",
        ttl_seconds=60,
        class_name="Huntress",
        stat="Attack",
        allow_scrape=False,
    )
    assert "[loadout legendary]" in text
    assert "[item:Doom Bow]" in text


async def test_retrieve_set_visualizer_stays_empty_without_shiny_divine_wording(
    redis_client, monkeypatch
):
    """A plain "best items for a dex huntress" (no shiny/divine wording)
    must not derive a set - that ask stays on the text-brief path."""
    async def boom(*args, **kwargs):
        raise AssertionError("must not derive build items with no shiny/divine wording")

    monkeypatch.setattr(item_aliases, "top_build_items", boom)

    text = await retrieve_set_visualizer(
        redis_client,
        "best items for a dex huntress",
        ttl_seconds=60,
        class_name="Huntress",
        stat="Dexterity",
        allow_scrape=False,
    )
    assert text == ""


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


def test_trailing_all_shiny_divine_does_not_stick_to_crown():
    """Live Sep 16: 'Warmonger, The Triangle, Vesture, and Crown all shiny
    divine' used to leave the last name as 'Crown all'."""
    names = extract_set_item_names(
        "Show me a bard set with Warmonger, The Triangle, Vesture, and Crown "
        "all shiny divine"
    )
    assert names == [
        "Warmonger",
        "The Triangle",
        "Vesture of Duality",
        "The Forgotten Crown",
    ]


async def test_named_bard_set_uses_realmeye_bow_kind_and_forgotten_crown(
    redis_client,
):
    """Live Sep 16: named shiny Bard set called Warmonger a sword and cited
    RealmShark. Catalog hub + Crown alias must drive the set chunk."""
    await _seed_catalog(
        redis_client,
        [
            ("Warmonger", "weapon", "longbows"),
            ("The Triangle", "ability", "lutes"),
            ("Vesture of Duality", "armor", "robes"),
            ("The Forgotten Crown", "ring", "rings"),
        ],
    )
    text = await retrieve_set_visualizer(
        redis_client,
        "Show me a bard set with Warmonger, The Triangle, Vesture of Duality, "
        "and Crown all shiny divine",
        ttl_seconds=60,
        class_name="Bard",
        allow_scrape=False,
    )
    assert "[item:Warmonger]" in text
    assert "[item:The Triangle]" in text
    assert "[item:Vesture of Duality]" in text
    assert "[item:The Forgotten Crown]" in text
    assert "(bow)" in text
    assert "https://www.realmeye.com/wiki/warmonger" in text
    assert "tracker.realmshark" not in text
    assert "Cite the RealmEye wiki URLs" in text


async def test_fungal_star_resolves_from_drop_place(redis_client):
    from api.models.item import ItemProfile
    from api.services.wiki_scaling import write_cached_item

    await _seed_catalog(
        redis_client,
        [("Crystalline Kunai", "ability", "stars")],
    )
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Crystalline Kunai",
            type="Star",
            drop_locations=["Fungal Cavern"],
        ),
        3600,
    )
    assert (
        await resolve_item_query(
            redis_client, "fungal star", ttl_seconds=3600, allow_scrape=False
        )
        == "Crystalline Kunai"
    )
    assert (
        await resolve_item_query(
            redis_client, "crystal star", ttl_seconds=3600, allow_scrape=False
        )
        == "Crystalline Kunai"
    )


async def test_shiny_fungal_star_prefers_ut_not_st(redis_client):
    from api.models.item import ItemProfile
    from api.services.wiki_scaling import write_cached_item

    await _seed_catalog(
        redis_client,
        [
            ("Crystalline Kunai", "ability", "stars"),
            ("Star of Enlightenment", "ability", "stars"),
        ],
    )
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Crystalline Kunai",
            type="Star",
            tier="ST",
            drop_locations=["Fungal Cavern"],
        ),
        3600,
    )
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Star of Enlightenment",
            type="Star",
            tier="UT",
            shiny_sprite_url="https://example.com/enlighten-shiny.png",
            drop_locations=["Crystal Cavern"],
        ),
        3600,
    )
    assert (
        await resolve_item_query(
            redis_client,
            "fungal star",
            ttl_seconds=3600,
            allow_scrape=False,
            prefer_shiny_ut=True,
        )
        == "Star of Enlightenment"
    )
    assert (
        await resolve_item_query(
            redis_client,
            "crystal star",
            ttl_seconds=3600,
            allow_scrape=False,
            prefer_shiny_ut=True,
        )
        == "Star of Enlightenment"
    )


async def test_shiny_place_slot_skips_st_only(redis_client):
    from api.models.item import ItemProfile
    from api.services.wiki_scaling import write_cached_item

    await _seed_catalog(
        redis_client,
        [("Crystalline Kunai", "ability", "stars")],
    )
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Crystalline Kunai",
            type="Star",
            tier="ST",
            drop_locations=["Fungal Cavern"],
        ),
        3600,
    )
    assert (
        await resolve_item_query(
            redis_client,
            "fungal star",
            ttl_seconds=3600,
            allow_scrape=False,
            prefer_shiny_ut=True,
        )
        is None
    )


async def test_staff_synonym_resolves_spellblade(redis_client):
    from api.models.item import ItemProfile
    from api.services.wiki_scaling import write_cached_item

    await _seed_catalog(
        redis_client,
        [("Test Spellblade", "weapon", "spellblades")],
    )
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Test Spellblade",
            type="Spellblade",
            tier="UT",
            drop_locations=["Fungal Cavern"],
        ),
        3600,
    )
    assert (
        await resolve_item_query(
            redis_client, "fungal staff", ttl_seconds=3600, allow_scrape=False
        )
        == "Test Spellblade"
    )
    assert (
        await resolve_item_query(
            redis_client, "crystal spellblade", ttl_seconds=3600, allow_scrape=False
        )
        == "Test Spellblade"
    )


async def test_suggest_skips_st_when_query_is_shiny(redis_client):
    from api.services.item_aliases import SUGGEST_KEY, suggest_terms

    await redis_client.set(
        SUGGEST_KEY,
        json.dumps(
            [
                {
                    "n": "Crystalline Kunai",
                    "a": "fungal star",
                    "k": "item",
                    "t": "ST",
                },
                {
                    "n": "Star of Enlightenment",
                    "a": "fungal star",
                    "k": "item",
                    "t": "UT",
                },
            ]
        ),
    )
    shiny = [row["name"] for row in await suggest_terms(redis_client, "shiny fungal")]
    assert "Star of Enlightenment" in shiny
    assert "Crystalline Kunai" not in shiny


async def test_limited_clone_resolves_to_original(redis_client):
    from api.models.item import ItemProfile
    from api.services.wiki_scaling import write_cached_item

    await _seed_catalog(
        redis_client,
        [("Coral Bow", "weapon", "bows")],
    )
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Holiday Coral Bow",
            limited_edition=True,
            original_name="Coral Bow",
        ),
        3600,
        "Holiday Coral Bow",
    )
    assert (
        await resolve_item_query(
            redis_client,
            "Holiday Coral Bow",
            ttl_seconds=3600,
            allow_scrape=False,
        )
        == "Coral Bow"
    )


async def test_warm_suggest_index_covers_scraped_stores(redis_client):
    from api.models.item import ItemProfile
    from api.services.dungeon_guide import INDEX_CACHE_KEY, PAGE_CACHE_PREFIX
    from api.services.item_aliases import SUGGEST_KEY, suggest_terms, warm_suggest_index
    from api.services.wiki_scaling import HUB_PREFIX, write_cached_item

    await redis_client.set(
        f"{HUB_PREFIX}:staves",
        json.dumps([{"name": "Staff of Extreme Prejudice", "tier": "UT"}]),
    )
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Crystal Sword",
            type="Sword",
            tier="UT",
            drop_locations=["Fungal Cavern"],
        ),
        3600,
    )
    await redis_client.set(
        INDEX_CACHE_KEY,
        json.dumps([{"title": "The Shatters", "slug": "the-shatters"}]),
    )
    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}the-shatters",
        json.dumps(
            {
                "title": "The Shatters",
                "slug": "the-shatters",
                "drops": [
                    {
                        "name": "Brilliance",
                        "drops_from": "Nox the Wild Shadow",
                    }
                ],
            }
        ),
    )
    stats = await warm_suggest_index(redis_client, ttl_seconds=3600)
    assert stats["terms"] > 8
    raw = await redis_client.get(SUGGEST_KEY)
    assert raw
    names = {
        name
        for q in (
            "extreme",
            "crystal sword",
            "shatts",
            "nox",
            "floral",
            "qot",
        )
        for name in [row["name"] for row in await suggest_terms(redis_client, q)]
    }
    assert "Staff of Extreme Prejudice" in names
    assert "Crystal Sword" in names
    assert "The Shatters" in names
    assert "Nox the Wild Shadow" in names
    assert "Floral Escape" in names
    assert "Quiver of Thunder" in names


async def test_suggest_continues_last_word_in_a_sentence(redis_client):
    from api.services.item_aliases import SUGGEST_KEY, suggest_terms

    await redis_client.set(
        SUGGEST_KEY,
        json.dumps(
            [
                {
                    "n": "Cackling Straitjacket",
                    "a": "Cackling Straitjacket",
                    "k": "item",
                },
                {
                    "n": "Cackling Straitjacket",
                    "a": "straitjacket",
                    "k": "item",
                },
            ]
        ),
    )
    hits = await suggest_terms(
        redis_client, "I want to see a shiny strait"
    )
    assert hits
    assert hits[0]["name"] == "Cackling Straitjacket"
    assert hits[0]["alias"].lower().startswith("strait")


async def test_suggest_matches_place_slot_alias(redis_client):
    from api.services.item_aliases import SUGGEST_KEY, suggest_terms

    await redis_client.set(
        SUGGEST_KEY,
        json.dumps(
            [
                {"n": "Crystalline Kunai", "a": "fungal star", "k": "item"},
                {"n": "Fungal Cavern", "a": "Fungal Cavern", "k": "dungeon"},
            ]
        ),
    )
    hits = await suggest_terms(redis_client, "fungal")
    names = [row["name"] for row in hits]
    assert "Crystalline Kunai" in names
    assert "Fungal Cavern" in names
    kunai = next(row for row in hits if row["name"] == "Crystalline Kunai")
    assert kunai.get("alias") == "fungal star"
