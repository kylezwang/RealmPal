"""
Durable entitlement store.

The bug this replaces: a Stripe payment minted a JWT with `paid: true`, and
nothing about the subscription was ever checked again for that token's
whole lifetime. These cover the store in isolation; test_payments.py and
test_chat_quota.py cover it wired into the webhook and the chat path.
"""
from __future__ import annotations

import pytest

from api.config import Settings
from api.services import entitlements


@pytest.fixture
def db_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        anthropic_api_key="test-key-not-real",
        jwt_secret="test-jwt-secret",
        pii_hash_secret="test-pii-secret",
        entitlements_db_path=str(tmp_path / "entitlements.db"),
    )


async def test_an_email_never_seen_before_is_not_active(db_settings):
    """
    Fail-closed: /auth/request-link hands a magic link to anyone, so an
    unknown email is an ordinary free sign-in, not a rare pre-existing
    customer this store hasn't heard about yet.
    """
    assert await entitlements.is_active("nobody@example.com", db_settings) is False


async def test_upserting_active_status_is_read_back(db_settings):
    await entitlements.upsert("player@example.com", status="active", settings=db_settings)
    assert await entitlements.is_active("player@example.com", db_settings) is True


async def test_a_canceled_row_revokes_access(db_settings):
    await entitlements.upsert("player@example.com", status="active", settings=db_settings)
    await entitlements.upsert("player@example.com", status="canceled", settings=db_settings)
    assert await entitlements.is_active("player@example.com", db_settings) is False


async def test_lookup_is_case_and_whitespace_insensitive(db_settings):
    await entitlements.upsert("  Player@Example.com  ", status="canceled", settings=db_settings)
    assert await entitlements.is_active("player@example.com", db_settings) is False


async def test_set_status_by_customer_updates_the_matching_row(db_settings):
    await entitlements.upsert(
        "player@example.com",
        status="active",
        settings=db_settings,
        stripe_customer_id="cus_123",
    )
    affected = await entitlements.set_status_by_customer("cus_123", "canceled", db_settings)
    assert affected == "player@example.com"
    assert await entitlements.is_active("player@example.com", db_settings) is False


async def test_set_status_by_customer_on_an_unknown_customer_is_a_noop(db_settings):
    affected = await entitlements.set_status_by_customer("cus_unknown", "canceled", db_settings)
    assert affected is None


async def test_upsert_preserves_customer_id_across_status_only_updates(db_settings):
    """A subscription.updated event may not repeat the customer/sub IDs."""
    await entitlements.upsert(
        "player@example.com",
        status="active",
        settings=db_settings,
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_456",
    )
    await entitlements.upsert("player@example.com", status="past_due", settings=db_settings)

    affected = await entitlements.set_status_by_customer("cus_123", "canceled", db_settings)
    assert affected == "player@example.com"


async def test_get_status_is_none_for_an_unknown_email(db_settings):
    assert await entitlements.get_status("nobody@example.com", db_settings) is None


async def test_get_status_returns_the_raw_stored_value(db_settings):
    await entitlements.upsert("player@example.com", status="past_due", settings=db_settings)
    assert await entitlements.get_status("player@example.com", db_settings) == "past_due"


async def test_empty_email_is_ignored(db_settings):
    await entitlements.upsert("   ", status="active", settings=db_settings)
    assert await entitlements.is_active("   ", db_settings) is False
