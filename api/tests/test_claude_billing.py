"""Paid Claude pool and the $0 spend-cap default."""
from __future__ import annotations

import httpx
import pytest

from api.auth import create_jwt
from api.config import get_settings
from api.dependencies import get_redis
from api.main import create_app
from api.services import entitlements
from api.services.claude_billing import consume_claude_reply
from api.identity import AuthenticatedUser

CALLER = ("198.51.100.7", 44321)


def _client(redis_client, settings) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_settings] = lambda: settings
    transport = httpx.ASGITransport(app=app, client=CALLER)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_included_claude_replies_then_402_at_default_cap(
    redis_client, anon_settings
):
    email = "pro@example.com"
    await entitlements.upsert(email, status="active", settings=anon_settings)
    user = AuthenticatedUser(subject=email, email=email, claims={"email": email})
    settings = anon_settings.model_copy(update={"paid_claude_included": 2})
    for _ in range(2):
        await consume_claude_reply(redis_client, user, settings, paid=True)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        await consume_claude_reply(redis_client, user, settings, paid=True)
    assert raised.value.status_code == 402
    assert raised.value.detail["reason"] == "claude_pool"


async def test_custom_spend_cap_round_trip(redis_client, anon_settings):
    from api.services import billing_prefs

    email = "custom@example.com"
    await entitlements.upsert(email, status="active", settings=anon_settings)
    saved = await billing_prefs.set_spend_cap_usd(email, 35, anon_settings)
    assert saved == 35.0
    assert await billing_prefs.get_spend_cap_usd(email, anon_settings) == 35.0


async def test_spend_cap_lets_overage_through(redis_client, anon_settings):
    from api.services import billing_prefs
    from fastapi import HTTPException

    email = "power@example.com"
    await entitlements.upsert(email, status="active", settings=anon_settings)
    await billing_prefs.set_spend_cap_usd(email, 5, anon_settings)
    user = AuthenticatedUser(subject=email, email=email, claims={"email": email})
    settings = anon_settings.model_copy(update={"paid_claude_included": 1})
    await consume_claude_reply(redis_client, user, settings, paid=True)
    await consume_claude_reply(redis_client, user, settings, paid=True)

    token = create_jwt({"email": email, "paid": True}, anon_settings)
    async with _client(redis_client, anon_settings) as http:
        body = (
            await http.get(
                "/payments/on-demand",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()
    assert body["spend_cap_usd"] == 5
    assert body["claude_used"] == 2
    assert body["on_demand_spent_usd"] == pytest.approx(anon_settings.claude_overage_usd)

    # Turning the cap back to $0 is the same as "included only".
    await billing_prefs.set_spend_cap_usd(email, 0, anon_settings)
    with pytest.raises(HTTPException) as raised:
        await consume_claude_reply(redis_client, user, settings, paid=True)
    assert raised.value.detail["reason"] == "claude_pool"
