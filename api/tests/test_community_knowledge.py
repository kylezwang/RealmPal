"""Community slot lists: cores + RealmShark + Umi, never hub T0 order."""
from api.services.community_knowledge import (
    names_mentioned_in_umi,
    rank_community_slot_names,
    spec_for_slot,
)


def test_rank_community_slot_names_cores_beat_hub_order():
    names = rank_community_slot_names(
        cores=("Makakoyumi",),
        shark_counts={"Warmonger": 3, "Shortbow": 1},
        umi_names=["Clockwork Repeater", "Shortbow"],
    )
    assert names[0] == "Makakoyumi"
    assert names.index("Warmonger") < names.index("Clockwork Repeater")
    assert "Shortbow" in names


def test_rank_community_slot_names_promotes_doom_bow_upgrade():
    names = rank_community_slot_names(
        cores=(),
        shark_counts={"Doom Bow": 4},
        umi_names=[],
    )
    assert names[0] == "Clockwork Repeater"
    assert "Doom Bow" in names


def test_spec_for_slot_bows_uses_archer_family_and_makakoyumi():
    spec = spec_for_slot("bows")
    assert spec is not None
    assert spec.cores == ("Makakoyumi",)
    assert spec.shark_slot == "weapon"
    assert "Archer" in spec.classes
    assert "bows" in spec.hubs


def test_spec_for_slot_swords_uses_divinity():
    spec = spec_for_slot("swords")
    assert spec is not None
    assert "Divinity" in spec.cores
    assert "Damnation" in spec.cores


def test_spec_for_slot_armors_includes_robe_and_leather_cores():
    spec = spec_for_slot("armors")
    assert spec is not None
    assert "Vesture of Duality" in spec.cores
    assert "Cackling Straitjacket" in spec.cores
    assert spec.shark_slot == "armor"


def test_spec_for_slot_rings_uses_top_rings():
    spec = spec_for_slot("rings")
    assert spec is not None
    assert spec.cores[0] == "Chrysalis of Eternity"
    assert "Kagenohikari" in spec.cores


def test_names_mentioned_in_umi_prefers_matching_stat_tab():
    text = (
        "## Umi tab: Attack Archer (?tab=attack-archer)\n"
        "Warmonger\n"
        "## Umi tab: Dexterity Archer (?tab=dexterity-archer)\n"
        "Makakoyumi\n"
    )
    catalog = ["Warmonger", "Makakoyumi"]
    assert names_mentioned_in_umi(text, catalog, stat="Dexterity") == [
        "Makakoyumi"
    ]
    both = names_mentioned_in_umi(text, catalog)
    assert "Warmonger" in both
    assert "Makakoyumi" in both
