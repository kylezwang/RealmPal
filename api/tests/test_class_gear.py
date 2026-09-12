import json

from api.models.item import ItemProfile
from api.routers import items as items_router
from api.services.class_gear import class_can_wear_item, class_equipment_hubs
from api.services.wiki_scaling import HUB_PREFIX, write_cached_item


def test_kensei_hubs_are_heavy_katana_sheath_and_rings():
    hubs = class_equipment_hubs("Kensei")
    assert "heavy-armors" in hubs
    assert "katanas" in hubs
    assert "tachis" in hubs
    assert "sheaths" in hubs
    assert "rings" in hubs
    assert "leather-armors" not in hubs
    assert "stars" not in hubs


async def test_kensei_cannot_wear_ninja_leather(redis_client):
    await redis_client.set(
        f"{HUB_PREFIX}:leather-armors",
        json.dumps([
            {"name": "Hirejou Tenne", "tier": "ST"},
            {"name": "Venerable Coral Silk Armor", "tier": "UT"},
            {"name": "Centaur’s Shielding", "tier": "UT"},
        ]),
    )
    await redis_client.set(
        f"{HUB_PREFIX}:heavy-armors",
        json.dumps([{"name": "Sage’s Wakibiki", "tier": "ST"}]),
    )
    await redis_client.set(
        f"{HUB_PREFIX}:katanas",
        json.dumps([{"name": "Enforcer", "tier": "UT"}]),
    )
    await redis_client.set(
        f"{HUB_PREFIX}:rings",
        json.dumps([{"name": "Captain’s Ring", "tier": "UT"}]),
    )
    assert await class_can_wear_item(redis_client, "Kensei", "Hirejou Tenne") is False
    assert await class_can_wear_item(redis_client, "Kensei", "Venerable Coral Silk Armor") is False
    assert await class_can_wear_item(redis_client, "Kensei", "Centaur's Shielding") is False
    assert await class_can_wear_item(redis_client, "Kensei", "Enforcer") is True
    assert await class_can_wear_item(redis_client, "Kensei", "Captain's Ring") is True
    assert await class_can_wear_item(redis_client, "Kensei", "Sage's Wakibiki") is True


async def test_item_endpoint_marks_leather_unwearable_for_kensei(
    redis_client, anon_settings, monkeypatch
):
    item = ItemProfile(
        name="Hirejou Tenne",
        sprite_url="https://www.realmeye.com/s/a/img/wiki/tenne.png",
    )
    await write_cached_item(redis_client, item, 60)
    await redis_client.set(
        f"{HUB_PREFIX}:leather-armors",
        json.dumps([{"name": "Hirejou Tenne", "tier": "ST"}]),
    )

    async def boom(*args, **kwargs):
        raise AssertionError("must not scrape a warmed profile")

    monkeypatch.setattr(items_router, "scrape_item", boom)
    monkeypatch.setattr(items_router, "resolve_item_query", boom)

    found = await items_router.get_item(
        "Hirejou Tenne",
        anon_settings,
        redis_client,
        object(),
        class_name="Kensei",
    )
    assert found.sprite_url == item.sprite_url
    assert found.wearable is False

    open_lookup = await items_router.get_item(
        "Hirejou Tenne",
        anon_settings,
        redis_client,
        object(),
    )
    assert open_lookup.wearable is None
