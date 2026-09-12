"""
End-to-end magic-link redemption and checkout throttling through the real
/payments routes.

test_auth.py covers token shape in isolation; these exercise the two things
that only show up wired into Redis and FastAPI: a second redemption of the
same link is refused, and an unauthenticated caller can't flood Checkout
session creation.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import pytest

from api.auth import create_magic_token
from api.config import Settings, get_settings
from api.dependencies import get_redis
from api.main import create_app
from api.routers.payments import _apply_stripe_event
from api.services import entitlements

CALLER = ("198.51.100.7", 44321)


def _client(redis_client, settings) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_settings] = lambda: settings
    transport = httpx.ASGITransport(app=app, client=CALLER)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _magic_link(settings, email: str = "player@example.com") -> str:
    return create_magic_token(email, settings.effective_magic_link_secret)


# --- single-use magic links -----------------------------------------------


async def test_a_valid_magic_link_redeems_once(redis_client, anon_settings):
    token = _magic_link(anon_settings)
    async with _client(redis_client, anon_settings) as http:
        response = await http.get("/payments/verify", params={"token": token})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "player@example.com"
    assert body["token"]


async def test_redeeming_the_same_link_twice_is_refused(redis_client, anon_settings):
    token = _magic_link(anon_settings)
    async with _client(redis_client, anon_settings) as http:
        first = await http.get("/payments/verify", params={"token": token})
        second = await http.get("/payments/verify", params={"token": token})

    assert first.status_code == 200
    assert second.status_code == 400


async def test_a_redeemed_link_with_no_entitlement_is_not_paid(redis_client, anon_settings):
    """
    The fix that matters: /auth/request-link hands a magic link to anyone,
    so a successfully redeemed link must not imply `paid: true` on its own.
    """
    token = _magic_link(anon_settings)
    async with _client(redis_client, anon_settings) as http:
        response = await http.get("/payments/verify", params={"token": token})

    assert response.status_code == 200
    assert response.json()["paid"] is False


async def test_a_redeemed_link_for_an_active_entitlement_is_paid(redis_client, anon_settings):
    await entitlements.upsert("player@example.com", status="active", settings=anon_settings)
    token = _magic_link(anon_settings)
    async with _client(redis_client, anon_settings) as http:
        response = await http.get("/payments/verify", params={"token": token})

    assert response.status_code == 200
    assert response.json()["paid"] is True


async def test_two_different_links_each_redeem_once(redis_client, anon_settings):
    """Single-use is per-token (jti), not a blanket one-redemption-ever rule."""
    async with _client(redis_client, anon_settings) as http:
        first = await http.get(
            "/payments/verify", params={"token": _magic_link(anon_settings)}
        )
        second = await http.get(
            "/payments/verify", params={"token": _magic_link(anon_settings)}
        )

    assert first.status_code == 200
    assert second.status_code == 200


async def test_garbage_token_is_rejected_without_touching_redis_state(
    redis_client, anon_settings
):
    async with _client(redis_client, anon_settings) as http:
        response = await http.get(
            "/payments/verify", params={"token": "not-a-real-token"}
        )
    assert response.status_code == 400


async def test_a_session_secret_alone_cannot_forge_a_redeemable_link(
    redis_client, anon_settings
):
    """MAGIC_LINK_SECRET separation, exercised through the real endpoint."""
    from api.auth import create_magic_token as make

    settings = anon_settings.model_copy(
        update={"magic_link_secret": "a-separate-magic-secret"}
    )
    forged = make("attacker@example.com", settings.jwt_secret)  # session secret, not magic

    async with _client(redis_client, settings) as http:
        response = await http.get("/payments/verify", params={"token": forged})

    assert response.status_code == 400


# --- checkout throttling ---------------------------------------------------


async def test_checkout_is_rate_limited(redis_client, anon_settings):
    """
    Stripe isn't configured in tests, so every call 503s on that check - but
    the rate-limit dependency runs first, so once the burst budget is spent
    the response changes from 503 to 429 rather than silently letting an
    unauthenticated caller keep hammering Checkout-session creation.
    """
    async with _client(redis_client, anon_settings) as http:
        statuses = []
        for _ in range(anon_settings.lookup_rate_limit_anonymous + 1):
            response = await http.post(
                "/payments/checkout",
                json={"session_id": "s1", "email": "player@example.com"},
            )
            statuses.append(response.status_code)

    assert statuses[:-1] == [503] * anon_settings.lookup_rate_limit_anonymous
    assert statuses[-1] == 429


async def test_unconfigured_checkout_explains_what_to_set(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post(
            "/payments/checkout",
            json={"session_id": "s1", "email": "player@example.com"},
        )
    assert response.status_code == 503
    assert "STRIPE_SECRET_KEY" in response.json()["detail"]
    assert "STRIPE_PRICE_ID" in response.json()["detail"]


# --- Stripe webhook -> durable entitlement store --------------------------


@pytest.fixture
def entitlement_settings(anon_settings, tmp_path) -> Settings:
    return anon_settings.model_copy(
        update={
            "entitlements_db_path": str(tmp_path / "entitlements.db"),
            "stripe_webhook_secret": "whsec_test_secret",
        }
    )


def _stripe_event(event_type: str, data_object: dict) -> dict:
    return {"type": event_type, "data": {"object": data_object}}


def _signed_webhook_headers(payload: bytes, secret: str) -> dict:
    """Stripe's documented v1 signing scheme, so construct_event verifies it
    for real rather than the test stubbing verification away."""
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload.decode()}"
    signature = hmac.new(
        secret.encode(), signed_payload.encode(), hashlib.sha256
    ).hexdigest()
    return {"stripe-signature": f"t={timestamp},v1={signature}"}


async def test_checkout_completed_opens_an_active_entitlement(entitlement_settings):
    event = _stripe_event(
        "checkout.session.completed",
        {
            "customer_email": "player@example.com",
            "customer": "cus_123",
            "subscription": "sub_456",
        },
    )
    await _apply_stripe_event(event, entitlement_settings)
    assert await entitlements.is_active("player@example.com", entitlement_settings) is True


async def test_subscription_deleted_revokes_the_matching_customer(entitlement_settings):
    await entitlements.upsert(
        "player@example.com",
        status="active",
        settings=entitlement_settings,
        stripe_customer_id="cus_123",
    )
    event = _stripe_event(
        "customer.subscription.deleted", {"customer": "cus_123", "status": "canceled"}
    )
    await _apply_stripe_event(event, entitlement_settings)
    assert await entitlements.is_active("player@example.com", entitlement_settings) is False


async def test_subscription_updated_to_past_due_revokes_access(entitlement_settings):
    await entitlements.upsert(
        "player@example.com",
        status="active",
        settings=entitlement_settings,
        stripe_customer_id="cus_123",
    )
    event = _stripe_event(
        "customer.subscription.updated", {"customer": "cus_123", "status": "past_due"}
    )
    await _apply_stripe_event(event, entitlement_settings)
    assert await entitlements.is_active("player@example.com", entitlement_settings) is False


async def test_subscription_updated_to_trialing_stays_active(entitlement_settings):
    await entitlements.upsert(
        "player@example.com",
        status="active",
        settings=entitlement_settings,
        stripe_customer_id="cus_123",
    )
    event = _stripe_event(
        "customer.subscription.updated", {"customer": "cus_123", "status": "trialing"}
    )
    await _apply_stripe_event(event, entitlement_settings)
    assert await entitlements.is_active("player@example.com", entitlement_settings) is True


async def test_full_webhook_request_with_a_real_stripe_signature(
    redis_client, entitlement_settings
):
    """
    End-to-end through the actual endpoint, with a genuinely HMAC-signed
    payload | signature verification bugs are exactly the kind of thing a
    mocked-out `stripe.Webhook.construct_event` would hide.
    """
    payload = json.dumps(
        _stripe_event(
            "checkout.session.completed",
            {"customer_email": "player@example.com", "customer": "cus_999"},
        )
    ).encode()
    headers = _signed_webhook_headers(payload, entitlement_settings.stripe_webhook_secret)

    async with _client(redis_client, entitlement_settings) as http:
        response = await http.post(
            "/payments/webhook", content=payload, headers=headers
        )

    assert response.status_code == 200
    assert await entitlements.is_active("player@example.com", entitlement_settings) is True


async def test_confirm_opens_pro_for_the_signed_in_account(
    redis_client, entitlement_settings, monkeypatch
):
    from api.auth import create_jwt
    from api.services import accounts

    token = create_jwt(
        {"email": "player@example.com", "paid": False}, entitlement_settings
    )

    class _Session:
        def to_dict(self):
            return {
                "status": "complete",
                "payment_status": "paid",
                "customer_email": "player@example.com",
                "customer": "cus_confirm",
                "subscription": "sub_confirm",
                "metadata": {"email": "player@example.com"},
                "customer_details": {"email": "player@example.com"},
            }

    monkeypatch.setattr(
        "stripe.checkout.Session.retrieve", lambda _sid: _Session()
    )

    settings = entitlement_settings.model_copy(
        update={"stripe_secret_key": "sk_test_dummy", "stripe_price_id": "price_dummy"}
    )
    await accounts.create(
        "player@example.com", "long-enough", settings, ign="Turbine"
    )

    async with _client(redis_client, settings) as http:
        response = await http.post(
            "/payments/confirm",
            json={"session_id": "cs_test_123"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["paid"] is True
    assert response.json()["email"] == "player@example.com"
    assert await entitlements.is_active("player@example.com", settings) is True


async def test_confirm_rejects_a_session_for_another_email(
    redis_client, entitlement_settings, monkeypatch
):
    from api.auth import create_jwt

    token = create_jwt({"email": "player@example.com"}, entitlement_settings)

    class _Session:
        def to_dict(self):
            return {
                "status": "complete",
                "payment_status": "paid",
                "customer_email": "other@example.com",
                "metadata": {"email": "other@example.com"},
                "customer_details": {"email": "other@example.com"},
            }

    monkeypatch.setattr(
        "stripe.checkout.Session.retrieve", lambda _sid: _Session()
    )
    settings = entitlement_settings.model_copy(
        update={"stripe_secret_key": "sk_test_dummy"}
    )

    async with _client(redis_client, settings) as http:
        response = await http.post(
            "/payments/confirm",
            json={"session_id": "cs_test_other"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert await entitlements.is_active("player@example.com", settings) is False


async def test_webhook_with_a_bad_signature_is_rejected(redis_client, entitlement_settings):
    payload = json.dumps(
        _stripe_event(
            "checkout.session.completed", {"customer_email": "attacker@example.com"}
        )
    ).encode()
    headers = _signed_webhook_headers(payload, "wrong-secret")

    async with _client(redis_client, entitlement_settings) as http:
        response = await http.post(
            "/payments/webhook", content=payload, headers=headers
        )

    assert response.status_code == 400
    # A rejected signature must mean the handler never ran at all.
    assert await entitlements.get_status("attacker@example.com", entitlement_settings) is None
