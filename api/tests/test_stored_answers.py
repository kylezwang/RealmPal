"""Stored answers skip Claude on drops and minted builds."""
from __future__ import annotations

import json

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
    _ability_reply,
    _build_reply,
    _compose_guide_brief,
    _shiny_divine_flags,
    _shiny_divine_item_name,
    _shiny_divine_reply,
    _slot_reply,
    _strip_item_card_hooks,
    _strip_wiki_chrome,
    ability_brief_key,
    build_brief_key,
    is_ability_ask,
    is_retry_query,
    maybe_mint_brief,
    try_stored_reply,
)
from api.services.wiki_scaling import CACHE_PREFIX, HUB_PREFIX, write_cached_item

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


async def _seed_class_scaling(
    redis, class_name: str, item_name: str, stat: str
) -> None:
    await redis.set(
        f"{CACHE_PREFIX}:{class_name.lower()}",
        json.dumps(
            {
                "class_name": class_name,
                "abilities": [
                    {
                        "name": item_name,
                        "tier": "UT",
                        "scales": {stat: f"per {stat}"},
                    }
                ],
            }
        ),
    )


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
    assert (
        _shiny_divine_item_name("Shiny divine awakened snake eye ring")
        == "snake eye ring"
    )
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


async def test_shiny_divine_awakened_ring_never_hits_the_llm(
    stream_app, redis_client, anon_settings
):
    """Found live Sep 21: 'Shiny divine awakened snake eye ring' was treated
    as an enchant question, so Claude had no [loadout] chunk."""
    client, calls = stream_app
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Snake Eye Ring",
            type="ring",
            shiny_sprite_url="https://www.realmeye.com/s/a/img/wiki/shiny.png",
        ),
        anon_settings.wiki_ttl_seconds,
    )
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={
                "message": "Shiny divine awakened snake eye ring",
                "session_id": "s-awakened-shiny",
            },
        )
        assert response.status_code == 200
        text = await _read_sse_text(response)
    assert calls == []
    assert "[loadout shiny divine]" in text
    assert "[item:Snake Eye Ring]" in text


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


