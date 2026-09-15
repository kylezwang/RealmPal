import pytest

from api.models.item import ItemProfile
from api.routers import items as items_router
from .conftest import build_request
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
