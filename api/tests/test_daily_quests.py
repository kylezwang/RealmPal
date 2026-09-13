"""Claiming today's quests grants +1 message, once."""
from __future__ import annotations

import httpx

from api.auth import create_jwt
from api.config import get_settings
from api.dependencies import get_redis
from api.main import create_app
from api.services import entitlements
from api.services.rate_limit import quota_for

from .conftest import build_request

CALLER_IP = "198.51.100.7"
CALLER = (CALLER_IP, 44321)


def _client(redis_client, settings) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_settings] = lambda: settings
    transport = httpx.ASGITransport(app=app, client=CALLER)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_guest_claim_adds_one_daily_message(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        before = (await http.get("/chat/usage")).json()
        first = (await http.post("/chat/quests/claim")).json()
        second = (await http.post("/chat/quests/claim")).json()
        after = (await http.get("/chat/usage")).json()

    assert first["granted"] is True
    assert first["bonus"] == 1
    assert second["granted"] is False
    assert after["limit"] == before["limit"] + 1
    assert after["remaining"] == before["remaining"] + 1


async def test_paid_claim_adds_one_included_reply(redis_client, anon_settings):
    email = "pro-quests@example.com"
    await entitlements.upsert(email, status="active", settings=anon_settings)
    token = create_jwt({"email": email, "paid": True}, anon_settings)
    headers = {"Authorization": f"Bearer {token}"}

    async with _client(redis_client, anon_settings) as http:
        before = (await http.get("/chat/usage", headers=headers)).json()
        claimed = (await http.post("/chat/quests/claim", headers=headers)).json()
        after = (await http.get("/chat/usage", headers=headers)).json()

    assert claimed["granted"] is True
    assert after["claude_limit"] == before["claude_limit"] + 1
    assert after["claude_remaining"] == before["claude_remaining"] + 1


async def test_guest_claim_survives_quota_key_shape(redis_client, anon_settings):
    """Bonus is keyed the same way usage is, not on a browser session id."""
    quota = quota_for(None, build_request(peer=CALLER_IP), anon_settings)
    await redis_client.set(quota.key, anon_settings.anonymous_message_limit)

    async with _client(redis_client, anon_settings) as http:
        await http.post("/chat/quests/claim")
        body = (await http.get("/chat/usage")).json()

    assert body["used"] == anon_settings.anonymous_message_limit
    assert body["remaining"] == 1


async def test_claim_expires_with_quota_not_at_utc_midnight(redis_client, anon_settings):
    """The bonus/claim keys must expire when the caller's actual rolling
    quota resets, not at a fixed UTC-midnight boundary. Otherwise a claim
    near midnight could either vanish before the quota it boosts resets, or
    (worse) become re-claimable while the same quota window is still live."""
    from api.services.daily_quests import _claimed_key, _free_bonus_key, identity_key
    from api.services.rate_limit import consume

    quota = quota_for(None, build_request(peer=CALLER_IP), anon_settings)
    await consume(redis_client, quota)  # Starts the quota's own rolling TTL.
    quota_ttl = await redis_client.ttl(quota.key)
    assert quota_ttl > 0

    async with _client(redis_client, anon_settings) as http:
        claimed = (await http.post("/chat/quests/claim")).json()
    assert claimed["granted"] is True

    bucket = identity_key(quota.key, anon_settings)
    claim_ttl = await redis_client.ttl(_claimed_key(bucket))
    bonus_ttl = await redis_client.ttl(_free_bonus_key(bucket))
    # Synced to the quota's TTL (within a couple seconds of test runtime),
    # not a full fresh 24h from claim time and not a fixed calendar key.
    assert 0 < claim_ttl <= quota_ttl
    assert 0 < bonus_ttl <= quota_ttl


async def test_quest_art_returns_todays_dungeon_and_shiny(redis_client, anon_settings):
    from api.models.item import ItemProfile
    from api.services.daily_quests import todays_dungeon_name
    from api.services.wiki_scaling import write_cached_item

    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Snake Eye Ring",
            shiny_sprite_url="https://example.com/snake-shiny.png",
        ),
        60,
    )
    async with _client(redis_client, anon_settings) as http:
        body = (await http.get("/chat/quests/art")).json()

    assert body["dungeon_name"]
    assert "Guide to complete" in body["dungeon_prompt"]
    assert body["shiny_name"]
    assert todays_dungeon_name() in body["dungeon_prompt"] or body["dungeon_name"]


async def test_quest_art_shift_changes_dungeon(redis_client, anon_settings):
    from api.services.daily_quests import todays_dungeon_name

    async with _client(redis_client, anon_settings) as http:
        today = (await http.get("/chat/quests/art")).json()
        shifted = (await http.get("/chat/quests/art", params={"shift": 1})).json()

    assert today["dungeon_name"] != shifted["dungeon_name"]
    assert todays_dungeon_name(shift=1) in shifted["dungeon_prompt"] or shifted["dungeon_name"]
