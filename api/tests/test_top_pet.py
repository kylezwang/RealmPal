from api.services.scraper import _pick_top_pet


def test_top_pet_is_highest_ability_total_not_first_slot():
    picked = _pick_top_pet(
        [
            {"name": "Monkey Head", "levels": [30, 20, 10]},
            {"name": "Reaper", "levels": [90, 90, 80]},
            {"name": "Penguin", "levels": [50, 50, 40]},
        ]
    )
    assert picked is not None
    assert picked["name"] == "Reaper"


def test_top_pet_tie_breaks_on_highest_single_ability():
    picked = _pick_top_pet(
        [
            {"name": "Even", "levels": [70, 70, 70]},
            {"name": "Spiky", "levels": [100, 60, 50]},
        ]
    )
    assert picked is not None
    assert picked["name"] == "Spiky"
