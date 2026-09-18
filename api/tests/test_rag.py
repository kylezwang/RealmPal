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
    assert "overall family cores" in prompt
    assert "Never say overlay" in prompt
    assert "The Triangle" in prompt
    assert "SET VISUALIZER PICKS" in prompt
    assert "UmiEnjoyers BIS tabs" in prompt or "?tab=speed-wizard" in prompt
    assert "Never list a T7 robe" in prompt
    assert "Makakoyumi" in prompt
    assert "Enforcer" in prompt
    assert "Snake Eye Ring" in prompt
    assert "unique class+stat" in prompt.lower()
    assert "Fungal Breastplate" in prompt
    assert "Warmonger is a bow" in prompt
    assert "Crown means The Forgotten Crown" in prompt
    assert "potential-DPS and stat numbers" in prompt
    assert "T7 weapons are not best-in-slot" in prompt
    assert "Do not infer that class's usual stat" in prompt


def test_system_prompt_never_invents_item_names_or_loot():
    prompt = build_system_prompt("Source: https://example.test\nunused")
    assert "Never invent player stats, item names, or loot" in prompt
    assert "Do not turn a source name into a made-up item title" in prompt
    assert "dungeon, boss, NPC, or event" in prompt
    assert "name the original, not the LE title" in prompt


def test_system_prompt_names_all_slot_rarities():
    prompt = build_system_prompt("Source: https://example.test\nunused")
    assert "Uncommon (1 diamond)" in prompt
    assert "Legendary (3)" in prompt
    assert "Do not say Legendary, Rare, or Uncommon is not a rarity" in prompt


def test_system_prompt_forbids_disowning_numbers_it_was_given():
    """Regression, found live Sep 17: asked "what do the numbers look like?"
    right after a correct DPS reconstruct, the model apologised and called its
    own number made up, which reads as the whole feature being broken."""
    prompt = build_system_prompt("Source: https://example.test\nunused")
    assert "Never say you invented" in prompt
    assert "HOW THIS RECONSTRUCT WAS BUILT" in prompt
    assert "rather than disowning the earlier answer" in prompt
    assert "rescale from the reconstruct in context" in prompt