async def test_new_single_item_ask_does_not_reuse_a_stale_set_from_history(
    redis_client, anon_settings
):
    """Regression: found live Sep 22. A chat that had earlier visualized a
    real 4-item set, then later asked for a *different*, single new item
    ("shiny divine awakened snake eye ring"), got "Same items, shown as
    Shiny Divine" replaying the old 4-item set - because
    _set_visualize_reply's "no names on this turn? borrow 2+ [item:] tokens
    from history" fallback fired on ANY message without 2+ named items,
    not just genuine "same set" follow-ups. The frontend also has no item
    to fetch for that stale set (it re-derives names from the *current*
    prompt), so nothing rendered at all - no sprite, just the text. A
    message that names exactly one real item on its own must resolve that
    item via _shiny_divine_reply instead."""
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Snake Eye Ring",
            type="ring",
            shiny_sprite_url="https://www.realmeye.com/s/a/img/wiki/shiny.png",
        ),
        anon_settings.wiki_ttl_seconds,
    )
    reply = await try_stored_reply(
        redis_client,
        "shiny divine awakened snake eye ring",
        history=[
            "shiny divine snake ring",
            "[loadout shiny divine]\n[item:Doom Bow]\n[item:Quiver of Thunder]\n"
            "[item:Cackling Straitjacket]\n[item:The Forgotten Crown]",
        ],
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert reply is not None
    assert "[item:Snake Eye Ring]" in reply.text
    assert "Doom Bow" not in reply.text
    assert "Same items" not in reply.text


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
    await _seed_class_scaling(redis_client, "Ninja", "Poison Fang Star", "Attack")
    await maybe_mint_brief(
        redis_client,
        "Best attack ninja build",
        "The stored Attack Ninja brief. [item:Poison Fang Star]",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert await redis_client.get(build_brief_key("Ninja", "Attack"))
    reply = await _build_reply(
        redis_client,
        "Shiny divine snake eye ring. Is it insane with the awakened enchantment?",
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


def test_legendary_item_extracts_like_divine():
    assert _shiny_divine_item_name("What does legendary Crown look like") == "Crown"
    assert _shiny_divine_item_name("I want to see a rare straitjacket") == (
        "straitjacket"
    )
    assert _shiny_divine_item_name("make it legendary") is None
    assert _shiny_divine_item_name("make it legendary please") is None
    assert _shiny_divine_flags("What does legendary Crown look like") == (
        False,
        False,
    )


async def test_make_it_legendary_keeps_shiny_from_history(redis_client, anon_settings):
    await write_cached_item(
        redis_client,
        ItemProfile(name="Cackling Straitjacket", drop_locations=["Parasite Chambers"]),
        anon_settings.wiki_ttl_seconds,
    )
    reply = await _shiny_divine_reply(
        redis_client,
        "make it legendary",
        anon_settings.wiki_ttl_seconds,
        history=["I want to see a shiny straitjacket"],
    )
    assert reply is not None
    assert "[loadout shiny legendary]" in reply.text
    assert "[item:Cackling Straitjacket]" in reply.text

    uncommon = await _shiny_divine_reply(
        redis_client,
        "make it uncommon",
        anon_settings.wiki_ttl_seconds,
        history=[
            "I want to see a shiny straitjacket",
            "make it legendary",
        ],
    )
    assert uncommon is not None
    assert "[loadout shiny uncommon]" in uncommon.text
    assert "[item:Cackling Straitjacket]" in uncommon.text


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


async def test_cached_build_does_not_resurface_on_an_unrelated_follow_up(
    redis_client, anon_settings
):
    """Stored briefs only match when this turn asks for that class+stat
    again. Found live Sep 16: after a Dexterity Huntress brief, a later
    LLM-bound prompt inherited Huntress/Dexterity from history and
    streamed the same loadout instead of falling through to Claude."""
    await _seed_class_scaling(
        redis_client, "Huntress", "Lifebringing Lotus", "Dexterity"
    )
    await maybe_mint_brief(
        redis_client,
        "Best items for a dex huntress",
        "Frozen Whisper and Lifebringing Lotus.",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert await redis_client.get(build_brief_key("Huntress", "Dexterity"))
    same_ask = await _build_reply(
        redis_client, "Best items for a dexterity huntress"
    )
    assert same_ask is not None
    assert "Frozen Whisper" in same_ask.text
    slipped = await _build_reply(
        redis_client, "Tell me a fun fact about the weather"
    )
    assert slipped is None


async def test_guest_at_limit_gets_paywall_not_a_prior_build_brief(
    stream_app, redis_client, anon_settings
):
    """Guest spent in-depth, then sent an LLM prompt in the same Huntress
    thread. Must 402 the paywall, not replay the cached loadout."""
    client, calls = stream_app
    quota = quota_for(None, build_request(peer=CALLER[0]), anon_settings)
    await redis_client.set(quota.key, anon_settings.anonymous_message_limit)
    await _seed_class_scaling(
        redis_client, "Huntress", "Lifebringing Lotus", "Dexterity"
    )
    await maybe_mint_brief(
        redis_client,
        "Best items for a dex huntress",
        "Frozen Whisper and Lifebringing Lotus.",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={
                "message": "Tell me a fun fact about the weather",
                "session_id": "s-cached-slip",
                "history": [
                    {
                        "role": "user",
                        "content": "Best items for a dex huntress",
                    },
                    {
                        "role": "assistant",
                        "content": "Frozen Whisper and Lifebringing Lotus.",
                    },
                ],
            },
        )
    assert response.status_code == 402
    assert calls == []
    assert "Frozen Whisper" not in (response.text or "")


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


async def test_best_bows_uses_cores_not_hub_t0(redis_client, anon_settings):
    """Live Sep 16: 'Best bows in the game' listed Shortbow because the
    RealmEye hub is T0-first and _slot_reply took the first six rows."""
    await redis_client.set(
        f"{HUB_PREFIX}:bows",
        json.dumps(
            [
                {"name": "Shortbow", "tier": "T0"},
                {"name": "Reinforced Bow", "tier": "T1"},
                {"name": "Makakoyumi", "tier": "UT"},
            ]
        ),
    )
    reply = await _slot_reply(
        redis_client,
        "Best bows in the game",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert reply is not None
    assert "Makakoyumi" in reply.text
    assert "Shortbow" not in reply.text
    assert "Reinforced Bow" not in reply.text
    assert "RealmEye hub" not in reply.text
    assert "UmiEnjoyers" in reply.text


async def test_best_swords_and_rings_use_community_cores(
    redis_client, anon_settings
):
    swords = await _slot_reply(
        redis_client,
        "Best swords in the game",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert swords is not None
    assert "Divinity" in swords.text
    assert "Damnation" in swords.text
    rings = await _slot_reply(
        redis_client,
        "Best rings in the game",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert rings is not None
    assert "Kagenohikari" in rings.text
    assert "Chrysalis of Eternity" in rings.text
    armor = await _slot_reply(
        redis_client,
        "Best armor in the game",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert armor is not None
    assert "Vesture of Duality" in armor.text
    assert "Cackling Straitjacket" in armor.text


async def test_best_equipment_for_dexterity_aims_at_that_stat(
    redis_client, anon_settings
):
    await redis_client.set(
        f"{HUB_PREFIX}:bows",
        json.dumps([{"name": "Makakoyumi", "tier": "UT"}]),
    )
    await redis_client.set(
        "umi:bis:v2:archer",
        json.dumps(
            [
                "## Umi tab: Dexterity Archer (?tab=dexterity-archer)\n"
                "Makakoyumi\n",
                "https://www.umienjoyers.com/guides/best-in-slot/archer",
            ]
        ),
    )
    reply = await _slot_reply(
        redis_client,
        "Best equipment for dexterity",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert reply is not None
    assert "maximize Dexterity" in reply.text
    assert "Makakoyumi" in reply.text
    assert "Kagenohikari" in reply.text


def test_ability_ask_matches_best_druid_abilities_not_a_full_build():
    assert is_ability_ask("Best druid abilities")
    assert is_ability_ask("best wisdom druid abilities")
    assert not is_ability_ask("Best items for a dex huntress")


async def test_second_druid_ability_ask_uses_the_minted_brief(
    redis_client, anon_settings
):
    """Live Sep 16: the same 'Best druid abilities' ask burned Claude twice
    because mint required a named stat and skipped Haiku."""
    await _seed_class_scaling(redis_client, "Druid", "Sigil of the Rhino", "Wisdom")
    minted = await maybe_mint_brief(
        redis_client,
        "Best druid abilities",
        "Sigil of the Rhino leads on Wisdom Druid.",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert minted == ability_brief_key("Druid")
    reply = await _ability_reply(redis_client, "Best druid abilities")
    assert reply is not None
    assert "Sigil of the Rhino" in reply.text
    assert await _build_reply(redis_client, "Best druid abilities") is None


async def test_second_druid_ability_stream_does_not_call_claude(
    stream_app, redis_client, anon_settings
):
    client, calls = stream_app
    await _seed_class_scaling(redis_client, "Druid", "Sigil of the Rhino", "Wisdom")
    async with client as http:
        first = await http.post(
            "/chat/stream",
            json={"message": "Best druid abilities", "session_id": "s-abil-1"},
        )
        assert first.status_code == 200
        text = await _read_sse_text(first)
        second = await http.post(
            "/chat/stream",
            json={"message": "Best druid abilities", "session_id": "s-abil-2"},
        )
        assert second.status_code == 200
        again = await _read_sse_text(second)
    assert len(calls) == 1
    assert "Rift Ripper" in text
    assert "Rift Ripper" in again


async def test_best_items_for_dex_huntress_is_not_a_slot_list(
    redis_client, anon_settings
):
    reply = await _slot_reply(
        redis_client,
        "Best items for a dex huntress",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert reply is None


async def test_second_wis_kensei_is_a_cache_hit(stream_app, redis_client, anon_settings):
    client, calls = stream_app
    await _seed_class_scaling(redis_client, "Kensei", "Volcanic Sheath", "Wisdom")
    await maybe_mint_brief(
        redis_client,
        "Best items for a Wis Kensei",
        "Volcanic Sheath and Rift Rippers. [item:Volcanic Sheath] [item:Rift Ripper]",
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
    assert "Volcanic Sheath" in text


async def test_constrained_follow_up_still_streams(
    stream_app, redis_client, anon_settings
):
    client, calls = stream_app
    await _seed_class_scaling(redis_client, "Kensei", "Volcanic Sheath", "Wisdom")
    await maybe_mint_brief(
        redis_client,
        "Best items for a Wis Kensei",
        "The stored Wis Kensei brief. [item:Volcanic Sheath]",
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


def test_retry_phrasing_is_constrained():
    assert is_retry_query("Give me a different wisdom kensei")
    assert is_retry_query("try again")
    assert not is_retry_query("Best items for a Wis Kensei")


async def test_retry_drops_the_minted_build_brief(
    stream_app, redis_client, anon_settings
):
    """Found live Sep 18: Wis Kensei minted while sheaths were still
    scraping, then 'give me a different wisdom kensei' replayed it."""
    client, calls = stream_app
    await _seed_class_scaling(redis_client, "Kensei", "Volcanic Sheath", "Wisdom")
    await maybe_mint_brief(
        redis_client,
        "Best items for a Wis Kensei",
        "The stored Wis Kensei brief. [item:Volcanic Sheath]",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    key = build_brief_key("Kensei", "Wisdom")
    assert await redis_client.get(key)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={
                "message": "Give me a different wisdom kensei",
                "session_id": "s-retry",
            },
        )
        assert response.status_code == 200
        await _read_sse_text(response)
    assert await redis_client.get(key) is None
    assert calls == [anon_settings.claude_model]


async def test_does_not_mint_while_ability_store_is_empty(
    redis_client, anon_settings
):
    minted = await maybe_mint_brief(
        redis_client,
        "Best items for a Wis Kensei",
        "No ability slot token was provided. [item:Buster Katana]",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert minted is None
    assert await redis_client.get(build_brief_key("Kensei", "Wisdom")) is None


async def test_does_not_mint_when_reply_omits_the_scaling_ability(
    redis_client, anon_settings
):
    await _seed_class_scaling(redis_client, "Kensei", "Volcanic Sheath", "Wisdom")
    minted = await maybe_mint_brief(
        redis_client,
        "Best items for a Wis Kensei",
        "Sage's Wakibiki and a T7 katana. [item:Buster Katana]",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert minted is None


async def test_dungeon_guide_without_a_brief_streams_haiku(
    stream_app, anon_settings
):
    """A dungeon that is not a core fallback still streams Haiku when unwarmed.

    The Shatters is always merged into an empty index, so that ask now dumps
    the wiki page instead of calling Claude.
    """
    client, calls = stream_app
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "Guide to complete Cursed Library", "session_id": "s4"},
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


@pytest.mark.asyncio
async def test_keyper_shinies_uses_wiki_loot_not_invented_item(redis_client):
    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}the-keyper",
        json.dumps(
            {
                "title": "The Keyper",
                "url": "https://www.realmeye.com/wiki/the-keyper",
                "text": "The Keyper sells dungeon keys.",
                "drops": [{"name": "Dirk of Cronus"}],
            }
        ),
    )
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Dirk of Cronus",
            drop_locations=["The Keyper"],
            shiny_sprite_url="https://www.realmeye.com/s/a/img/wiki/shiny.png",
        ),
        3600,
    )
    reply = await try_stored_reply(
        redis_client,
        "Can the Keyper drop shinies?",
        ttl_seconds=3600,
    )
    assert reply is not None
    assert reply.kind == "source-drop"
    assert "Dirk of Cronus" in reply.text
    assert "Trickery" not in reply.text
    assert "shiny" in reply.text.lower()


@pytest.mark.asyncio
async def test_keyper_shinies_honest_miss_does_not_invent_a_name(redis_client):
    reply = await try_stored_reply(
        redis_client,
        "Can the Keyper drop shinies?",
        ttl_seconds=3600,
    )
    assert reply is not None
    assert reply.kind == "source-drop"
    assert "Trickery" not in reply.text
    assert "invent" in reply.text.lower()
    assert "[item:" not in reply.text


@pytest.mark.asyncio
async def test_nox_and_archmage_use_drops_from_not_dungeon_title(redis_client):
    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}hard-mode-shatters",
        json.dumps(
            {
                "title": "Hard Mode Shatters",
                "url": "https://www.realmeye.com/wiki/hard-mode-shatters",
                "drops": [
                    {
                        "name": "Nox Test Cloak",
                        "drops_from": "Nox the Wild Shadow",
                    },
                    {
                        "name": "Valen Test Helm",
                        "drops_from": "Valen the Unbreakable",
                    },
                ],
            }
        ),
    )
    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}the-shatters",
        json.dumps(
            {
                "title": "The Shatters",
                "url": "https://www.realmeye.com/wiki/the-shatters",
                "drops": [
                    {
                        "name": "Archmage Test Bow",
                        "drops_from": "Twilight Archmage",
                    },
                    {
                        "name": "King Test Quiver",
                        "drops_from": "The Forgotten King",
                    },
                ],
            }
        ),
    )
    reply = await try_stored_reply(
        redis_client,
        "what Nox the wild shadow and the twilight archmage drops",
        ttl_seconds=3600,
    )
    assert reply is not None
    assert reply.kind == "source-drop"
    assert "Nox Test Cloak" in reply.text
    assert "Archmage Test Bow" in reply.text
    assert "Valen Test Helm" not in reply.text
    assert "King Test Quiver" not in reply.text
    assert "Trickery" not in reply.text
    assert "invent" not in reply.text.lower()


@pytest.mark.asyncio
async def test_shiny_fungal_star_uses_ut_not_st_kunai(redis_client):
    from api.services.item_aliases import CATALOG_PREFIX

    await redis_client.set(
        f"{CATALOG_PREFIX}:all:cached",
        json.dumps(
            [
                {
                    "name": "Crystalline Kunai",
                    "slot": "ability",
                    "aliases": [],
                    "hub": "stars",
                },
                {
                    "name": "Star of Enlightenment",
                    "slot": "ability",
                    "aliases": [],
                    "hub": "stars",
                },
            ]
        ),
    )
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Crystalline Kunai",
            type="Star",
            tier="ST",
            drop_locations=["Fungal Cavern"],
        ),
        3600,
    )
    await write_cached_item(
        redis_client,
        ItemProfile(
            name="Star of Enlightenment",
            type="Star",
            tier="UT",
            shiny_sprite_url="https://example.com/enlighten-shiny.png",
            drop_locations=["Crystal Cavern"],
        ),
        3600,
    )
    reply = await try_stored_reply(
        redis_client,
        "Shiny fungal star",
        ttl_seconds=3600,
    )
    assert reply is not None
    assert reply.kind == "shiny"
    assert "Star of Enlightenment" in reply.text
    assert "Kunai" not in reply.text
    assert "fungal star" not in reply.text.lower()
    assert "[item:Star of Enlightenment]" in reply.text


@pytest.mark.asyncio
async def test_player_dps_ask_does_not_use_stored_player_lookup(
    redis_client, monkeypatch
):
    async def boom(*args, **kwargs):
        raise AssertionError("player DPS must not use the stored fame/guild lookup")

    monkeypatch.setattr(
        "api.services.stored_answers.get_or_scrape_player", boom
    )
    reply = await try_stored_reply(
        redis_client,
        "What's the DPS for Turbine's bard?",
        ttl_seconds=60,
        player_ttl_seconds=120,
    )
    assert reply is None
    reply = await try_stored_reply(
        redis_client,
        "How much potential DPS does Turbine's bard have?",
        ttl_seconds=60,
        player_ttl_seconds=120,
    )
    assert reply is None


async def test_named_comma_set_is_a_stored_loadout(redis_client, anon_settings):
    reply = await try_stored_reply(
        redis_client,
        "Rare shiny doom bow, rare shiny vile, rare shiny straitjacket, "
        "legendary shiny ring of skeletal specters",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert reply is not None
    assert reply.kind == "set"
    assert "[loadout" in reply.text
    assert "[item:" in reply.text
    assert "vile" in reply.text.lower() or "straitjacket" in reply.text.lower()


async def test_same_set_followup_reuses_character_equipment(
    redis_client, anon_settings
):
    from api.models.player import CharacterSummary, EquipmentItem, PlayerProfile
    from api.services.player_lookup import PLAYER_CACHE_PREFIX

    profile = PlayerProfile(
        username="Turbine",
        characters=[
            CharacterSummary(
                class_name="Huntress",
                equipment=[
                    EquipmentItem(name="Doom Bow", tooltip="bow"),
                    EquipmentItem(name="Quiver of Thunder", tooltip="ability"),
                    EquipmentItem(name="Cackling Straitjacket", tooltip="armor"),
                    EquipmentItem(name="The Forgotten Crown", tooltip="ring"),
                    EquipmentItem(name="Loot Bag", tooltip="bag"),
                ],
            )
        ],
    )
    await redis_client.set(
        f"{PLAYER_CACHE_PREFIX}turbine", profile.model_dump_json()
    )
    reply = await try_stored_reply(
        redis_client,
        "Same set but all divine",
        history=[
            "What would Turbine's huntress look like if the bow and armor turned divine?"
        ],
        ttl_seconds=anon_settings.wiki_ttl_seconds,
        player_ttl_seconds=anon_settings.player_ttl_seconds,
    )
    assert reply is not None
    assert "[item:Doom Bow]" in reply.text
    assert "[item:Quiver of Thunder]" in reply.text
    assert "[item:The Forgotten Crown]" in reply.text
    assert "Loot Bag" not in reply.text
    assert "divine" in reply.text.lower()


async def test_dungeon_loot_is_grouped_by_enemy(redis_client, anon_settings):
    from api.services.dungeon_guide import INDEX_CACHE_KEY, PAGE_CACHE_PREFIX

    await redis_client.set(
        INDEX_CACHE_KEY,
        json.dumps(
            [
                {
                    "title": "Ocean Trench",
                    "slug": "ocean-trench",
                    "kind": "dungeon",
                }
            ]
        ),
    )
    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}ocean-trench",
        json.dumps(
            {
                "title": "Ocean Trench",
                "url": "https://www.realmeye.com/wiki/ocean-trench",
                "drops": [
                    {
                        "name": "Coral Bow",
                        "drops_from": "Thessal the Mermaid Goddess",
                    },
                    {
                        "name": "Coral Silk Armour",
                        "drops_from": "Thessal the Mermaid Goddess",
                    },
                    {
                        "name": "Coral Ring",
                        "drops_from": "Coral Gift",
                    },
                ],
            }
        ),
    )
    reply = await try_stored_reply(
        redis_client,
        "what enemies in ocean trench drop",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert reply is not None
    assert reply.kind == "source-drop"
    assert "Thessal the Mermaid Goddess" in reply.text
    assert "Coral Gift" in reply.text
    assert "[item:Coral Bow]" in reply.text
    assert "**enemy**" not in reply.text.lower()


async def test_ocean_trench_portal_drops_from_realm_enemies(
    redis_client, anon_settings
):
    """Found live Sep 21: 'What enemy does ocean trench drop from' listed
    Thessal loot. RealmEye's Ocean Trench lead names the realm portal drops."""
    from api.services.dungeon_guide import INDEX_CACHE_KEY, PAGE_CACHE_PREFIX

    await redis_client.set(
        INDEX_CACHE_KEY,
        json.dumps(
            [
                {
                    "title": "Ocean Trench",
                    "slug": "ocean-trench",
                    "kind": "dungeon",
                }
            ]
        ),
    )
    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}ocean-trench",
        json.dumps(
            {
                "title": "Ocean Trench",
                "url": "https://www.realmeye.com/wiki/ocean-trench",
                "text": (
                    "The portal to Ocean Trench has a chance to drop from "
                    "Abyssal Squid, Sea Dragon and Ice Giant. It is also "
                    "guaranteed to drop from Hermit God and Eye of the Storm."
                ),
                "drops": [
                    {
                        "name": "Coral Bow",
                        "drops_from": "Thessal the Mermaid Goddess",
                    }
                ],
            }
        ),
    )
    reply = await try_stored_reply(
        redis_client,
        "What enemy does ocean trench drop from",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert reply is not None
    assert reply.kind == "portal-drop"
    assert "Abyssal Squid" in reply.text
    assert "Sea Dragon" in reply.text
    assert "Ice Giant" in reply.text
    assert "Hermit God" in reply.text
    assert "Eye of the Storm" in reply.text
    assert "Coral Bow" not in reply.text
    assert "Thessal" not in reply.text
    follow = await try_stored_reply(
        redis_client,
        "No I meant which enemies found in realm can drop ocean trench",
        ttl_seconds=anon_settings.wiki_ttl_seconds,
    )
    assert follow is not None
    assert "Abyssal Squid" in follow.text
    assert "Thessal" not in follow.text
