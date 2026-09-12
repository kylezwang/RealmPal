"""
The chat path's legacy-paid-token check against the durable entitlement
store, in isolation from the network-calling parts of /chat/stream.

Before this, `_has_legacy_paid_token` only checked a JWT's signature and
expiry; a cancelled or refunded subscription kept bypassing the free quota
until that token expired. It now also asks api/services/entitlements.py.
"""
from __future__ import annotations

import pytest

from api.auth import create_jwt
from api.config import Settings
from api.routers.chat import _has_legacy_paid_token
from api.services import entitlements


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        anthropic_api_key="test-key-not-real",
        jwt_secret="test-jwt-secret",
        pii_hash_secret="test-pii-secret",
        entitlements_db_path=str(tmp_path / "entitlements.db"),
    )


def _paid_token(settings: Settings, email: str = "player@example.com") -> str:
    return create_jwt({"email": email, "paid": True}, settings)


async def test_no_bearer_token_is_not_paid(settings):
    assert await _has_legacy_paid_token(None, settings) is False


async def test_a_non_paid_token_is_not_paid(settings):
    token = create_jwt({"email": "player@example.com"}, settings)
    assert await _has_legacy_paid_token(f"Bearer {token}", settings) is False


async def test_an_unpaid_token_with_an_active_entitlement_is_paid(settings):
    """Returning from Stripe leaves the old free JWT in the browser until
    /payments/confirm remints it. Chat must still see the new entitlement."""
    await entitlements.upsert("player@example.com", status="active", settings=settings)
    token = create_jwt({"email": "player@example.com", "paid": False}, settings)
    assert await _has_legacy_paid_token(f"Bearer {token}", settings) is True


async def test_an_unverifiable_token_is_not_paid(settings):
    assert await _has_legacy_paid_token("Bearer not.a.real.token", settings) is False


async def test_paid_token_with_no_entitlement_row_is_rejected(settings):
    """
    Fail-closed: since /auth/request-link hands a magic link to anyone,
    a `paid: true` claim with no backing row must not be trusted - that
    would give every free sign-in the paid tier.
    """
    token = _paid_token(settings)
    assert await _has_legacy_paid_token(f"Bearer {token}", settings) is False


async def test_paid_token_with_an_active_row_passes(settings):
    await entitlements.upsert("player@example.com", status="active", settings=settings)
    token = _paid_token(settings)
    assert await _has_legacy_paid_token(f"Bearer {token}", settings) is True


async def test_paid_token_with_a_canceled_row_is_rejected(settings):
    """The actual fix: a validly signed, unexpired token no longer bypasses
    the free quota once Stripe has told us the subscription ended."""
    await entitlements.upsert("player@example.com", status="active", settings=settings)
    await entitlements.upsert("player@example.com", status="canceled", settings=settings)
    token = _paid_token(settings)
    assert await _has_legacy_paid_token(f"Bearer {token}", settings) is False


async def test_revocation_is_scoped_to_the_email_on_the_token(settings):
    """Cancelling one email's subscription must not affect another's."""
    await entitlements.upsert("player@example.com", status="active", settings=settings)
    await entitlements.upsert("other@example.com", status="canceled", settings=settings)
    token = _paid_token(settings, email="player@example.com")
    assert await _has_legacy_paid_token(f"Bearer {token}", settings) is True
