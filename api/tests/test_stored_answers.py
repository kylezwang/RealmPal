"""Stored answers skip Claude on drops and minted builds."""
from __future__ import annotations

import httpx
import pytest

from api.config import get_settings
from api.dependencies import get_optional_user, get_qdrant, get_redis
from api.identity import AuthenticatedUser
from api.main import create_app
from api.models.item import ItemProfile
from api.models.player import PlayerProfile
from api.services import entitlements
from api.services.claude_billing import peek_claude_usage
from api.services.rate_limit import peek, quota_for
from api.services.dungeon_guide import INDEX_CACHE_KEY, PAGE_CACHE_PREFIX
from api.services.item_aliases import CATALOG_PREFIX
from api.services.stored_answers import (
    _build_reply,
    _compose_guide_brief,
    _shiny_divine_flags,
    _shiny_divine_item_name,
    _shiny_divine_reply,
    _strip_item_card_hooks,
    _strip_wiki_chrome,
    build_brief_key,
    maybe_mint_brief,
)
from api.services.wiki_scaling import write_cached_item

from .conftest import build_request

SIGNED_IN = AuthenticatedUser(subject="player@example.com", email="player@example.com")

CALLER = ("198.51.100.7", 44321)


class _TextStream:
    def __init__(self, text: str):
        self._text = text
        self._done = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._done:
            raise StopAsyncIteration
        self._done = True
        return self._text


class _FakeStream:
    def __init__(self, text: str):
        self.text_stream = _TextStream(text)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get_final_message(self):
        class _Usage:
            input_tokens = 12
            output_tokens = 8

        class _Message:
            usage = _Usage()

        return _Message()


class _FakeClient:
    def __init__(self, calls: list[str], text: str = "minted Wis Kensei [item:Rift Ripper]"):
        self._calls = calls
        self._text = text
        self.messages = self

    def stream(self, **kwargs):
        self._calls.append(kwargs.get("model") or "stream")
        return _FakeStream(self._text)

    async def close(self):
        return None


def _client(app, redis_client, settings) -> httpx.AsyncClient:
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_qdrant] = lambda: object()
    transport = httpx.ASGITransport(app=app, client=CALLER)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def stream_app(redis_client, anon_settings, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    calls: list[str] = []
    monkeypatch.setattr(
        "api.routers.chat.build_chat_client",
        lambda _settings: _FakeClient(calls),
    )
    app = create_app()
    return _client(app, redis_client, anon_settings), calls


async def _read_sse_text(response: httpx.Response) -> str:
    import json

    parts: list[str] = []
    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue
        chunk = json.loads(line[6:])
        if chunk.get("content"):
            parts.append(chunk["content"])
    return "".join(parts)


def test_shiny_divine_quest_prompt_extracts_the_item():
    assert _shiny_divine_item_name("Show me a shiny divine Crown") == "Crown"
    assert _shiny_divine_item_name("See a shiny divine Twilight Gemstone") == (
        "Twilight Gemstone"
    )
    assert (
        _shiny_divine_item_name(
            "Show me a shiny divine set with Fractal Blades and a cloak"
        )
        is None
    )


async def test_shiny_divine_item_never_hits_the_llm(
    stream_app, redis_client, anon_settings
):
    client, calls = stream_app
    await write_cached_item(
        redis_client,
        ItemProfile(name="The Forgotten Crown", drop_locations=["Oryx's Castle"]),
        anon_settings.wiki_ttl_seconds,
    )
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "Show me a shiny divine Crown", "session_id": "s-shiny"},
        )
        assert response.status_code == 200
        text = await _read_sse_text(response)
    assert calls == []
    assert "[loadout shiny divine]" in text
    assert "[item:The Forgotten Crown]" in text


def test_shiny_alone_extracts_the_item_and_strips_look_like():
    """Regression: shiny and divine are independent visual flags in-game (an
    item can be shiny without being divine, or vice versa), but this used to
    require both words together, so a plain "shiny X" fell through to a real
    Claude call with no way to actually render anything. Found live Sep 14
    with "What does shiny snake eye ring look like?"."""
    assert (
        _shiny_divine_item_name("What does shiny snake eye ring look like?")
        == "snake eye ring"
    )
    assert _shiny_divine_flags("What does shiny snake eye ring look like?") == (
        True,
        False,
    )


