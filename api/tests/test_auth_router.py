"""
POST /auth/request-link | passwordless sign-in, independent of payment.

This is the endpoint that makes fail-closed entitlements (see
test_entitlements.py) necessary in the first place: before it existed, the
only way to get a magic link was a completed Stripe checkout, so every
redeemed link implied payment. Now anyone can request one for any address.
"""
from __future__ import annotations

import httpx
import pytest

from api.config import get_settings
from api.dependencies import get_redis
from api.main import create_app

CALLER = ("198.51.100.7", 44321)


def _client(redis_client, settings) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_settings] = lambda: settings
    transport = httpx.ASGITransport(app=app, client=CALLER)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_a_well_formed_email_is_accepted(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post(
            "/auth/request-link", json={"email": "player@example.com"}
        )
    assert response.status_code == 200
    assert response.json() == {"sent": True}


@pytest.mark.parametrize(
    "email",
    [
        "not-an-email",
        "",
        "@example.com",
        "player@",
        "player@example",
        "player@example.com\r\nBcc: attacker@evil.com",
    ],
)
async def test_malformed_email_is_rejected(redis_client, anon_settings, email):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post("/auth/request-link", json={"email": email})
    assert response.status_code == 400


async def test_request_link_is_rate_limited(redis_client, anon_settings):
    """
    Same shared lookup limiter as players/items/checkout: this sends an
    email (eventually, once a provider is wired), so it must not be free
    to hammer.
    """
    async with _client(redis_client, anon_settings) as http:
        statuses = []
        for _ in range(anon_settings.lookup_rate_limit_anonymous + 1):
            response = await http.post(
                "/auth/request-link", json={"email": "player@example.com"}
            )
            statuses.append(response.status_code)

    assert statuses[:-1] == [200] * anon_settings.lookup_rate_limit_anonymous
    assert statuses[-1] == 429


async def test_response_does_not_reveal_whether_anything_was_sent(
    redis_client, anon_settings
):
    """No email-provider integration yet, but the contract must not change
    once one lands: never distinguish "we sent it" from "this looked odd
    but we sent it anyway" for a well-formed address."""
    async with _client(redis_client, anon_settings) as http:
        first = await http.post(
            "/auth/request-link", json={"email": "definitely-new@example.com"}
        )
        second = await http.post(
            "/auth/request-link", json={"email": "definitely-new@example.com"}
        )
    assert first.json() == second.json() == {"sent": True}


# --- email + password ------------------------------------------------------


def _register_body(
    email: str = "player@example.com",
    password: str = "long-enough",
    confirm: str | None = None,
    ign: str = "Turbine",
) -> dict:
    return {
        "email": email,
        "password": password,
        "confirm_password": password if confirm is None else confirm,
        "ign": ign,
    }


async def test_register_then_signin_returns_a_session(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        created = await http.post("/auth/register", json=_register_body())
        assert created.status_code == 200
        body = created.json()
        assert body["email"] == "player@example.com"
        assert body["ign"] == "Turbine"
        assert body["paid"] is False
        assert body["token"]

        signed_in = await http.post(
            "/auth/signin",
            json={"email": "player@example.com", "password": "long-enough"},
        )
    assert signed_in.status_code == 200
    assert signed_in.json()["email"] == "player@example.com"
    assert signed_in.json()["ign"] == "Turbine"
    assert signed_in.json()["token"]


async def test_register_does_not_grant_paid(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post(
            "/auth/register", json=_register_body(email="free@example.com")
        )
    assert response.status_code == 200
    assert response.json()["paid"] is False


async def test_duplicate_register_is_rejected(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        first = await http.post("/auth/register", json=_register_body())
        second = await http.post(
            "/auth/register",
            json=_register_body(password="different1", ign="OtherName"),
        )
    assert first.status_code == 200
    assert second.status_code == 409


async def test_mismatched_passwords_are_rejected(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post(
            "/auth/register",
            json=_register_body(confirm="not-the-same"),
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "Passwords do not match"


async def test_register_requires_an_ign(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post("/auth/register", json=_register_body(ign=""))
    assert response.status_code == 400


async def test_wrong_password_is_rejected(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        await http.post("/auth/register", json=_register_body())
        response = await http.post(
            "/auth/signin",
            json={"email": "player@example.com", "password": "wrong-password"},
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


async def test_unknown_email_looks_the_same_as_a_wrong_password(
    redis_client, anon_settings
):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post(
            "/auth/signin",
            json={"email": "nobody@example.com", "password": "long-enough"},
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


async def test_signin_accepts_ign(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        await http.post("/auth/register", json=_register_body())
        signed_in = await http.post(
            "/auth/signin",
            json={"email": "Turbine", "password": "long-enough"},
        )
    assert signed_in.status_code == 200
    assert signed_in.json()["email"] == "player@example.com"
    assert signed_in.json()["ign"] == "Turbine"


async def test_signin_ign_is_case_insensitive(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        await http.post("/auth/register", json=_register_body())
        signed_in = await http.post(
            "/auth/signin",
            json={"email": "turbine", "password": "long-enough"},
        )
    assert signed_in.status_code == 200
    assert signed_in.json()["email"] == "player@example.com"


async def test_duplicate_ign_signin_uses_the_matching_password(
    redis_client, anon_settings
):
    """Two local rows can share an IGN. Unlock the one whose password matches."""
    from api.services import accounts

    async with _client(redis_client, anon_settings) as http:
        first = await http.post("/auth/register", json=_register_body())
        assert first.status_code == 200
        second = await http.post(
            "/auth/register",
            json=_register_body(
                email="other@example.com",
                password="other-pass",
                ign="OtherName",
            ),
        )
        assert second.status_code == 200
        conn = accounts._connection(anon_settings.accounts_db_path)
        conn.execute("DROP INDEX IF EXISTS accounts_ign_nocase")
        conn.execute(
            "UPDATE accounts SET ign = 'Turbine' WHERE email = 'other@example.com'"
        )
        by_other = await http.post(
            "/auth/signin",
            json={"email": "Turbine", "password": "other-pass"},
        )
        by_first = await http.post(
            "/auth/signin",
            json={"email": "Turbine", "password": "long-enough"},
        )
    assert by_other.status_code == 200
    assert by_other.json()["email"] == "other@example.com"
    assert by_first.status_code == 200
    assert by_first.json()["email"] == "player@example.com"


async def test_unknown_ign_looks_the_same_as_a_wrong_password(
    redis_client, anon_settings
):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post(
            "/auth/signin",
            json={"email": "Nobody", "password": "long-enough"},
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


async def test_duplicate_ign_register_is_rejected(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        first = await http.post("/auth/register", json=_register_body())
        second = await http.post(
            "/auth/register",
            json=_register_body(email="other@example.com", password="different1"),
        )
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "An account with this IGN already exists"


async def test_short_password_is_rejected_on_register(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post(
            "/auth/register",
            json=_register_body(password="short"),
        )
    assert response.status_code == 400


async def test_signin_is_rate_limited(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        statuses = []
        for _ in range(anon_settings.lookup_rate_limit_anonymous + 1):
            response = await http.post(
                "/auth/signin",
                json={"email": "nobody@example.com", "password": "long-enough"},
            )
            statuses.append(response.status_code)

    assert statuses[:-1] == [401] * anon_settings.lookup_rate_limit_anonymous
    assert statuses[-1] == 429


@pytest.mark.parametrize("provider", ["google", "microsoft"])
async def test_oauth_start_is_not_wired_yet(redis_client, anon_settings, provider):
    async with _client(redis_client, anon_settings) as http:
        response = await http.get(f"/auth/oauth/{provider}")
    assert response.status_code == 501


async def test_password_session_uses_the_signed_in_quota(redis_client, anon_settings):
    """
    Registering used to leave you on the anonymous IP bucket because
    get_optional_user only understood JWKS tokens. A password session
    must count against the signed-in allowance instead.
    """
    async with _client(redis_client, anon_settings) as http:
        created = await http.post(
            "/auth/register",
            json=_register_body(ign="QuotaPlayer"),
        )
        token = created.json()["token"]
        usage = await http.get(
            "/chat/usage", headers={"Authorization": f"Bearer {token}"}
        )
    body = usage.json()
    assert body["scope"] == "user"
    assert body["limit"] == anon_settings.free_message_limit
    assert body["limit"] > anon_settings.anonymous_message_limit


async def test_unknown_oauth_provider_is_not_found(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.get("/auth/oauth/facebook")
    assert response.status_code == 404


async def test_guest_preferences_default_to_train_on(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.get("/auth/preferences")
    assert response.status_code == 200
    assert response.json() == {"train_on_data": True}


async def test_guest_cannot_persist_preferences(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.patch(
            "/auth/preferences", json={"train_on_data": False}
        )
    assert response.status_code == 401


async def test_signed_in_preferences_default_on_and_can_opt_out(
    redis_client, anon_settings
):
    async with _client(redis_client, anon_settings) as http:
        created = await http.post("/auth/register", json=_register_body())
        token = created.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        before = await http.get("/auth/preferences", headers=headers)
        assert before.json() == {"train_on_data": True}

        updated = await http.patch(
            "/auth/preferences",
            json={"train_on_data": False},
            headers=headers,
        )
        assert updated.status_code == 200
        assert updated.json() == {"train_on_data": False}

        after = await http.get("/auth/preferences", headers=headers)
    assert after.json() == {"train_on_data": False}
