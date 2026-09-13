"""
End-to-end quota behaviour through the real /chat/usage endpoint.

test_rate_limit.py covers the keying logic in isolation. These go through the
full request path, because the bug that motivated this work lived *between*
layers: uvicorn's proxy-header handling was rewriting the client address
before our code could decide whether to trust it.
"""
from __future__ import annotations

import httpx
import pytest

from api.config import get_settings
from api.dependencies import get_qdrant, get_redis
from api.main import create_app
from api.services.budget import KILL_SWITCH_KEY, today_key
from api.services.rate_limit import quota_for

from .conftest import build_request

# ASGITransport lets us pin the socket peer, which TestClient can't do.
CALLER_IP = "198.51.100.7"
CALLER = (CALLER_IP, 44321)


def _client(app, redis_client, settings) -> httpx.AsyncClient:
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_settings] = lambda: settings
    transport = httpx.ASGITransport(app=app, client=CALLER)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def stream_client(redis_client, anon_settings, monkeypatch):
    """A client for /chat/stream, with Qdrant stubbed out."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    app = create_app()
    app.dependency_overrides[get_qdrant] = lambda: object()
    return _client(app, redis_client, anon_settings)


@pytest.fixture
def client(redis_client, anon_settings, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    return _client(create_app(), redis_client, anon_settings)


@pytest.fixture
def spend(redis_client, anon_settings):
    """Put a known amount of usage on the calling IP's bucket."""

    async def _spend(count: int) -> None:
        quota = quota_for(None, build_request(peer=CALLER_IP), anon_settings)
        await redis_client.set(quota.key, count)

    return _spend


async def test_usage_starts_empty(client, anon_settings):
    async with client as http:
        body = (await http.get("/chat/usage")).json()
    assert body["used"] == 0
    assert body["limit"] == anon_settings.anonymous_message_limit
    assert body["remaining"] == anon_settings.anonymous_message_limit
    assert body["scope"] == "ip"
    assert body["tier"] == "guest"


async def test_health_reports_the_chat_provider(client):
    async with client as http:
        body = (await http.get("/health")).json()
    assert body["status"] == "ok"
    assert body["provider"] in {"anthropic", "foundry"}
    assert "model" in body


async def test_rotating_session_id_does_not_reset_usage(client, spend):
    """
    The original bug: session_id came from the browser, so clearing
    localStorage handed out a brand new allowance.
    """
    await spend(2)
    async with client as http:
        for session_id in ["aaaa-1111", "bbbb-2222", "cccc-3333", "totally-new"]:
            body = (
                await http.get("/chat/usage", params={"session_id": session_id})
            ).json()
            assert body["used"] == 2, f"session_id {session_id} got a fresh bucket"
            assert body["remaining"] == 1


@pytest.mark.parametrize(
    "forwarded",
    ["9.9.9.9", "1.2.3.4", "8.8.8.8, 7.7.7.7", "127.0.0.1", ""],
)
async def test_spoofed_forwarded_for_does_not_reset_usage(client, spend, forwarded):
    """
    Requires the server to run without uvicorn's proxy-header handling. If
    this starts failing in deployment but passes here, check that
    --no-proxy-headers is still set on every launch path.
    """
    await spend(2)
    async with client as http:
        body = (
            await http.get("/chat/usage", headers={"X-Forwarded-For": forwarded})
        ).json()
    assert body["used"] == 2


async def test_unverifiable_bearer_token_does_not_grant_identity(client, spend):
    await spend(2)
    async with client as http:
        body = (
            await http.get(
                "/chat/usage", headers={"Authorization": "Bearer not.a.real.token"}
            )
        ).json()
    assert body["scope"] == "ip"
    assert body["used"] == 2


async def test_kill_switch_returns_503_before_spending_quota(
    stream_client, redis_client, anon_settings
):
    """
    A shut-off deployment must not consume someone's allowance on a request
    it isn't going to answer.
    """
    await redis_client.set(KILL_SWITCH_KEY, "Down for maintenance.")

    async with stream_client as http:
        response = await http.post("/chat/stream", json={"message": "hello"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Down for maintenance."

    quota = quota_for(None, build_request(peer=CALLER_IP), anon_settings)
    assert await redis_client.get(quota.key) is None


async def test_exhausted_budget_returns_503(
    stream_client, redis_client, anon_settings
):
    await redis_client.set(today_key(), anon_settings.daily_cost_budget_micros)

    async with stream_client as http:
        response = await http.post("/chat/stream", json={"message": "hello"})

    assert response.status_code == 503
    assert "daily usage limit" in response.json()["detail"]


async def test_oversized_message_is_rejected_before_any_work(stream_client):
    from api.models.chat import MAX_MESSAGE_CHARS

    async with stream_client as http:
        response = await http.post(
            "/chat/stream", json={"message": "a" * (MAX_MESSAGE_CHARS + 1)}
        )

    assert response.status_code == 422


async def test_verified_token_switches_to_the_user_bucket(
    redis_client, auth_settings, jwks_server, make_token, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")

    # Usage sitting on the caller's IP bucket must not follow them into their
    # account, and vice versa.
    ip_quota = quota_for(None, build_request(peer=CALLER_IP), auth_settings)
    await redis_client.set(ip_quota.key, 3)

    async with _client(create_app(), redis_client, auth_settings) as http:
        body = (
            await http.get(
                "/chat/usage", headers={"Authorization": f"Bearer {make_token()}"}
            )
        ).json()

    assert body["scope"] == "user"
    assert body["used"] == 0
    assert body["limit"] == auth_settings.free_message_limit
    assert body["limit"] > auth_settings.anonymous_message_limit
