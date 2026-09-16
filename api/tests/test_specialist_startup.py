"""Empty Redis is warmed on boot; a full store is left alone."""
from __future__ import annotations

import asyncio
import json

from api import main
from api.models.build import CLASS_ABILITY_HUB
from api.services.specialist_warm import (
    INDEX_HUB_SLUGS,
    has_missing_work,
    missing_specialist_work,
)
from api.services.wiki_scaling import CACHE_PREFIX, HUB_PREFIX
from api.services.specialist_warm import REQUIRED_HUB_SLUGS
from api.services.dungeon_guide import INDEX_CACHE_KEY
from api.services.enchanting import CACHE_KEY as ENCHANTING_CACHE_KEY
from api.services.realmshark import GRAPH_CACHE_KEY
from api.services.skin_visualizer import CATALOG_KEY


def _full_snapshot() -> dict:
    return {
        "abilities": [
            {"class_name": name, "abilities": 1, "ttl_seconds": 60}
            for name in CLASS_ABILITY_HUB
        ],
        "hubs": [
            {"slug": slug, "items": 1, "ttl_seconds": 60}
            for slug in REQUIRED_HUB_SLUGS
        ],
        "items": {"cached": 10, "total": 10},
        "dungeons": {"cached": 4, "total": 4, "index": 1},
        "dps": {"graph": 1, "loadouts": 3, "edges": 3},
        "umi": [
            {"class_name": name, "stored": 1, "ttl_seconds": 60}
            for name in CLASS_ABILITY_HUB
        ],
        "skins": {"stored": 1, "classes": 19, "ttl_seconds": 60},
        "enchanting": {"stored": 1, "rolls": 30, "ttl_seconds": 60},
    }


def test_missing_work_is_empty_when_every_store_is_full():
    work = missing_specialist_work(_full_snapshot())
    assert has_missing_work(work) is False


def test_item_warm_skips_tiered_junk_and_broken_names():
    from api.services.specialist_warm import should_warm_item

    assert should_warm_item({"name": "Doom Bow", "tier": "UT"}) is True
    assert should_warm_item({"name": "Quiver of Elvish Mastery", "tier": "T7"}) is True
    assert should_warm_item({"name": "Chrysalis of Eternity", "tier": ""}) is True
    assert should_warm_item({"name": "Steel Dagger", "tier": "2"}) is False
    assert should_warm_item({"name": "Valor (Rehearsal)", "tier": "UT"}) is False
    assert should_warm_item({"name": "B.O.W.", "tier": "UT"}) is False
    assert should_warm_item({"name": "E.Y.E.", "tier": "UT"}) is False
    assert should_warm_item({"name": "Babel Blocks", "tier": "UT"}) is False


async def test_item_status_counts_curly_apostrophe_warm_keys(redis_client):
    from api.services.specialist_warm import item_store_status
    from api.services.wiki_scaling import HUB_PREFIX, ITEM_CACHE_PREFIX

    await redis_client.set(
        f"{HUB_PREFIX}:daggers",
        json.dumps([{"name": "Hero's Dagger", "tier": "UT"}]),
    )
    await redis_client.set(
        f"{ITEM_CACHE_PREFIX}:hero’s dagger",
        json.dumps({"name": "Hero’s Dagger"}),
    )
    status = await item_store_status(redis_client)
    assert status == {"cached": 1, "total": 1}


def test_missing_work_sees_empty_dungeons_and_hubs():
    snap = _full_snapshot()
    snap["dungeons"] = {"cached": 0, "total": 0, "index": 0}
    real_hub = next(row for row in snap["hubs"] if row["slug"] not in INDEX_HUB_SLUGS)
    real_hub["items"] = 0
    work = missing_specialist_work(snap)
    assert work["dungeons"] is True
    assert real_hub["slug"] in work["hubs"]
    assert "player" not in work


def test_category_hubs_and_a_few_dead_pages_are_not_missing_work():
    snap = _full_snapshot()
    for row in snap["hubs"]:
        if row["slug"] in INDEX_HUB_SLUGS:
            row["items"] = 0
    snap["items"] = {"cached": 1255, "total": 1256}
    snap["dungeons"] = {"cached": 171, "total": 179, "index": 1}
    snap["dps"] = {"graph": 1, "loadouts": 34, "edges": 36}
    work = missing_specialist_work(snap)
    assert work["hubs"] == []
    assert work["items"] is False
    assert work["dungeons"] is False
    assert work["dps"] is False
    assert has_missing_work(work) is False


