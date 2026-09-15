"""
Quota keying and enforcement.

The bug these guard against: the free tier used to be keyed on a UUID the
browser generated, so clearing localStorage reset the allowance. A quota is
only worth anything if the caller can't pick which bucket they land in.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from api.identity import AuthenticatedUser
from api.services.rate_limit import (
    ANONYMOUS_SCOPE,
    QUOTA_TTL_SECONDS,
    USER_SCOPE,
    client_ip,
    consume,
    peek,
    quota_for,
    seconds_until_daily_reset,
)

from .conftest import build_request

SIGNED_IN = AuthenticatedUser(subject="user-abc-123", email="player@example.com")


# --- how the bucket is chosen ---------------------------------------------


def test_anonymous_callers_are_keyed_on_ip(anon_settings):
    quota = quota_for(None, build_request(peer="198.51.100.7"), anon_settings)
    assert quota.scope == ANONYMOUS_SCOPE
    assert quota.limit == anon_settings.anonymous_message_limit


def test_raw_ip_never_appears_in_the_redis_key(anon_settings):
    """Quota keys shouldn't double as a visitor log."""
    ip = "198.51.100.7"
    quota = quota_for(None, build_request(peer=ip), anon_settings)
    assert ip not in quota.key
    assert ip not in quota.label


def test_same_ip_shares_one_bucket(anon_settings):
    first = quota_for(None, build_request(peer="198.51.100.7"), anon_settings)
    second = quota_for(None, build_request(peer="198.51.100.7"), anon_settings)
    assert first.key == second.key


def test_different_ips_get_separate_buckets(anon_settings):
    first = quota_for(None, build_request(peer="198.51.100.7"), anon_settings)
    second = quota_for(None, build_request(peer="198.51.100.8"), anon_settings)
    assert first.key != second.key


def test_signed_in_callers_are_keyed_on_the_verified_subject(anon_settings):
    quota = quota_for(SIGNED_IN, build_request(), anon_settings)
    assert quota.scope == USER_SCOPE
    assert SIGNED_IN.subject in quota.key
    assert quota.limit == anon_settings.free_message_limit


def test_signing_in_raises_the_ceiling(anon_settings):
    """Otherwise there's no incentive to sign in rather than churn IPs."""
    anonymous = quota_for(None, build_request(), anon_settings)
    signed_in = quota_for(SIGNED_IN, build_request(), anon_settings)
    assert signed_in.limit > anonymous.limit


def test_identity_beats_the_caller_address(anon_settings):
    """One account moving between networks keeps one quota."""
    home = quota_for(SIGNED_IN, build_request(peer="198.51.100.7"), anon_settings)
    cafe = quota_for(SIGNED_IN, build_request(peer="203.0.113.99"), anon_settings)
    assert home.key == cafe.key


# --- X-Forwarded-For spoofing ---------------------------------------------


def test_forwarded_header_is_ignored_by_default(anon_settings):
    """
    Trusting X-Forwarded-For unconditionally would restore the very bypass
    this design removes: anyone could mint a fresh quota per request.
    """
    assert anon_settings.trust_forwarded_for is False
    spoofed = build_request(
        peer="198.51.100.7", headers={"x-forwarded-for": "1.2.3.4"}
    )
    honest = build_request(peer="198.51.100.7")
    assert client_ip(spoofed, anon_settings) == "198.51.100.7"
    assert quota_for(None, spoofed, anon_settings).key == quota_for(
        None, honest, anon_settings
    ).key


def test_spoofing_the_header_cannot_rotate_buckets(anon_settings):
    keys = {
        quota_for(
            None,
            build_request(peer="198.51.100.7", headers={"x-forwarded-for": f"10.0.0.{i}"}),
            anon_settings,
        ).key
        for i in range(10)
    }
    assert len(keys) == 1


def test_forwarded_header_is_used_behind_a_trusted_proxy(anon_settings):
    behind_proxy = anon_settings.model_copy(
        update={"trust_forwarded_for": True, "forwarded_proxy_hops": 1}
    )
    request = build_request(
        peer="10.0.0.1", headers={"x-forwarded-for": "198.51.100.7"}
    )
    assert client_ip(request, behind_proxy) == "198.51.100.7"


def test_caller_prepended_entries_are_discarded(anon_settings):
    """
    With one proxy in front, only the right-most entry was written by
    infrastructure we control. Anything to its left came from the caller.
    """
    behind_proxy = anon_settings.model_copy(
        update={"trust_forwarded_for": True, "forwarded_proxy_hops": 1}
    )
    request = build_request(
        peer="10.0.0.1",
        headers={"x-forwarded-for": "1.2.3.4, 5.6.7.8, 198.51.100.7"},
    )
    assert client_ip(request, behind_proxy) == "198.51.100.7"


