"""Skin visualizer query detection and outfit parsing."""
import json

import pytest

from api.services.skin_visualizer import (
    compose_skin_stored_reply,
    extract_outfit_query,
    is_skin_visualize_query,
)


def test_look_like_with_cloth_is_skin_query():
    msg = "What does Vampire Slayer Archer look like with Large Crown cloth?"
    assert is_skin_visualize_query(msg)


def test_extract_vampire_slayer_archer_outfit():
    msg = "What does Vampire Slayer Archer look like with Large Crown cloth?"
    query = extract_outfit_query(msg)
    assert query.class_name == "Archer"
    assert query.skin_name == "Vampire Slayer"
    assert query.clothing == "Large Crown cloth"
    assert query.accessory is None


def test_ambiguous_crown_cloth_defaults_large():
    msg = "What does Vampire Slayer Archer look like with crown cloth?"
    query = extract_outfit_query(msg)
    assert query.clothing == "Large crown cloth"


def test_followup_small_black_dye_is_skin_query():
    history = [
        "What does Vampire Slayer Archer look like with Large Crown cloth?",
    ]
    msg = "Let me see with small black dye"
    assert is_skin_visualize_query(msg, history=history)


def test_followup_extracts_merged_outfit():
    history = [
        "What does Vampire Slayer Archer look like with Large Crown cloth?",
    ]
    msg = "Let me see with small black dye"
    query = extract_outfit_query(msg, history=history)
    assert query.class_name == "Archer"
    assert query.skin_name == "Vampire Slayer"
    assert query.clothing == "Large Crown cloth"
    assert query.accessory == "small black dye"


def test_followup_uses_skin_token_history():
    history = [
        "What does Vampire Slayer Archer look like with Large Crown cloth?",
        "[skin:Archer|Vampire Slayer|Large Crown Cloth|]\n\nComposited from RealmEye.",
    ]
    query = extract_outfit_query("Let me see with small black dye", history=history)
    assert query.skin_name == "Vampire Slayer"
    assert query.clothing == "Large Crown Cloth"
    assert query.accessory == "small black dye"


def test_large_and_small_crown_cloth():
    msg = "What does Vampire Slayer Archer look like with Large and small Crown cloth?"
    query = extract_outfit_query(msg)
    assert query.class_name == "Archer"
    assert query.skin_name == "Vampire Slayer"
    assert query.clothing == "Large Crown cloth"
    assert query.accessory == "Small Crown cloth"


def test_followup_black_dye_on_the_other():
    history = [
        "What does Vampire Slayer Archer look like with Large Crown cloth?",
        "[skin:Archer|Vampire Slayer|Large Crown Cloth|]",
    ]
    msg = "Let me see with black dye on the other"
    assert is_skin_visualize_query(msg, history=history)
    query = extract_outfit_query(msg, history=history)
    assert query.class_name == "Archer"
    assert query.skin_name == "Vampire Slayer"
    assert query.clothing == "Large Crown Cloth"
    assert query.accessory == "black dye"


def test_followup_what_does_it_look_like_if_i_use_small_black_dye():
    history = [
        "What does Vampire Slayer Archer look like with Large and small Crown cloth?",
        "[skin:Archer|Vampire Slayer|Large Crown Cloth|Small Crown Cloth]",
    ]
    msg = "What does it look like if I use small black dye"
    assert is_skin_visualize_query(msg, history=history)
    query = extract_outfit_query(msg, history=history)
    assert query.class_name == "Archer"
    assert query.skin_name == "Vampire Slayer"
    assert query.clothing == "Large Crown Cloth"
    assert query.accessory == "small black dye"


def test_followup_black_dye_accessory_keeps_skin():
    history = [
        "What does Vampire Slayer Archer look like with Large Crown cloth?",
        "[skin:Archer|Vampire Slayer|Large Crown Cloth|]",
    ]
    msg = "black dye accessory"
    assert is_skin_visualize_query(msg, history=history)
    query = extract_outfit_query(msg, history=history)
    assert query.skin_name == "Vampire Slayer"
    assert query.clothing == "Large Crown Cloth"
    assert query.accessory == "black dye"


def test_large_and_small_black_dye():
    msg = "What does Vampire Slayer Archer look like with Large and small black dye?"
    query = extract_outfit_query(msg)
    assert query.clothing == "Large black dye"
    assert query.accessory == "Small black dye"


def test_followup_now_switch_swaps_slots():
    history = [
        "What does Vampire Slayer Archer look like with Large Crown cloth?",
        "[skin:Archer|Vampire Slayer|Large Crown Cloth|Black Accessory Dye]",
    ]
    msg = "Now switch"
    assert is_skin_visualize_query(msg, history=history)
    query = extract_outfit_query(msg, history=history)
    assert query.class_name == "Archer"
    assert query.skin_name == "Vampire Slayer"
    assert query.clothing == "Black Clothing Dye"
    assert query.accessory == "Small Crown Cloth"


