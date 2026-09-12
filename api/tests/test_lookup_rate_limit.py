"""
Burst limiter for scrape-triggering lookups (players/items/dungeons/skins/
sprite), and the name sanitizer that runs ahead of it.

A cache miss on any of those endpoints launches a real headless browser
behind a single-Chromium semaphore in api/services/scraper.py. Before this,
none of them were rate limited at all: an anonymous caller could queue an
unbounded number of Playwright launches, which delays every other visitor's
lookup and burns real compute — a free denial-of-service the chat quota in
api/services/budget.py never covered.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.dependencies import enforce_lookup_rate_limit
from api.identity import AuthenticatedUser
from api.services.rate_limit import consume_windowed, lookup_quota_for
from api.services.validation import MAX_LOOKUP_NAME_LENGTH, sanitize_lookup_name

from .conftest import build_request

SIGNED_IN = AuthenticatedUser(subject="user-abc-123", email="player@example.com")


# --- bucket selection -------------------------------------------------


def test_anonymous_lookups_are_keyed_on_ip(anon_settings):
    quota = lookup_quota_for(None, build_request(peer="198.51.100.7"), anon_settings)
    assert quota.limit == anon_settings.lookup_rate_limit_anonymous
    assert quota.window_seconds == anon_settings.lookup_rate_window_seconds


def test_signed_in_lookups_get_a_higher_ceiling(anon_settings):
    anon_quota = lookup_quota_for(None, build_request(), anon_settings)
    user_quota = lookup_quota_for(SIGNED_IN, build_request(), anon_settings)
    assert user_quota.limit > anon_quota.limit


def test_lookup_bucket_is_separate_from_the_chat_quota_bucket(anon_settings):
    """Flooding /items shouldn't spend someone's chat allowance, or vice versa."""
    lookup = lookup_quota_for(None, build_request(peer="198.51.100.7"), anon_settings)
    from api.services.rate_limit import quota_for

    chat = quota_for(None, build_request(peer="198.51.100.7"), anon_settings)
    assert lookup.key != chat.key


def test_raw_ip_never_appears_in_the_lookup_key(anon_settings):
    ip = "198.51.100.7"
    quota = lookup_quota_for(None, build_request(peer=ip), anon_settings)
    assert ip not in quota.key


# --- counting -----------------------------------------------------------


async def test_consume_windowed_increments(redis_client, anon_settings):
    quota = lookup_quota_for(None, build_request(), anon_settings)
    assert await consume_windowed(redis_client, quota) == 1
    assert await consume_windowed(redis_client, quota) == 2


async def test_window_ttl_is_short_not_daily(redis_client, anon_settings):
    quota = lookup_quota_for(None, build_request(), anon_settings)
    await consume_windowed(redis_client, quota)
    ttl = await redis_client.ttl(quota.key)
    assert 0 < ttl <= anon_settings.lookup_rate_window_seconds


# --- the FastAPI dependency ---------------------------------------------


async def test_bursts_within_the_limit_pass(redis_client, anon_settings):
    request = build_request(peer="198.51.100.7")
    for _ in range(anon_settings.lookup_rate_limit_anonymous):
        await enforce_lookup_rate_limit(request, anon_settings, redis_client, None)


async def test_exceeding_the_limit_raises_429_with_retry_after(
    redis_client, anon_settings
):
    request = build_request(peer="198.51.100.7")
    for _ in range(anon_settings.lookup_rate_limit_anonymous):
        await enforce_lookup_rate_limit(request, anon_settings, redis_client, None)

    with pytest.raises(HTTPException) as exc_info:
        await enforce_lookup_rate_limit(request, anon_settings, redis_client, None)

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == str(
        anon_settings.lookup_rate_window_seconds
    )


async def test_different_callers_get_independent_buckets(redis_client, anon_settings):
    flooder = build_request(peer="198.51.100.7")
    victim = build_request(peer="198.51.100.8")

    for _ in range(anon_settings.lookup_rate_limit_anonymous):
        await enforce_lookup_rate_limit(flooder, anon_settings, redis_client, None)

    # The victim's own budget is untouched by the flooder's requests.
    await enforce_lookup_rate_limit(victim, anon_settings, redis_client, None)


async def test_redis_failure_fails_open(monkeypatch, redis_client, anon_settings):
    """An infra blip should degrade the feature, not take it down."""

    async def boom(*args, **kwargs):
        raise ConnectionError("redis is unreachable")

    monkeypatch.setattr(redis_client, "incr", boom)
    await enforce_lookup_rate_limit(
        build_request(), anon_settings, redis_client, None
    )


# --- name sanitization ---------------------------------------------------


def test_a_normal_name_passes_through_unchanged():
    assert sanitize_lookup_name("Angel's Fanfare", field="name") == "Angel's Fanfare"
    assert sanitize_lookup_name("  Kabam  ", field="username") == "Kabam"


def test_empty_name_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        sanitize_lookup_name("   ", field="name")
    assert exc_info.value.status_code == 400


def test_overlong_name_is_rejected():
    with pytest.raises(HTTPException):
        sanitize_lookup_name("a" * (MAX_LOOKUP_NAME_LENGTH + 1), field="name")


@pytest.mark.parametrize(
    "value",
    [
        "../../etc/passwd",
        "foo/../bar",
        "foo/bar",
        "foo\\bar",
        "evil\r\nSet-Cookie: pwned=1",
        "foo\x00bar",
        "foo\x7fbar",
    ],
)
def test_path_and_control_characters_are_rejected(value):
    with pytest.raises(HTTPException) as exc_info:
        sanitize_lookup_name(value, field="name")
    assert exc_info.value.status_code == 400


# --- CORS and default-secret checks (config.py properties) --------------


def test_cors_only_includes_the_configured_app_url_in_production():
    from api.config import Settings

    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key-not-real",
        jwt_secret="test-jwt-secret",
        pii_hash_secret="test-pii-secret",
        app_url="https://realmpal.example.com",
        debug=False,
    )
    assert settings.cors_allowed_origins == ["https://realmpal.example.com"]


def test_cors_adds_localhost_only_in_debug():
    from api.config import Settings

    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key-not-real",
        jwt_secret="test-jwt-secret",
        pii_hash_secret="test-pii-secret",
        app_url="https://realmpal.example.com",
        debug=True,
    )
    assert "http://localhost:3000" in settings.cors_allowed_origins
    assert "https://realmpal.example.com" in settings.cors_allowed_origins


def test_default_jwt_secret_is_detected(anon_settings):
    from api.config import Settings

    default = Settings(_env_file=None, anthropic_api_key="x", pii_hash_secret="p")
    rotated = Settings(
        _env_file=None, anthropic_api_key="x", jwt_secret="a-real-secret", pii_hash_secret="p"
    )
    assert default.uses_default_jwt_secret is True
    assert rotated.uses_default_jwt_secret is False
    assert anon_settings.uses_default_jwt_secret is False
