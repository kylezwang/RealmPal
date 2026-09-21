import json

import pytest
from fastapi import HTTPException

from api.models.item import ItemProfile
from api.routers import items as items_router
from .conftest import build_request
from api.services.item_aliases import CATALOG_PREFIX
from api.services.scraper import ScraperError, _item_wiki_slug
from api.services.wiki_scaling import (
    ITEM_CACHE_PREFIX,
    is_item_marked_missing,
    item_name_keys,
    mark_item_missing,
    read_cached_item,
    write_cached_item,
)


def test_ascii_and_curly_apostrophes_become_realmeye_slugs():
    assert _item_wiki_slug("Angel's Fanfare") == "angel-s-fanfare"
    assert _item_wiki_slug("Angel’s Fanfare") == "angel-s-fanfare"
    assert _item_wiki_slug("Piper’s Pan Flute") == "piper-s-pan-flute"
    assert _item_wiki_slug("St. Abraham’s Wand") == "st-abraham-s-wand"


def test_item_name_keys_cover_both_apostrophes():
    keys = item_name_keys("Tlatoani's Shroud")
    assert "tlatoani's shroud" in keys
    assert "tlatoani’s shroud" in keys


async def test_warmed_v3_profile_is_readable_by_item_cards(redis_client):
    item = ItemProfile(
        name="Flowering Kimono",
        sprite_url="https://www.realmeye.com/s/a/img/wiki/kimono.png",
    )
    await write_cached_item(redis_client, item, 60)
    raw = await redis_client.get(f"{ITEM_CACHE_PREFIX}:flowering kimono")
    assert raw
    hit = await read_cached_item(redis_client, "Flowering Kimono")
    assert hit is not None
    assert hit.sprite_url == item.sprite_url


async def test_curly_apostrophe_warm_hits_ascii_lookup(redis_client):
    item = ItemProfile(
        name="Tlatoani’s Shroud",
        sprite_url="https://www.realmeye.com/s/a/img/wiki/shroud.png",
    )
    await write_cached_item(redis_client, item, 60)
    hit = await read_cached_item(redis_client, "Tlatoani's Shroud")
    assert hit is not None
    assert hit.sprite_url == item.sprite_url


async def test_item_endpoint_uses_warm_store_not_live_scrape(
    redis_client, anon_settings, monkeypatch
):
    item = ItemProfile(
        name="Command Cornea",
        sprite_url="https://www.realmeye.com/s/a/img/wiki/cornea.png",
    )
    await write_cached_item(redis_client, item, 60)

    async def boom(*args, **kwargs):
        raise AssertionError("item cards must read the warmed profile")

    monkeypatch.setattr(items_router, "scrape_item", boom)
    monkeypatch.setattr(items_router, "resolve_item_query", boom)

    found = await items_router.get_item(
        "Command Cornea",
        anon_settings,
        redis_client,
        object(),
        build_request(),
    )
    assert found.sprite_url == item.sprite_url


async def _no_alias(*args, **kwargs):
    return None


async def test_scrape_failure_marks_the_item_missing(redis_client, anon_settings, monkeypatch):
    """Regression: found live Sep 14 - Rift Rippers is a real item (a fresh
    RealmShark leaderboard entry) with no RealmEye wiki page yet, and every
    lookup for it re-paid a full two-attempt Playwright timeout (~30s)
    because a scrape failure was never remembered. A failed scrape must mark
    the name missing so the next lookup fails fast instead of re-scraping."""

    async def always_fails(*args, **kwargs):
        raise ScraperError("Page.wait_for_selector: Timeout 15000ms exceeded.")

    monkeypatch.setattr(items_router, "scrape_item", always_fails)
    monkeypatch.setattr(items_router, "resolve_item_query", _no_alias)

    with pytest.raises(Exception):
        await items_router.get_item(
            "Rift Rippers",
            anon_settings,
            redis_client,
            object(),
            build_request(),
        )
    assert await is_item_marked_missing(redis_client, "Rift Rippers")


async def test_item_marked_missing_fails_fast_without_scraping_again(
    redis_client, anon_settings, monkeypatch
):
    await mark_item_missing(redis_client, "Rift Rippers", anon_settings.missing_item_ttl_seconds)

    async def boom(*args, **kwargs):
        raise AssertionError("a known-missing item must not be re-scraped")

    monkeypatch.setattr(items_router, "scrape_item", boom)
    monkeypatch.setattr(items_router, "resolve_item_query", _no_alias)

    with pytest.raises(Exception):
        await items_router.get_item(
            "Rift Rippers",
            anon_settings,
            redis_client,
            object(),
            build_request(),
        )