def test_two_hops_reads_past_the_inner_proxy(anon_settings):
    behind_two = anon_settings.model_copy(
        update={"trust_forwarded_for": True, "forwarded_proxy_hops": 2}
    )
    request = build_request(
        peer="10.0.0.1",
        headers={"x-forwarded-for": "198.51.100.7, 10.0.0.2"},
    )
    assert client_ip(request, behind_two) == "198.51.100.7"


def test_short_forwarded_chain_falls_back_to_the_socket_peer(anon_settings):
    """A chain shorter than configured means the request skipped a proxy."""
    behind_two = anon_settings.model_copy(
        update={"trust_forwarded_for": True, "forwarded_proxy_hops": 2}
    )
    request = build_request(peer="10.0.0.1", headers={"x-forwarded-for": "1.2.3.4"})
    assert client_ip(request, behind_two) == "10.0.0.1"


def test_missing_peer_does_not_crash(anon_settings):
    quota = quota_for(None, build_request(peer=None), anon_settings)
    assert quota.key
    assert quota.scope == ANONYMOUS_SCOPE


# --- counting -------------------------------------------------------------


async def test_consume_increments_and_peek_does_not(redis_client, anon_settings):
    quota = quota_for(None, build_request(), anon_settings)
    assert await peek(redis_client, quota) == 0

    assert await consume(redis_client, quota) == 1
    assert await consume(redis_client, quota) == 2
    assert await peek(redis_client, quota) == 2
    assert await peek(redis_client, quota) == 2


async def test_first_consume_sets_the_window_ttl(redis_client, anon_settings):
    quota = quota_for(None, build_request(), anon_settings)
    await consume(redis_client, quota)
    ttl = await redis_client.ttl(quota.key)
    assert 0 < ttl <= QUOTA_TTL_SECONDS


async def test_ttl_is_not_extended_by_later_requests(redis_client, anon_settings):
    """Otherwise steady traffic would hold the window open indefinitely."""
    quota = quota_for(None, build_request(), anon_settings)
    await consume(redis_client, quota)
    await redis_client.expire(quota.key, 60)
    await consume(redis_client, quota)
    assert await redis_client.ttl(quota.key) <= 60


async def test_buckets_are_independent(redis_client, anon_settings):
    first = quota_for(None, build_request(peer="198.51.100.7"), anon_settings)
    second = quota_for(None, build_request(peer="198.51.100.8"), anon_settings)

    await consume(redis_client, first)
    await consume(redis_client, first)

    assert await peek(redis_client, first) == 2
    assert await peek(redis_client, second) == 0


@pytest.mark.parametrize("junk", ["not-a-number", "", "NaN"])
async def test_corrupt_counter_reads_as_zero(redis_client, anon_settings, junk):
    quota = quota_for(None, build_request(), anon_settings)
    await redis_client.set(quota.key, junk)
    assert await peek(redis_client, quota) == 0


# --- shared daily reset time -----------------------------------------------


def test_seconds_until_daily_reset_counts_down_to_5pm_pacific_same_day():
    """Regression: quotas used to reset 24h after each caller's own first
    message, so "when do I get more" depended on when you happened to first
    message - reported live Sep 14. Everyone now shares one reset instant."""
    pacific = ZoneInfo("America/Los_Angeles")
    noon = datetime(2026, 9, 14, 12, 0, tzinfo=pacific)
    assert seconds_until_daily_reset(noon) == 5 * 3600


def test_seconds_until_daily_reset_rolls_to_tomorrow_once_past_5pm():
    pacific = ZoneInfo("America/Los_Angeles")
    just_after = datetime(2026, 9, 14, 17, 0, 1, tzinfo=pacific)
    # 23h59m59s until tomorrow's 5pm.
    assert seconds_until_daily_reset(just_after) == 23 * 3600 + 59 * 60 + 59


def test_seconds_until_daily_reset_exactly_at_5pm_rolls_to_tomorrow():
    pacific = ZoneInfo("America/Los_Angeles")
    exactly = datetime(2026, 9, 14, 17, 0, 0, tzinfo=pacific)
    assert seconds_until_daily_reset(exactly) == 24 * 3600


def test_seconds_until_daily_reset_is_timezone_independent_input():
    """A UTC instant and its Pacific equivalent must agree."""
    pacific = ZoneInfo("America/Los_Angeles")
    in_pacific = datetime(2026, 9, 14, 9, 0, tzinfo=pacific)
    in_utc = in_pacific.astimezone(ZoneInfo("UTC"))
    assert seconds_until_daily_reset(in_pacific) == seconds_until_daily_reset(in_utc)


async def test_anonymous_allowance_is_exhausted_at_the_limit(
    redis_client, anon_settings
):
    quota = quota_for(None, build_request(), anon_settings)
    counts = [await consume(redis_client, quota) for _ in range(quota.limit)]
    assert counts == list(range(1, quota.limit + 1))
    # The next request is the one that should be refused.
    assert await consume(redis_client, quota) == quota.limit + 1