def test_divine_alone_extracts_the_item():
    assert _shiny_divine_item_name("What does divine Crown look like") == "Crown"
    assert _shiny_divine_flags("What does divine Crown look like") == (False, True)


def test_shiny_item_followed_by_a_new_sentence_stops_at_the_period():
    """Regression: the old regex was anchored to a bare `$` with no way to
    stop partway through the message, so a second sentence asking a real
    follow-up question got glued onto the item name as one giant "name."
    Found live Sep 14: "Shiny divine snake eye ring. Is it insane with the
    awakened enchantment?" extracted "snake eye ring. Is it insane with the
    awakened enchantment" instead of just "snake eye ring."""
    assert (
        _shiny_divine_item_name(
            "Shiny divine snake eye ring. Is it insane with the awakened enchantment?"
        )
        == "snake eye ring"
    )


def test_shiny_item_with_no_sentence_break_stops_at_the_auxiliary_verb():
    """Regression: found live Sep 14, same day as the test above but a
    harder case - "Shiny divine snake eye ring is the awakened enchantment
    good?" has no sentence-ending punctuation before the trailing "?" at
    all, the item name and the question run on as one grammatical sentence.
    The period/question-mark/"looks like" boundary from the fix above
    wasn't enough on its own; a bare auxiliary verb (is/does/has/can/will/
    should/would) is an equally valid stop point since no real item name
    contains one as a whole word."""
    assert (
        _shiny_divine_item_name(
            "Shiny divine snake eye ring is the awakened enchantment good?"
        )
        == "snake eye ring"
    )
    assert (
        _shiny_divine_item_name("Shiny divine Ring of Decades does it look good")
        == "Ring of Decades"
    )


def test_shiny_divine_set_request_with_no_named_item_is_not_treated_as_an_item():
    """Regression: found live Sep 14 (in-game playtest) - "best shiny divine
    set for full dexterity huntress" strips "set", leaving "for full
    dexterity huntress" as the "item name." No item was ever named, this is
    a build request (a set FOR this class), not "an item literally named
    X" - and no real item name starts with a bare preposition/relative
    word like "for". Must return None so this falls through to the general
    build-brief flow instead of a doomed wiki scrape for "for full dexterity
    huntress."."""
    assert (
        _shiny_divine_item_name("best shiny divine set for full dexteirty huntress")
        is None
    )
    assert _shiny_divine_item_name("shiny divine set on a mystic") is None
    assert _shiny_divine_item_name("shiny divine loadout for wizard") is None


def test_shiny_divine_bare_stat_and_class_is_not_treated_as_an_item():
    """Regression: found live Sep 14 (in-game playtest, minutes after the
    "for X" fix above closed one gap) - "shiny divine attack huntress" has
    no "for"/"set" to strip or catch, it's a bare stat+class pair with no
    item named at all, but nothing rejected it, so it went to a doomed wiki
    scrape of "/wiki/attack-huntress" (404 after a ~30s timeout, then
    negative-cached). If every remaining word is stat/class vocabulary
    (including nicknames like "dex"/"myst"), this is a build reference, not
    an item name."""
    assert _shiny_divine_item_name("shiny divine attack huntress") is None
    assert _shiny_divine_item_name("shiny divine attack huntress build") is None
    assert _shiny_divine_item_name("shiny divine dex huntress") is None
    assert _shiny_divine_item_name("shiny divine mystic") is None
    # Real items keep working: connector words / non-class-stat nouns mean
    # not every word is build vocabulary.
    assert _shiny_divine_item_name("Show me a shiny divine Crown") == "Crown"
    assert (
        _shiny_divine_item_name("Shiny divine Ring of Decades does it look good")
        == "Ring of Decades"
    )


async def test_shiny_divine_reply_resolves_a_still_glued_run_on_via_the_catalog(
    redis_client, anon_settings
):
    """Durable fix, layered on top of the regex fixes above: even a phrasing
    the auxiliary-verb regex hasn't been taught to stop at yet (or an older
    deployed revision that predates that regex fix) should still resolve to
    the real item, because _shiny_divine_reply now falls back to the real
    item catalog with trailing-word trimming instead of handing the
    frontend a name that was never a real item ("...ring is the awakened
    enchantment good" verbatim, guaranteed 404 after a ~30s scrape
    timeout)."""
    import json

    payload = [{"name": "Snake Eye Ring", "slot": "ring", "aliases": []}]
    await redis_client.set(f"{CATALOG_PREFIX}:all:cached", json.dumps(payload))

    reply = await _shiny_divine_reply(
        redis_client,
        "shiny divine snake eye ring is the awakened enchantment good",
        anon_settings.wiki_ttl_seconds,
    )
    assert reply is not None
    assert "[item:Snake Eye Ring]" in reply.text


