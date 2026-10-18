"""Player IGN extraction, including suggestion-chip placeholders."""
from api.services.player_lookup import extract_player_ign


def test_placeholder_ign_is_not_a_player():
    assert extract_player_ign("Look up player IGN") is None
