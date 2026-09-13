from api.config import Settings
from api.services.budget import cost_micros
from api.services.model_route import pick_chat_model


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        anthropic_api_key="test-key-not-real",
        jwt_secret="test-jwt-secret",
        pii_hash_secret="test-pii-secret",
    )


def test_dungeon_guide_uses_haiku_when_store_has_the_page():
    settings = _settings()
    assert (
        pick_chat_model(
            "Guide to complete The Shatters",
            settings,
            dungeon_only=True,
        )
        == settings.claude_light_model
    )


def test_constrained_build_stays_on_sonnet():
    settings = _settings()
    assert (
        pick_chat_model("best items for a wis kensei but no ST", settings)
        == settings.claude_model
    )


def test_first_time_stat_class_brief_stays_on_sonnet():
    settings = _settings()
    assert pick_chat_model("best items for a vitality rogue", settings) == settings.claude_model


def test_class_nicknames_parse_for_build_routing():
    from api.services.realmshark import parse_query

    settings = _settings()
    cases = [
        ("Best items for a Vitality Pally", "Paladin", "Vitality"),
        ("Best items for a Dex Trix", "Trickster", "Dexterity"),
        ("Best items for a Wis Sorc", "Sorcerer", "Wisdom"),
        ("Best items for a Attack Hunt", "Huntress", "Attack"),
        ("Best items for a Mana Wiz", "Wizard", "MP"),
    ]
    for msg, class_name, stat in cases:
        parsed_class, parsed_stat, buildish = parse_query(msg)
        assert parsed_class == class_name, msg
        assert parsed_stat == stat, msg
        assert buildish
        assert pick_chat_model(msg, settings, context="x" * 500) == settings.claude_model


def test_truncated_rogue_build_stays_on_sonnet():
    from api.services.realmshark import parse_query

    settings = _settings()
    msg = "Best items for a Vitality Rog"
    class_name, stat, buildish = parse_query(msg)
    assert class_name == "Rogue"
    assert stat == "Vitality"
    assert buildish
    assert (
        pick_chat_model(msg, settings, context="x" * 500)
        == settings.claude_model
    )


def test_rich_rag_context_uses_haiku():
    settings = _settings()
    context = "x" * 500
    assert pick_chat_model("what is exaltation", settings, context=context) == (
        settings.claude_light_model
    )


def test_haiku_tokens_are_cheaper_than_sonnet():
    settings = _settings()
    sonnet = cost_micros(settings, 8_000, 600)
    haiku = cost_micros(settings, 8_000, 600, model=settings.claude_light_model)
    assert haiku < sonnet
    assert haiku == 11_000