async def test_shiny_divine_reply_gives_up_cleanly_on_pure_extraction_garbage(
    redis_client, anon_settings
):
    """When nothing in the catalog matches any prefix and the leftover text
    is too long to plausibly be a real item name, _shiny_divine_reply must
    return None (falling through to a different reply path) instead of a
    StoredReply pointing the frontend at a doomed lookup."""
    reply = await _shiny_divine_reply(
        redis_client,
        "shiny divine completely unrelated nonsense text that names nothing real",
        anon_settings.wiki_ttl_seconds,
    )
    assert reply is None


async def test_enchant_question_about_a_ring_does_not_reuse_a_cached_build_brief(
    redis_client, anon_settings
):
    """Regression: found live Sep 14 - after minting an Attack Ninja build
    brief, a later unrelated follow-up ("Shiny divine snake eye ring. Is it
    insane with the awakened enchantment?") got served that stale cached
    brief instead of an answer about the ring's enchant. "ring" alone flips
    parse_query's weak buildish regex True, which then pulled Ninja/Attack
    in from history no matter how unrelated the actual question was.
    Enchant questions have their own specialist and must never be
    intercepted by the generic class+stat build-brief cache."""
    await maybe_mint_brief(
        redis_client,
        "Best attack ninja build",
        "The stored Attack Ninja brief.",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert await redis_client.get(build_brief_key("Ninja", "Attack"))
    history = [
        "Best attack ninja build",
        "Would this be the bis attack ninja then?",
    ]
    reply = await _build_reply(
        redis_client,
        "Shiny divine snake eye ring. Is it insane with the awakened enchantment?",
        history,
    )
    assert reply is None


async def test_shiny_alone_item_never_hits_the_llm_and_renders_shiny_only(
    stream_app, redis_client, anon_settings
):
    client, calls = stream_app
    await write_cached_item(
        redis_client,
        ItemProfile(name="Snake Eye Ring", drop_locations=["Snake Pit"]),
        anon_settings.wiki_ttl_seconds,
    )
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={
                "message": "What does shiny snake eye ring look like?",
                "session_id": "s-shiny-only",
            },
        )
        assert response.status_code == 200
        text = await _read_sse_text(response)
    assert calls == []
    assert "[loadout shiny]" in text
    assert "[loadout shiny divine]" not in text
    assert "[item:Snake Eye Ring]" in text


async def test_drop_question_never_hits_the_llm(stream_app, redis_client, anon_settings):
    client, calls = stream_app
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Doom Bow",
            drop_locations=["The Shatters", "Oryx's Castle"],
        ),
        anon_settings.wiki_ttl_seconds,
    )
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "Where does Doom Bow drop?", "session_id": "s1"},
        )
        assert response.status_code == 200
        text = await _read_sse_text(response)
    assert calls == []
    assert "The Shatters" in text
    assert "[item:Doom Bow]" in text
    quota = quota_for(None, build_request(peer=CALLER[0]), anon_settings)
    assert await peek(redis_client, quota) == 0


async def test_anonymous_at_daily_limit_still_gets_stored_answer(
    stream_app, redis_client, anon_settings
):
    """A guest who already spent their Claude turns can still get a
    no-model reply. The daily cap only meters real AI calls."""
    client, calls = stream_app
    quota = quota_for(None, build_request(peer=CALLER[0]), anon_settings)
    await redis_client.set(quota.key, anon_settings.anonymous_message_limit)
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Doom Bow",
            drop_locations=["The Shatters"],
        ),
        anon_settings.wiki_ttl_seconds,
    )
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "Where does Doom Bow drop?", "session_id": "s1-limit"},
        )
        assert response.status_code == 200
        text = await _read_sse_text(response)
    assert calls == []
    assert "The Shatters" in text
    assert await peek(redis_client, quota) == anon_settings.anonymous_message_limit


