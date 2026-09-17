"""Class progression briefs: Sorcerer ratchet and family-shaped sisters."""
from api.services.progression import (
    format_progression,
    parse_progression_query,
    progression_for,
)
from api.services.stored_answers import try_stored_reply


def test_parse_progression_query_needs_class_and_band_words():
    assert parse_progression_query("best early game items for sorcerer") == (
        "Sorcerer",
        "early",
    )
    assert parse_progression_query("sorcerer progression") == ("Sorcerer", None)
    assert parse_progression_query("mid game gear for huntress") == (
        "Huntress",
        "mid",
    )
    assert parse_progression_query("Best items for a dex huntress") is None
    assert parse_progression_query("early game items") is None


def test_sorcerer_progression_uses_the_verified_route():
    text = format_progression(progression_for("Sorcerer"), band="early")
    assert "Scepter of Fulmination" in text
    assert "[item:Scepter of Fulmination]" in text
    assert "Mad Lab" in text
    assert "Cnidaria Rod" in text
    assert "Vesture of Duality" in text
    assert "Awakening" in text
    assert "Sprite Wand" not in text
    assert "you asked about **early game**" in text.lower() or "early game" in text.lower()


def test_huntress_progression_is_bows_not_scepters():
    text = format_progression(progression_for("Huntress"))
    assert "Makakoyumi" in text
    assert "Coral Bow" in text
    assert "Cackling Straitjacket" in text
    assert "Scepter of Fulmination" not in text
    assert "Scepter of Devastation" not in text


def test_wizard_progression_is_staves_and_robes():
    text = format_progression(progression_for("Wizard"))
    assert "Staff of Unholy Sacrifice" in text
    assert "Water Dragon Silk Robe" in text
    assert "Scepter of Fulmination" not in text


async def test_stored_sorcerer_early_game_skips_generic_t6_blurb(
    redis_client, anon_settings
):
    reply = await try_stored_reply(
        redis_client,
        "What are the best early game items for Sorcerer?",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert reply is not None
    assert reply.kind == "progression"
    assert "[item:Scepter of Fulmination]" in reply.text
    assert "Nexus priest" not in reply.text