def test_swap_the_cloth_and_dye_converts_sizes():
    history = [
        "[skin:Archer|Vampire Slayer|Large Crown Cloth|Black Accessory Dye]",
    ]
    query = extract_outfit_query("Swap the cloth and dye", history=history)
    assert query.clothing == "Black Clothing Dye"
    assert query.accessory == "Small Crown Cloth"


def test_set_visualize_not_skin_query():
    msg = "Show me a shiny divine Huntress set"
    assert not is_skin_visualize_query(msg)


def test_followup_correction_with_no_cloth_keyword_is_skin_query():
    """Regression: correcting just the skin name ("Sorry I mean X") mentions
    no cloth/dye/clothing/accessory keyword at all, so this previously fell
    through to a real (paid) Claude call with irrelevant RAG context instead
    of the free skin-composite path. Found live Sep 14 - see
    docs/chat-quality-benchmarks.md's Sep 14 production trace."""
    history = [
        "What does Vampire Slayer Archer look like with Large and small Crown cloth?",
        "[skin:Archer|Vampire Slayer|Large Crown cloth|Small Crown cloth]",
    ]
    msg = "Sorry I mean Mini Royal Crossbowman Archer"
    assert is_skin_visualize_query(msg, history=history)


def test_followup_correction_extracts_clean_skin_name_and_keeps_prior_dyes():
    history = [
        "What does Vampire Slayer Archer look like with Large and small Crown cloth?",
        "[skin:Archer|Vampire Slayer|Large Crown cloth|Small Crown cloth]",
    ]
    msg = "Sorry I mean Mini Royal Crossbowman Archer"
    query = extract_outfit_query(msg, history=history)
    assert query.class_name == "Archer"
    assert query.skin_name == "Mini Royal Crossbowman"
    # Prior clothing/accessory carry over - the user only corrected the name.
    assert query.clothing == "Large Crown cloth"
    assert query.accessory == "Small Crown cloth"


def test_i_meant_correction_is_skin_query():
    history = [
        "What does Vampire Slayer Archer look like with Large Crown cloth?",
        "[skin:Archer|Vampire Slayer|Large Crown cloth|]",
    ]
    msg = "I meant Kings Bowman Archer"
    assert is_skin_visualize_query(msg, history=history)
    query = extract_outfit_query(msg, history=history)
    assert query.skin_name == "Kings Bowman"


def test_bare_name_without_outfit_history_is_not_a_skin_query():
    """A bare name with no history and no visualizer/skin keyword at all
    should not be misclassified - only correction-cue phrasing or an
    explicit skin/outfit keyword should trigger this path."""
    assert not is_skin_visualize_query("Mini Royal Crossbowman Archer")


def test_correction_cue_does_not_corrupt_extraction_without_history():
    """_extract_outfit_from_text on its own (no history merge) should not
    stuff the correction phrase or the whole sentence into `clothing`."""
    query = extract_outfit_query("Sorry I mean Mini Royal Crossbowman Archer")
    assert query.class_name == "Archer"
    assert query.skin_name == "Mini Royal Crossbowman"
    assert query.clothing is None
    assert query.accessory is None


@pytest.mark.asyncio
async def test_compose_skin_stored_reply_includes_token(redis_client, anon_settings):
    catalog = {
        "classes": [
            {
                "id": 3,
                "name": "Archer",
                "skins": [{"id": 42, "name": "Vampire Slayer"}],
            }
        ],
        "clothing": [{"id": 7, "name": "Large Crown Cloth"}],
        "accessory": [],
    }
    await redis_client.set("outfit:catalog:v1", json.dumps(catalog))
    portrait_json = json.dumps(
        {
            "class_name": "Archer",
            "class_id": 3,
            "skin_name": "Vampire Slayer",
            "skin_id": 42,
            "clothing": {"name": "Large Crown Cloth", "item_id": 7},
            "accessory": None,
            "portrait_data_uri": "data:image/png;base64,abc",
            "realmeye_url": "https://example.com/outfit",
        }
    )
    await redis_client.set("outfit:portrait:v1:3:42:7:0", portrait_json)

    msg = "What does Vampire Slayer Archer look like with Large Crown cloth?"
    text = await compose_skin_stored_reply(
        redis_client, msg, ttl_seconds=anon_settings.wiki_ttl_seconds
    )
    assert "[skin:Archer|Vampire Slayer|Large Crown Cloth|]" in text
    assert "RealmEye" in text


def test_followup_and_small_sentinel_cloth_too_is_skin_query():
    """Live Sep 16: first visualize was stored; 'And small sentinel cloth too'
    fell through to Sonnet because leftover 'And too' looked like a skin name."""
    history = [
        "What does Vampire Slayer Archer look like with sentinel cloth?",
        "[skin:Archer|Vampire Slayer|Large Sentinel Cloth|]",
    ]
    msg = "And small sentinel cloth too"
    assert is_skin_visualize_query(msg, history=history)
    query = extract_outfit_query(msg, history=history)
    assert query.class_name == "Archer"
    assert query.skin_name == "Vampire Slayer"
    assert query.clothing and "sentinel" in query.clothing.lower()
    assert query.accessory and "small" in query.accessory.lower()
    assert "too" not in (query.skin_name or "").lower()