async def test_stored_answers_are_burst_limited_even_after_daily_in_depth_is_spent(
    stream_app, redis_client, anon_settings
):
    """The daily Claude cap no longer blocks stored replies. A short-window
    burst cap still stops a flood of those free lookups."""
    client, calls = stream_app
    quota = quota_for(None, build_request(peer=CALLER[0]), anon_settings)
    await redis_client.set(quota.key, anon_settings.anonymous_message_limit)
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Doom Bow",
            drop_locations=["The Shatters"],
        ),
        anon_settings.wiki_ttl_seconds,
    )
    async with client as http:
        for i in range(anon_settings.chat_burst_limit_anonymous):
            response = await http.post(
                "/chat/stream",
                json={
                    "message": "Where does Doom Bow drop?",
                    "session_id": f"s-burst-{i}",
                },
            )
            assert response.status_code == 200, response.status_code
            await _read_sse_text(response)
        blocked = await http.post(
            "/chat/stream",
            json={"message": "Where does Doom Bow drop?", "session_id": "s-burst-over"},
        )
    assert blocked.status_code == 429
    assert "Try again in a minute" in blocked.json()["detail"]
    assert calls == []
    assert await peek(redis_client, quota) == anon_settings.anonymous_message_limit


async def test_claude_turn_at_daily_limit_still_returns_402(
    stream_app, redis_client, anon_settings
):
    client, calls = stream_app
    quota = quota_for(None, build_request(peer=CALLER[0]), anon_settings)
    await redis_client.set(quota.key, anon_settings.anonymous_message_limit)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={
                "message": "Tell me a fun fact about the weather",
                "session_id": "s-claude-capped",
            },
        )
    assert response.status_code == 402
    assert calls == []


async def test_player_lookup_at_daily_limit_is_stored_not_claude(
    stream_app, redis_client, anon_settings, monkeypatch
):
    """Look up player never calls Claude, so it still works after the
    in-depth cap. Live Sep 16: Nutz 402'd then the frontend scrape still
    attached a character card onto the leftover copy."""
    client, calls = stream_app

    async def fake_scrape(_redis, username, *, ttl_seconds):
        return PlayerProfile(username=username, fame=10, account_fame=20)

    monkeypatch.setattr(
        "api.services.stored_answers.get_or_scrape_player", fake_scrape
    )
    quota = quota_for(None, build_request(peer=CALLER[0]), anon_settings)
    await redis_client.set(quota.key, anon_settings.anonymous_message_limit)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "Look up player Nutz", "session_id": "s-player-capped"},
        )
        assert response.status_code == 200, response.status_code
        text = await _read_sse_text(response)
    assert calls == []
    assert "Fame" in text
    assert "Copy these" not in text
    assert await peek(redis_client, quota) == anon_settings.anonymous_message_limit


async def test_anonymous_claude_turn_still_spends_daily_quota(
    stream_app, redis_client, anon_settings
):
    client, calls = stream_app
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={
                "message": "Tell me a fun fact about the weather",
                "session_id": "s-claude",
            },
        )
        assert response.status_code == 200
        await _read_sse_text(response)
    assert calls
    quota = quota_for(None, build_request(peer=CALLER[0]), anon_settings)
    assert await peek(redis_client, quota) == 1


async def test_signed_in_stored_answer_skips_daily_quota(
    redis_client, anon_settings, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    calls: list[str] = []
    monkeypatch.setattr(
        "api.routers.chat.build_chat_client",
        lambda _settings: _FakeClient(calls),
    )
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: SIGNED_IN
    client = _client(app, redis_client, anon_settings)
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Doom Bow",
            drop_locations=["The Shatters"],
        ),
        anon_settings.wiki_ttl_seconds,
    )
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "Where does Doom Bow drop?", "session_id": "s1b"},
        )
        assert response.status_code == 200
        await _read_sse_text(response)
    assert calls == []
    quota = quota_for(SIGNED_IN, build_request(peer=CALLER[0]), anon_settings)
    assert await peek(redis_client, quota) == 0


async def test_paid_stored_hit_does_not_increment_claude_meter(
    redis_client, anon_settings, monkeypatch
):
    email = "pro-stored@example.com"
    await entitlements.upsert(email, status="active", settings=anon_settings)
    user = AuthenticatedUser(subject=email, email=email, claims={"email": email})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    calls: list[str] = []
    monkeypatch.setattr(
        "api.routers.chat.build_chat_client",
        lambda _settings: _FakeClient(calls),
    )
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: user
    client = _client(app, redis_client, anon_settings)
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Doom Bow",
            drop_locations=["The Shatters"],
        ),
        anon_settings.wiki_ttl_seconds,
    )
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "Where does Doom Bow drop?", "session_id": "s1c"},
        )
        assert response.status_code == 200
        await _read_sse_text(response)
    assert calls == []
    usage = await peek_claude_usage(redis_client, email, anon_settings)
    assert usage.used == 0
    assert usage.included == anon_settings.paid_claude_included


