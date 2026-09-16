"""RAG must stay on this class/stat so effects do not leak across turns."""
from api.services.rag import build_system_prompt, rag_exclude_slugs


def test_samurai_rag_skips_huntress_traps_and_robes():
    skip = rag_exclude_slugs("Samurai", "Dexterity")
    assert "traps" in skip
    assert "orbs" in skip
    assert "robes" in skip
    assert "leather-armors" in skip
    assert "attack-rings" in skip
    assert "wakizashi" not in skip
    assert "dexterity-rings" not in skip
    assert "heavy-armors" not in skip


def test_system_prompt_does_not_teach_lotus_berserk_as_a_global_rule():
    prompt = build_system_prompt("Source: https://example.test\nunused")
    assert "Lifebringing Lotus" not in prompt
    assert "never invent Berserk" in prompt.lower() or "Never invent Berserk" in prompt


def test_system_prompt_ranks_realmshark_first():
    prompt = build_system_prompt("Source: https://example.test\nunused")
    assert "RealmEye wiki infoboxes and hub tables are the source of truth" not in prompt
    assert "RealmShark first" in prompt
    assert "player overlay" in prompt
    assert "The Triangle" in prompt
    assert "SET VISUALIZER PICKS" in prompt
    assert "UmiEnjoyers BIS tabs" in prompt or "?tab=speed-wizard" in prompt
    assert "Never list a T7 robe" in prompt
