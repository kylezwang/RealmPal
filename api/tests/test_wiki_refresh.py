"""Wiki corpus is scheduled; player lookups scrape on request."""
from __future__ import annotations

from api.config import Settings
from api.services import player_lookup, realmshark, wiki_refresh
from api.models.player import PlayerProfile


def test_wiki_ttl_is_weekly_and_players_are_short(anon_settings: Settings):
    assert anon_settings.wiki_ttl_seconds == 168 * 3600
    assert anon_settings.player_ttl_seconds == 120
    assert anon_settings.wiki_ttl_seconds > anon_settings.player_ttl_seconds


async def test_wiki_refresh_is_due_until_stamped(redis_client, anon_settings):
    assert await wiki_refresh.wiki_refresh_due(redis_client, anon_settings) is True

    async def fake_seed(client, slugs=None):
        return {"daggers": 1}

    async def fake_warm(redis, ttl_seconds, classes=None, **kwargs):
        return {"Huntress": 12}

    original = wiki_refresh.seed_wiki_hubs
    original_warm = wiki_refresh.warm_all_specialists
    wiki_refresh.seed_wiki_hubs = fake_seed
    wiki_refresh.warm_all_specialists = fake_warm
    try:
        result = await wiki_refresh.refresh_wiki_corpus(
            object(), redis_client, anon_settings
        )
    finally:
        wiki_refresh.seed_wiki_hubs = original
        wiki_refresh.warm_all_specialists = original_warm

    assert result["hubs"] == {"daggers": 1}
    assert result["specialists"] == {"Huntress": 12}
    assert await wiki_refresh.wiki_refresh_due(redis_client, anon_settings) is False


async def test_player_cache_is_skipped_when_ttl_is_zero(
    redis_client, monkeypatch
):
    calls = {"n": 0}

    async def fake_scrape(username: str) -> PlayerProfile:
        calls["n"] += 1
        return PlayerProfile(username=username)

    monkeypatch.setattr(player_lookup, "scrape_player_profile", fake_scrape)

    first = await player_lookup.get_or_scrape_player(
        redis_client, "Turbine", ttl_seconds=0
    )
    second = await player_lookup.get_or_scrape_player(
        redis_client, "Turbine", ttl_seconds=0
    )
    assert first.username == "Turbine"
    assert second.username == "Turbine"
    assert calls["n"] == 2


async def test_player_cache_collapses_duplicate_hits(
    redis_client, monkeypatch
):
    calls = {"n": 0}

    async def fake_scrape(username: str) -> PlayerProfile:
        calls["n"] += 1
        return PlayerProfile(username=username)

    monkeypatch.setattr(player_lookup, "scrape_player_profile", fake_scrape)

    await player_lookup.get_or_scrape_player(
        redis_client, "Turbine", ttl_seconds=120
    )
    await player_lookup.get_or_scrape_player(
        redis_client, "Turbine", ttl_seconds=120
    )
    assert calls["n"] == 1


async def test_player_cache_cannot_inherit_weekly_wiki_ttl(
    redis_client, monkeypatch
):
    async def fake_scrape(username: str) -> PlayerProfile:
        return PlayerProfile(username=username)

    monkeypatch.setattr(player_lookup, "scrape_player_profile", fake_scrape)

    await player_lookup.get_or_scrape_player(
        redis_client, "Turbine", ttl_seconds=168 * 3600
    )
    ttl = await redis_client.ttl(f"{player_lookup.PLAYER_CACHE_PREFIX}turbine")
    assert 0 < ttl <= player_lookup.MAX_PLAYER_CACHE_SECONDS


async def test_wiki_refresh_never_scrapes_players(
    redis_client, anon_settings, monkeypatch
):
    scrapes = {"n": 0}

    async def fake_scrape(username: str) -> PlayerProfile:
        scrapes["n"] += 1
        return PlayerProfile(username=username)

    async def fake_seed(client, slugs=None):
        return {"daggers": 1}

    async def fake_warm(redis, ttl_seconds, classes=None, **kwargs):
        return {"Huntress": 12}

    monkeypatch.setattr(player_lookup, "scrape_player_profile", fake_scrape)
    monkeypatch.setattr(wiki_refresh, "seed_wiki_hubs", fake_seed)
    monkeypatch.setattr(wiki_refresh, "warm_all_specialists", fake_warm)

    await wiki_refresh.refresh_wiki_corpus(
        object(), redis_client, anon_settings
    )
    assert scrapes["n"] == 0


async def test_player_lookup_skips_wiki_and_uses_short_ttl(
    redis_client, monkeypatch
):
    seen = {}

    async def boom(*args, **kwargs):
        raise AssertionError("player lookup must not load wiki or DPS stores")

    async def fake_slots(*args, **kwargs):
        seen["player_ttl"] = kwargs.get("player_ttl_seconds")
        seen["class_name"] = kwargs.get("class_name")
        seen["player_ign"] = kwargs.get("player_ign")
        return "PLAYER AGENT — Turbine"

    monkeypatch.setattr(realmshark, "load_graph", boom)
    monkeypatch.setattr(realmshark, "cached_class_wiki_scaling", boom)
    monkeypatch.setattr(realmshark, "run_slot_agents", fake_slots)

    text = await realmshark.retrieve_build_knowledge(
        redis_client,
        "look up player Turbine",
        ttl_seconds=168 * 3600,
        player_ttl_seconds=120,
        history=["Best attack Bard"],
    )
    assert "Turbine" in text
    assert seen["player_ttl"] == 120
    assert seen["class_name"] is None
    assert seen["player_ign"] == "Turbine"