async def test_second_wis_kensei_is_a_cache_hit(stream_app, redis_client, anon_settings):
    client, calls = stream_app
    await maybe_mint_brief(
        redis_client,
        "Best items for a Wis Kensei",
        "Rift Rippers and a sheath. [item:Rift Ripper]",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert await redis_client.get(build_brief_key("Kensei", "Wisdom"))
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "best items for a wis kensei", "session_id": "s2"},
        )
        assert response.status_code == 200
        text = await _read_sse_text(response)
    assert calls == []
    assert "Rift Ripper" in text


async def test_constrained_follow_up_still_streams(
    stream_app, redis_client, anon_settings
):
    client, calls = stream_app
    await maybe_mint_brief(
        redis_client,
        "Best items for a Wis Kensei",
        "The stored Wis Kensei brief.",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "wis kensei build but no ST", "session_id": "s3"},
        )
        assert response.status_code == 200
        await _read_sse_text(response)
    assert calls == [anon_settings.claude_model]


async def test_dungeon_guide_without_a_brief_streams_haiku(
    stream_app, anon_settings
):
    client, calls = stream_app
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "Guide to complete The Shatters", "session_id": "s4"},
        )
        assert response.status_code == 200
        await _read_sse_text(response)
    assert calls == [anon_settings.claude_light_model]


def test_wiki_chrome_keeps_realmeye_prose():
    text = _strip_wiki_chrome(
        "The Shatters - the RotMG Wiki\n"
        "This page is currently a work in progress.\n"
        "Last updated: Exalt Version 5.13.0.0 (June 2025)\n"
        "Contents\n"
        "Hard Mode has three boss fights.\n"
        "Do not mention wings — that mechanic is regular The Shatters.\n"
        "Back to top\n"
    )
    assert "Hard Mode has three boss fights." in text
    assert "work in progress" not in text
    assert "Last updated" not in text
    assert "the RotMG Wiki" not in text
    assert "Do not mention wings" not in text


@pytest.mark.asyncio
async def test_dungeon_brief_dumps_wiki_not_a_claude_essay(redis_client):
    import json

    await redis_client.set(
        INDEX_CACHE_KEY,
        json.dumps(
            [
                {
                    "title": "The Shatters",
                    "slug": "the-shatters",
                    "url": "https://www.realmeye.com/wiki/the-shatters",
                    "kind": "dungeon",
                }
            ]
        ),
    )
    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}the-shatters",
        json.dumps(
            {
                "title": "The Shatters - the RotMG Wiki",
                "slug": "the-shatters",
                "url": "https://www.realmeye.com/wiki/the-shatters",
                "text": (
                    "This page is currently a work in progress.\n"
                    "Hard Mode\n"
                    "Drops of Interest\n"
                    "History\n\n"
                    "The Shatters is an extremely dangerous and lengthy dungeon.\n\n"
                    "Hard Mode\n\n"
                    "Kill the Source and then fight Valen, Nox, and Azamoth.\n"
                    "Do not mention wings — that mechanic is regular The Shatters.\n"
                ),
            }
        ),
    )
    text = await _compose_guide_brief(redis_client, "Hardmode Shatters", 3600)
    assert text
    assert "Kill the Source" in text
    assert "extremely dangerous" not in text
    assert "work in progress" not in text
    assert "Do not mention wings" not in text
    assert "the RotMG Wiki" not in text
    minted = await maybe_mint_brief(
        redis_client,
        "Guide to complete Hardmode Shatters",
        "A short Claude rewrite of Shatters.",
        ttl_seconds=3600,
    )
    assert minted is None


def test_guide_brief_drops_item_card_hooks():
    text = _strip_item_card_hooks(
        "Kill [Valor](/wiki/valor) then loot [item:Peacekeeper] "
        "[sprite:Ice Crown] and [Warmonger](https://www.realmeye.com/wiki/warmonger)."
    )
    assert "Valor" in text
    assert "[item:" not in text
    assert "[sprite:" not in text
    assert "/wiki/" not in text