async def test_startup_does_not_warm_when_every_store_is_full(
    redis_client, anon_settings, monkeypatch
):
    for name in CLASS_ABILITY_HUB:
        await redis_client.set(
            f"{CACHE_PREFIX}:{name.lower()}",
            json.dumps({"abilities": [{"name": "x"}]}),
        )
    for slug in REQUIRED_HUB_SLUGS:
        await redis_client.set(f"{HUB_PREFIX}:{slug}", json.dumps([{"name": "x"}]))
    await redis_client.set("item:profile:v3:x", json.dumps({"name": "x"}))
    await redis_client.set(INDEX_CACHE_KEY, json.dumps([{"slug": "udl"}]))
    await redis_client.set("wiki:guide:v6:udl", json.dumps({"title": "UDL"}))
    await redis_client.set(
        GRAPH_CACHE_KEY, json.dumps({"season": "s", "edges": []})
    )
    await redis_client.set(
        CATALOG_KEY, json.dumps({"classes": [{"name": "Wizard"}], "clothing": [], "accessory": []})
    )
    for name in CLASS_ABILITY_HUB:
        await redis_client.set(f"umi:bis:v2:{name.lower()}", json.dumps(["t", "u"]))
    await redis_client.set(
        ENCHANTING_CACHE_KEY,
        json.dumps({"rolls": [{"name": "Attack Bonus", "eligible": "ALL", "effects": "+1 ATT"}]}),
    )

    monkeypatch.setattr("api.dependencies._get_redis", lambda url: redis_client)
    called = {"n": 0}

    async def boom(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("must not re-scrape a full store")

    monkeypatch.setattr(
        "api.services.specialist_warm.warm_all_specialists", boom
    )
    await main._ensure_specialist_stores(anon_settings)
    assert called["n"] == 0


async def test_startup_warms_missing_dungeon_store(
    redis_client, anon_settings, monkeypatch
):
    monkeypatch.setattr("api.dependencies._get_redis", lambda url: redis_client)
    called = {}

    async def fake_warm(*args, **kwargs):
        called["force"] = kwargs.get("force")
        return {"dungeons": {"cached": 1}}

    monkeypatch.setattr(
        "api.services.specialist_warm.warm_all_specialists", fake_warm
    )
    tasks = []
    real_create = asyncio.create_task

    def capture(coro):
        task = real_create(coro)
        tasks.append(task)
        return task

    monkeypatch.setattr(main.asyncio, "create_task", capture)
    await main._ensure_specialist_stores(anon_settings)
    assert tasks
    await tasks[0]
    assert called["force"] is False


async def test_warm_all_continues_after_item_phase_fails(
    redis_client, monkeypatch
):
    from api.services import specialist_warm

    async def boom(*args, **kwargs):
        raise ConnectionError("Connection closed by server.")

    async def fake_umi(*args, **kwargs):
        return {"Wizard": 1}

    async def fake_dps(*args, **kwargs):
        return {"graph": 1, "loadouts": 0, "edges": 0}

    async def fake_dungeons(*args, **kwargs):
        return {"cached": 2, "total": 2, "index": 1}

    async def fake_sets(*args, **kwargs):
        return {"items": 3}

    monkeypatch.setattr(specialist_warm, "warm_item_profiles", boom)
    monkeypatch.setattr(specialist_warm, "warm_umi_bis", fake_umi)
    monkeypatch.setattr(specialist_warm, "warm_dps_boards", fake_dps)
    monkeypatch.setattr(specialist_warm, "warm_dungeon_guides", fake_dungeons)
    monkeypatch.setattr(specialist_warm, "warm_set_catalog", fake_sets)
    async def fake_snap(redis):
        return _full_snapshot() | {
            "items": {"cached": 0, "total": 10},
            "dungeons": {"cached": 0, "total": 2, "index": 0},
            "dps": {"graph": 0, "loadouts": 0, "edges": 1},
            "umi": [{"class_name": "Wizard", "stored": 0, "ttl_seconds": 0}],
        }

    monkeypatch.setattr(specialist_warm, "specialist_snapshot", fake_snap)

    result = await specialist_warm.warm_all_specialists(
        redis_client, ttl_seconds=60, force=False
    )
    assert "error" in result["items"]
    assert result["umi"] == {"Wizard": 1}
    assert result["dungeons"]["cached"] == 2