async def test_glued_free_text_resolves_via_catalog_trim_instead_of_scraping_garbage(
    redis_client, anon_settings, monkeypatch
):
    """Durable fix, found live Sep 14 (repeatedly): a caller (a chat reply's
    item extraction) can hand this endpoint free text with a real item name
    glued to unrelated trailing words ("snake eye ring is the awakened
    enchantment good"). resolve_item_query alone requires the whole string
    to match and fails, but resolve_item_query_with_trim should find "Snake
    Eye Ring" inside it - the endpoint must use the resolved, cached title
    and never call scrape_item with the raw glued string."""
    payload = [{"name": "Snake Eye Ring", "slot": "ring", "aliases": []}]
    await redis_client.set(f"{CATALOG_PREFIX}:all:cached", json.dumps(payload))
    item = ItemProfile(name="Snake Eye Ring", drop_locations=["Wine Cellar"])
    await write_cached_item(redis_client, item, anon_settings.wiki_ttl_seconds)

    async def boom(*args, **kwargs):
        raise AssertionError("must resolve via the catalog, not scrape raw glued text")

    monkeypatch.setattr(items_router, "scrape_item", boom)

    found = await items_router.get_item(
        "snake eye ring is the awakened enchantment good",
        anon_settings,
        redis_client,
        object(),
        build_request(),
    )
    assert found.name == "Snake Eye Ring"


async def test_get_item_attaches_awakened_from_wiki_infobox(
    redis_client, anon_settings, monkeypatch
):
    """Loadout hover needs Draconic Gaze even when the enchanting table
    does not name Snake Eye Ring."""
    item = ItemProfile(
        name="Snake Eye Ring",
        stats={
            "On Equip": "+50 HP, +5 ATT, +5 DEF, +5 SPD",
            "Awakened Enchantment": (
                "Draconic Gaze. +50 MP. On ability use, gain Damaging "
                "for 2 seconds, 5 second cooldown."
            ),
        },
    )
    await write_cached_item(redis_client, item, 60)

    async def boom(*args, **kwargs):
        raise AssertionError("must read the warmed profile")

    monkeypatch.setattr(items_router, "scrape_item", boom)
    monkeypatch.setattr(items_router, "resolve_item_query", boom)

    found = await items_router.get_item(
        "Snake Eye Ring",
        anon_settings,
        redis_client,
        object(),
        build_request(),
    )
    assert found.awakened_enchant
    assert "Draconic Gaze" in found.awakened_enchant


SNAKE_EYE_AWAKENED_HTML = """
<table class="infobox">
<tr><th>On Equip</th><td>+50 HP, +5 ATT, +5 DEF, +5 SPD</td></tr>
</table>
<table>
<tr>
<th>Awakened Enchantment</th>
<td><img src="/s/a/img/wiki/gaze.png" alt="" /></td>
<td>Draconic Gaze. +50 MP. On ability use, gain Damaging for 2 seconds, 5 second cooldown.</td>
</tr>
</table>
"""


def test_parse_awakened_from_wiki_html_snake_eye():
    """Found live Sep 21: RealmEye keeps Awakened Enchantment in a table
    after the infobox (sprite td + effects td), so On Equip hover never
    attached Draconic Gaze."""
    from api.services.scraper import parse_awakened_from_wiki_html

    line = parse_awakened_from_wiki_html(SNAKE_EYE_AWAKENED_HTML)
    assert line
    assert "Draconic Gaze" in line
    assert "+50 MP" in line


def test_item_page_js_copies_awakened_table():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "services" / "scraper.py").read_text(
        encoding="utf-8"
    )
    assert "isAwakened" in source
    assert "Awakened Enchantment" in source


async def test_get_item_backfills_awakened_from_wiki_table(
    redis_client, anon_settings, monkeypatch
):
    """Cached Snake Eye had On Equip but no awakened row. GET /items should
    HTTP the wiki table and persist Draconic Gaze without a Playwright scrape."""
    item = ItemProfile(
        name="Snake Eye Ring",
        stats={"On Equip": "+50 HP, +5 ATT, +5 DEF, +5 SPD"},
    )
    await write_cached_item(redis_client, item, 60)

    async def boom(*args, **kwargs):
        raise AssertionError("must read the warmed profile")

    async def fake_awakened(name: str):
        assert "Snake Eye" in name
        return (
            "Draconic Gaze. +50 MP. On ability use, gain Damaging "
            "for 2 seconds, 5 second cooldown."
        )

    monkeypatch.setattr(items_router, "scrape_item", boom)
    monkeypatch.setattr(items_router, "resolve_item_query", boom)
    monkeypatch.setattr(items_router, "fetch_wiki_awakened_line", fake_awakened)

    found = await items_router.get_item(
        "Snake Eye Ring",
        anon_settings,
        redis_client,
        object(),
        build_request(),
    )
    assert found.awakened_enchant
    assert "Draconic Gaze" in found.awakened_enchant
    cached = await read_cached_item(redis_client, "Snake Eye Ring")
    assert cached is not None
    assert "Draconic Gaze" in (cached.stats or {}).get("Awakened Enchantment", "")


async def test_implausibly_long_name_is_rejected_without_a_scrape_attempt(
    redis_client, anon_settings, monkeypatch
):
    """When nothing in the catalog matches any prefix and the name is far
    longer than any real item name could be, reject immediately (404, no
    quota charge, no scrape) instead of paying a ~30s timeout for a wiki
    page that could never have existed."""

    async def boom(*args, **kwargs):
        raise AssertionError("must not attempt to scrape obvious extraction garbage")

    monkeypatch.setattr(items_router, "scrape_item", boom)
    monkeypatch.setattr(items_router, "resolve_item_query", _no_alias)

    with pytest.raises(HTTPException) as exc_info:
        await items_router.get_item(
            "completely unrelated nonsense text that names nothing real at all",
            anon_settings,
            redis_client,
            object(),
            build_request(),
        )
    assert exc_info.value.status_code == 404
