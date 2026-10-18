"""Jev disambiguates gated turns and never overrides a weak score."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from api.config import get_settings
from api.dependencies import get_qdrant, get_redis
from api.main import create_app
from api.models.item import ItemProfile
from api.models.player import PlayerProfile
from api.services.fuzzy_match import _ENGLISH_FILLER
from api.services.jev_route import (
    ABOUT_TEXT,
    JevDecision,
    OFF_TOPIC_TEXT,
    CLASS_CLARIFY_TEXT,
    canned_reply,
    accepted_nickname,
    clarify_reply,
    disambiguate,
    forced_slots,
    gate_reason,
    player_candidates,
    reply_kind,
    upgrade_model,
    verify_stored,
)
from api.services.rate_limit import peek, quota_for
from api.services.realmshark import retrieve_build_knowledge
from api.services.stored_answers import try_stored_reply
from api.services.wiki_scaling import write_cached_item
from api.tests.test_dps_specialist import _seed_turbine_bard
from api.tests.test_stored_answers import (
    CALLER,
    _FakeClient,
    _read_sse_chunks,
    _read_sse_text,
)

from .conftest import build_request


def _settings(**kwargs):
    base = dict(
        jev_mode="on",
        typesafe_api_key="test-key",
        jev_model="jev-1.13.0",
        jev_timeout_seconds=0.8,
        jev_cache_seconds=86400,
        claude_model="claude-sonnet-4-6",
        claude_light_model="claude-haiku-4-5",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _answer(
    intent: str,
    confidence: float,
    probabilities: dict,
    *,
    field: str = "none",
    field_confidence: float = 0.9,
    prior: float = 0.2,
    player: str | None = None,
    player_p: float = 0.0,
    no_request: float | None = None,
    stored_fits: float | None = None,
):
    answers = {
        "intent": {
            "choice": intent,
            "confidence": confidence,
            "probabilities": probabilities,
        },
        "continues_prior": {"noul": prior},
        "continue_field": {
            "choice": field,
            "confidence": field_confidence,
            "probabilities": {field: field_confidence},
        },
        "needs_sonnet": {"noul": 0.1},
    }
    if player is not None:
        answers["player_name"] = {
            "choice": player,
            "confidence": player_p,
            "probabilities": {player: player_p, "none": 1 - player_p},
        }
    if no_request is not None:
        answers["no_request"] = {"noul": no_request}
    if stored_fits is not None:
        answers["stored_fits"] = {"noul": stored_fits}
    return {"model": "jev-1.13.0", "answers": answers}


class _Response:
    def __init__(self, status: int, body):
        self.status_code = status
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _Client:
    posts = 0
    body = None
    status = 200
    error = None
    payload = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        type(self).posts += 1
        type(self).payload = json
        assert headers["Authorization"] == "Bearer test-key"
        assert json["model"] == "jev-1.13.0"
        if self.error:
            raise self.error
        return _Response(self.status, self.body)


class _MemoryRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


def _patch_http(monkeypatch):
    _Client.posts = 0
    _Client.error = None
    _Client.status = 200
    monkeypatch.setattr("api.services.jev_route._http_client", lambda timeout: _Client())


def test_gate_skips_clear_hits():
    assert gate_reason("best attack bard", []) == "clear"
    assert (
        gate_reason(
            "nvm, show me how to do moonlight village",
            ["best attack bard build"],
        )
        == "clear"
    )
    assert (
        gate_reason(
            "Sorry I mean Mini Royal Crossbowman Archer",
            ["What does Vampire Slayer Archer look like with Large Crown Cloth?"],
        )
        == "clear"
    )
    assert gate_reason("best druid abilities", []) == "clear"


def test_gate_conflict():
    # "Is shiny forging possible?" is forge + shiny, and enchant does not
    # match the word forging, so the forge specialist already owns it.
    assert gate_reason("Is shiny forging possible?", []) == "clear"
    assert gate_reason("can I forge an enchantment", []) == "conflict"
    assert gate_reason("What enemy does ocean trench drop from?", []) == "conflict"


def test_gate_followup_without_thin_words():
    skin_prior = ["What does Vampire Slayer Archer look like with Large Crown Cloth?"]
    assert gate_reason("now try it on a wizard", skin_prior) == "followup"
    assert gate_reason("and his priest?", ["What's the DPS for Turbine's bard?"]) == "followup"


def test_gate_standalone():
    for message in (
        "What is a steroid",
        "Who made this site",
        "Who is samridelli",
        "how much damage does my staff do",
    ):
        assert gate_reason(message, []) == "standalone"


def test_gate_skips_constrained_and_attachments():
    assert gate_reason("best attack bard no st", []) == "constrained"
    assert gate_reason("What is a steroid", [], has_attachment=True) == "attachment"
    assert gate_reason("   ", []) == "empty"


def test_reply_kind():
    assert reply_kind("see [skin:Archer|x||]") == "skin"
    assert reply_kind("here [loadout shiny]") == "set"
    assert reply_kind("DPS is 1234 on that set") == "dps"
    assert reply_kind("[item:A] [item:B] [item:C]") == "build"
    assert reply_kind("[item:A] and [item:B]") == "item"
    assert reply_kind("hello") == "none"


def test_player_candidates():
    assert "samridelli" in [name.lower() for name in player_candidates("Who is samridelli")]
    names = [name.lower() for name in player_candidates("What is a steroid")]
    assert "what" not in names
    assert "is" not in names
    if "steroid" in _ENGLISH_FILLER:
        assert "steroid" not in names
    else:
        assert "steroid" in names


def test_off_topic_on_conflict_gate_is_ignored():
    decision = JevDecision(
        called=True,
        gate="conflict",
        intent="off_topic",
        intent_confidence=0.95,
        probabilities={"off_topic": 0.99},
    )
    assert canned_reply(decision) is None


def test_forced_build_needs_a_class():
    decision = JevDecision(
        called=True,
        reason="ok",
        intent="build",
        intent_confidence=0.9,
        continue_field="class_stat",
        continue_field_confidence=0.9,
    )
    assert forced_slots(decision, "what about wizard") is None
    slots, depth = forced_slots(decision, "what about wizard", class_name="Wizard")
    assert depth == "brief"
    assert "weapon" in slots and "ring" in slots


def test_forced_keeps_player_and_dungeon_extras():
    decision = JevDecision(
        called=True, reason="ok", intent="skin", intent_confidence=0.9
    )
    slots, depth = forced_slots(
        decision,
        "now try it on a wizard",
        player_ign="Turbine",
        dungeon_name="The Nest",
    )
    assert depth == "deep"
    assert slots[0] == "skin"
    assert "player" in slots
    assert "dungeon" in slots


def test_needs_sonnet_upgrades_haiku_and_does_not_downgrade():
    yes = JevDecision(called=True, reason="ok", needs_sonnet=0.9)
    no = JevDecision(called=True, reason="ok", needs_sonnet=0.1)
    assert upgrade_model("haiku", yes, "sonnet", "haiku") == "sonnet"
    assert upgrade_model("sonnet", yes, "sonnet", "haiku") == "sonnet"
    assert upgrade_model("haiku", no, "sonnet", "haiku") == "haiku"


@pytest.mark.asyncio
async def test_cache_hit_skips_http(monkeypatch):
    _patch_http(monkeypatch)
    _Client.body = _answer("off_topic", 0.95, {"off_topic": 0.95})
    redis = _MemoryRedis()
    first = await disambiguate(redis, _settings(), "What is a steroid", use_cache=True)
    second = await disambiguate(redis, _settings(), "What is a steroid", use_cache=True)
    assert first.called and second.called
    assert second.from_cache
    assert _Client.posts == 1


@pytest.mark.asyncio
async def test_http_429_falls_back(monkeypatch):
    _patch_http(monkeypatch)
    _Client.status = 429
    _Client.body = {}
    decision = await disambiguate(None, _settings(), "What is a steroid", use_cache=False)
    assert decision.called is False
    assert decision.reason == "error"


@pytest.mark.asyncio
async def test_bad_json_falls_back(monkeypatch):
    _patch_http(monkeypatch)
    _Client.body = ValueError("bad")
    decision = await disambiguate(None, _settings(), "What is a steroid", use_cache=False)
    assert decision.called is False


@pytest.mark.asyncio
async def test_dps_continue_recovers_prior_ign(redis_client):
    await _seed_turbine_bard(redis_client)
    decision = JevDecision(
        called=True,
        reason="ok",
        gate="followup",
        intent="dps",
        intent_confidence=0.9,
        continue_field="dps",
        continue_field_confidence=0.9,
        probabilities={"dps": 0.9},
    )
    text = await retrieve_build_knowledge(
        redis_client,
        "and his priest?",
        ttl_seconds=60,
        player_ttl_seconds=120,
        history=["What's the DPS for Turbine's bard?"],
        jev=decision,
    )
    assert "Turbine" in text


def _enable(anon_settings):
    anon_settings.jev_mode = "on"
    anon_settings.typesafe_api_key = "test-key"


def _stream_client(redis_client, anon_settings, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    calls: list[str] = []
    monkeypatch.setattr(
        "api.routers.chat.build_chat_client",
        lambda _settings: _FakeClient(calls),
    )
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_settings] = lambda: anon_settings
    app.dependency_overrides[get_qdrant] = lambda: object()
    transport = httpx.ASGITransport(app=app, client=CALLER)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, calls


@pytest.mark.asyncio
async def test_off_topic_canned_reply_skips_claude_and_quota(
    redis_client, anon_settings, monkeypatch
):
    _enable(anon_settings)
    _patch_http(monkeypatch)
    _Client.body = _answer("off_topic", 0.95, {"off_topic": 0.95, "other": 0.05})
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "What is a steroid", "session_id": "jev-off"},
        )
        text = await _read_sse_text(response)
    assert response.status_code == 200
    assert OFF_TOPIC_TEXT in text
    assert calls == []
    quota = quota_for(None, build_request(peer=CALLER[0]), anon_settings)
    assert await peek(redis_client, quota) == 0


@pytest.mark.asyncio
async def test_shadow_mode_never_changes_slots_or_replies(
    redis_client, anon_settings, monkeypatch
):
    anon_settings.jev_mode = "shadow"
    anon_settings.typesafe_api_key = "test-key"
    _patch_http(monkeypatch)
    _Client.body = _answer("off_topic", 0.99, {"off_topic": 0.99})
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "What is a steroid", "session_id": "jev-shadow"},
        )
        text = await _read_sse_text(response)
    assert OFF_TOPIC_TEXT not in text
    assert calls


@pytest.mark.asyncio
async def test_player_name_runs_stored_lookup(
    redis_client, anon_settings, monkeypatch
):
    _enable(anon_settings)
    _patch_http(monkeypatch)
    _Client.body = _answer(
        "player",
        0.9,
        {"player": 0.9},
        player="samridelli",
        player_p=0.9,
    )

    async def fake_scrape(_redis, username, *, ttl_seconds):
        return PlayerProfile(username=username, fame=10, account_fame=20)

    monkeypatch.setattr(
        "api.services.stored_answers.get_or_scrape_player", fake_scrape
    )
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "Who is samridelli", "session_id": "jev-player"},
        )
        chunks = await _read_sse_chunks(response)
        text = "".join(chunk.get("content") or "" for chunk in chunks)
    assert calls == []
    assert "Fame" in text
    assert any(chunk.get("player_ign") == "samridelli" for chunk in chunks)


@pytest.mark.asyncio
async def test_used_history_flag(redis_client, monkeypatch):
    async def fake_scrape(_redis, username, *, ttl_seconds):
        return PlayerProfile(username=username, fame=10, account_fame=20)

    monkeypatch.setattr(
        "api.services.stored_answers.get_or_scrape_player", fake_scrape
    )
    followed = await try_stored_reply(
        redis_client,
        "what pets are best for priest",
        history=["Look up player Turbine"],
        ttl_seconds=60,
        player_ttl_seconds=60,
    )
    assert followed is not None
    assert followed.kind == "player"
    assert followed.used_history is True
    assert followed.player_ign == "Turbine"
    direct = await try_stored_reply(
        redis_client,
        "Look up player Turbine",
        history=[],
        ttl_seconds=60,
        player_ttl_seconds=60,
    )
    assert direct is not None
    assert direct.used_history is False
    assert direct.player_ign == "Turbine"


@pytest.mark.asyncio
async def test_stored_followup_dropped_when_jev_disagrees(
    redis_client, anon_settings, monkeypatch
):
    _enable(anon_settings)
    _patch_http(monkeypatch)
    _Client.body = _answer("other", 0.4, {"other": 0.7, "player": 0.1})

    async def fake_scrape(_redis, username, *, ttl_seconds):
        return PlayerProfile(username=username, fame=10, account_fame=20)

    monkeypatch.setattr(
        "api.services.stored_answers.get_or_scrape_player", fake_scrape
    )
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={
                "message": "what pets are best for priest",
                "session_id": "jev-drop",
                "history": [
                    {"role": "user", "content": "Look up player Turbine"},
                    {"role": "assistant", "content": "Turbine, fame 10."},
                ],
            },
        )
        text = await _read_sse_text(response)
    assert calls
    assert "Fame" not in text


@pytest.mark.asyncio
async def test_stored_followup_kept_when_jev_agrees(
    redis_client, anon_settings, monkeypatch
):
    _enable(anon_settings)
    _patch_http(monkeypatch)
    _Client.body = _answer("dungeon", 0.9, {"dungeon": 0.9, "other": 0.1})

    async def fake_guide(_redis, message, history, ttl_seconds):
        from api.services.stored_answers import StoredReply

        return StoredReply(text="NEST WALKTHROUGH", kind="guide")

    monkeypatch.setattr("api.services.stored_answers._guide_reply", fake_guide)
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={
                "message": "what drops from the boss",
                "session_id": "jev-keep",
                "history": [
                    {"role": "user", "content": "Guide to complete The Nest"},
                    {"role": "assistant", "content": "Clear the boss."},
                ],
            },
        )
        text = await _read_sse_text(response)
    assert "NEST WALKTHROUGH" in text
    assert calls == []


@pytest.mark.asyncio
async def test_stored_followup_kept_on_timeout(
    redis_client, anon_settings, monkeypatch
):
    _enable(anon_settings)
    _patch_http(monkeypatch)
    _Client.error = httpx.TimeoutException("slow")

    async def fake_scrape(_redis, username, *, ttl_seconds):
        return PlayerProfile(username=username, fame=11, account_fame=20)

    monkeypatch.setattr(
        "api.services.stored_answers.get_or_scrape_player", fake_scrape
    )
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={
                "message": "what pets are best for priest",
                "session_id": "jev-timeout",
                "history": [
                    {"role": "user", "content": "Look up player Turbine"},
                    {"role": "assistant", "content": "Turbine."},
                ],
            },
        )
        text = await _read_sse_text(response)
    assert calls == []
    assert "Fame" in text


@pytest.mark.asyncio
async def test_self_contained_stored_hit_never_calls_jev(
    redis_client, anon_settings, monkeypatch
):
    _enable(anon_settings)

    class _Boom:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Jev was called for a self-contained stored hit")

    monkeypatch.setattr(
        "api.services.jev_route._http_client",
        lambda timeout: (_ for _ in ()).throw(AssertionError("Jev was called")),
    )
    await write_cached_item(
        redis_client,
        ItemProfile(name="The Triangle", drop_locations=["Snake Pit"]),
        anon_settings.wiki_ttl_seconds,
        "triangle",
    )
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "where does the triangle drop", "session_id": "jev-drop-item"},
        )
        text = await _read_sse_text(response)
    assert calls == []
    assert "Snake Pit" in text


@pytest.mark.asyncio
async def test_skin_miss_goes_to_skin_store(
    redis_client, anon_settings, monkeypatch
):
    _enable(anon_settings)
    _patch_http(monkeypatch)
    _Client.body = _answer(
        "skin", 0.9, {"skin": 0.9}, field="skin", field_confidence=0.9, prior=0.9
    )

    async def fake_compose(_redis, message, *, ttl_seconds, history=None):
        return "[skin:Wizard|Vampire Slayer||]"

    monkeypatch.setattr(
        "api.services.stored_answers.compose_skin_stored_reply", fake_compose
    )
    monkeypatch.setattr("api.routers.chat.compose_skin_stored_reply", fake_compose)
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={
                "message": "now try it on a wizard",
                "session_id": "jev-skin",
                "history": [
                    {
                        "role": "user",
                        "content": "What does Vampire Slayer Archer look like with Large Crown Cloth?",
                    },
                    {"role": "assistant", "content": "[skin:Archer|Vampire Slayer|Large Crown Cloth|]"},
                ],
            },
        )
        text = await _read_sse_text(response)
    assert "[skin:" in text
    assert calls == []


def test_short_noise_gets_canned_reply():
    decision = JevDecision(
        called=True,
        gate="standalone",
        intent="other",
        probabilities={"other": 0.49, "off_topic": 0.46},
        no_request=0.96,
    )
    assert canned_reply(decision, "Hu") == OFF_TOPIC_TEXT


def test_short_topic_is_not_canned():
    decision = JevDecision(
        called=True,
        gate="standalone",
        intent="off_topic",
        probabilities={"off_topic": 0.52, "other": 0.40},
        no_request=0.03,
    )
    assert canned_reply(decision, "trading tips") is None


def test_short_rule_needs_a_short_message():
    decision = JevDecision(
        called=True,
        gate="standalone",
        intent="other",
        probabilities={"other": 0.5, "off_topic": 0.45},
        no_request=0.96,
    )
    assert canned_reply(decision, "what should I farm after the nest today") is None


def test_player_rule_uses_player_probability():
    from api.services.jev_route import confident_player_name

    decision = JevDecision(
        called=True,
        gate="standalone",
        intent="player",
        intent_confidence=0.70,
        probabilities={"player": 0.72},
        player_name="Nightmvre",
        player_name_p=0.78,
    )
    assert confident_player_name(decision) == "Nightmvre"
    low_name = JevDecision(
        called=True,
        gate="standalone",
        intent="player",
        intent_confidence=0.78,
        probabilities={"player": 0.79},
        player_name="Nightmvre",
        player_name_p=0.65,
    )
    assert confident_player_name(low_name) == "Nightmvre"
    too_low = JevDecision(
        called=True,
        gate="standalone",
        intent="player",
        intent_confidence=0.78,
        probabilities={"player": 0.79},
        player_name="Nightmvre",
        player_name_p=0.64,
    )
    assert confident_player_name(too_low) is None
    weak = JevDecision(
        called=True,
        gate="standalone",
        intent="player",
        intent_confidence=0.52,
        probabilities={"player": 0.55},
        player_name="oryx",
        player_name_p=0.97,
    )
    assert confident_player_name(weak) is None


def test_stored_fits_decides_keep():
    from api.services.jev_route import keep_stored

    fits = JevDecision(called=True, gate="stored", probabilities={"player": 0.1}, stored_fits=0.9)
    misses = JevDecision(called=True, gate="stored", probabilities={"player": 0.9}, stored_fits=0.2)
    assert keep_stored(fits, "player") is True
    assert keep_stored(misses, "player") is False


def test_cache_key_changes_with_questions():
    from api.services.jev_route import _cache_key

    state = {"current_message": "x", "previous_user_message": "", "previous_reply_kind": "none"}
    first = _cache_key("jev-1.13.0", state, "stored", {"a": 1})
    second = _cache_key("jev-1.13.0", state, "stored", {"a": 2})
    assert first != second


def test_build_and_dps_continuations_keep_inheritance():
    build = JevDecision(
        called=True,
        intent="build",
        intent_confidence=0.97,
        continue_field="dps",
        continue_field_confidence=0.9,
    )
    dps = JevDecision(
        called=True,
        intent="dps",
        intent_confidence=0.9,
        continue_field="dps",
        continue_field_confidence=0.9,
    )
    skin = JevDecision(
        called=True,
        intent="skin",
        intent_confidence=0.9,
        continue_field="skin",
        continue_field_confidence=0.9,
    )
    assert build.block_class_stat_inherit is False
    assert dps.block_class_stat_inherit is False
    assert skin.block_class_stat_inherit is True


@pytest.mark.asyncio
async def test_disambiguate_never_raises(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("detector broke")

    monkeypatch.setattr("api.services.jev_route.gate_reason", boom)
    decision = await disambiguate(None, _settings(), "What is a steroid", use_cache=False)
    assert decision.called is False
    assert decision.reason == "error"


@pytest.mark.asyncio
async def test_game_name_blocks_player_lookup(redis_client):
    from api.services.dungeon_guide import PAGE_CACHE_PREFIX
    from api.services.jev_route import is_game_name

    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}ocean-trench",
        json.dumps(
            {
                "url": "https://www.realmeye.com/wiki/ocean-trench",
                "drops": [
                    {"name": "Coral Bow", "drops_from": "Thessal the Mermaid Goddess"}
                ],
            }
        ),
    )
    assert await is_game_name(redis_client, "thessal") is True
    assert await is_game_name(redis_client, "Nightmvre") is False


@pytest.mark.asyncio
async def test_verify_stored_is_callable(monkeypatch):
    _patch_http(monkeypatch)
    _Client.body = _answer("player", 0.2, {"player": 0.1, "other": 0.8})
    decision = await verify_stored(
        None,
        _settings(),
        "what pets are best for priest",
        ["Look up player Turbine"],
        "player",
        stored_kind="player",
        use_cache=False,
    )
    assert decision.called
    assert decision.gate == "stored"


def _dps(message_intent="dps", confidence=0.9, **probs):
    probabilities = {"dps": confidence, "other": 0.05}
    probabilities.update(probs)
    return JevDecision(
        called=True,
        gate="standalone",
        intent=message_intent,
        intent_confidence=confidence,
        probabilities=probabilities,
    )


THESSAL = [
    {
        "name": "Thessal the Mermaid Goddess",
        "kind": "boss",
        "where": "Ocean Trench",
        "matched": "thessal",
    }
]


def test_class_question_for_a_staff_with_no_class():
    text = clarify_reply(_dps("item_info", 0.4, item_info=0.4, dps=0.3), "how much damage does my staff do")
    assert text == CLASS_CLARIFY_TEXT
    rings = clarify_reply(
        _dps("slot", 0.7, slot=0.7),
        "what rings should i use",
        history=["Guide to complete The Nest"],
    )
    assert rings == CLASS_CLARIFY_TEXT


def test_class_question_stays_quiet():
    wizard = _dps()
    assert clarify_reply(wizard, "best attack wizard") is None
    assert clarify_reply(wizard, "how much damage does my staff do", history=["best attack wizard"]) is None
    assert clarify_reply(wizard, "what rings drop in the nest") is None
    assert clarify_reply(wizard, "how much damage does oryx do") is None
    assert (
        clarify_reply(
            wizard,
            "how much damage does my staff do",
            prior_reply_kind="clarify",
        )
        is None
    )
    assert reply_kind(CLASS_CLARIFY_TEXT) == "clarify"


def test_boss_or_player_question_needs_both_signals():
    player = JevDecision(
        called=True,
        gate="standalone",
        intent="player",
        intent_confidence=0.9,
        probabilities={"player": 0.74},
        player_name="Thessal",
        player_name_p=0.8,
    )
    assert "boss Thessal" in clarify_reply(player, "who is thessal", terms=THESSAL)
    quiet = JevDecision(
        called=True,
        gate="standalone",
        intent="dungeon",
        intent_confidence=0.9,
        probabilities={"dungeon": 0.9, "player": 0.1},
    )
    assert clarify_reply(quiet, "what drops from thessal", terms=THESSAL) is None
    sure = JevDecision(
        called=True,
        gate="standalone",
        intent="other",
        intent_confidence=0.88,
        probabilities={"other": 0.88, "player": 0.09},
        player_name="none",
        player_name_p=0.99,
    )
    assert (
        clarify_reply(sure, "who is thessal", terms=THESSAL)
        == "Thessal the Mermaid Goddess is a boss in Ocean Trench."
    )
    night = JevDecision(
        called=True,
        gate="standalone",
        intent="player",
        intent_confidence=0.9,
        probabilities={"player": 0.9},
        player_name="Nightmvre",
        player_name_p=0.8,
    )
    assert clarify_reply(night, "who is Nightmvre", terms=[]) is None


def test_what_is_unknown_nickname_asks_instead_of_guessing():
    item = JevDecision(
        called=True,
        gate="stored",
        intent="item_info",
        intent_confidence=0.88,
        probabilities={"item_info": 0.88, "other": 0.05},
    )
    assert clarify_reply(item, "What is jugg?") == "Do you mean Helm of the Juggernaut?"
    assert clarify_reply(item, "What is blorf?") == (
        'I don\'t know "blorf". Which item, boss, or dungeon do you mean?'
    )
    assert clarify_reply(item, "What is a white bag?") is None
    assert clarify_reply(item, "What is fame?") is None
    assert clarify_reply(item, "What is Thessal?", terms=THESSAL) is None
    player = JevDecision(
        called=True,
        gate="standalone",
        intent="player",
        intent_confidence=0.9,
        probabilities={"player": 0.9},
        player_name="Nutz",
        player_name_p=0.9,
    )
    assert clarify_reply(player, "What is Nutz?") is None
    assert reply_kind("Do you mean Helm of the Juggernaut?") == "clarify"
    assert reply_kind('I don\'t know "blorf". Which item, boss, or dungeon do you mean?') == "clarify"
    assert clarify_reply(item, "What is jugg?", prior_reply_kind="clarify") is None
    assert accepted_nickname("yes", "Do you mean Helm of the Juggernaut?") == (
        "Helm of the Juggernaut\n\n[item:Helm of the Juggernaut]"
    )
    assert accepted_nickname(
        "yes",
        "Do you mean the boss Thessal the Mermaid Goddess, or a player named Thessal?",
    ) is None
    assert accepted_nickname("no", "Do you mean Helm of the Juggernaut?") is None


def _gap(kind: str, confidence: float = 0.85, intent: str = "item_info") -> JevDecision:
    return JevDecision(
        called=True,
        gate="followup",
        intent=intent,
        intent_confidence=0.88,
        probabilities={intent: 0.88, "other": 0.05},
        missing=kind,
        missing_confidence=confidence,
    )


def test_missing_gap_asks_only_when_the_catalog_agrees():
    from api.services.jev_route import DUNGEON_CLARIFY_TEXT, ITEM_CLARIFY_TEXT, PLAYER_CLARIFY_TEXT, _questions_for

    item = _gap("item")
    assert clarify_reply(item, "is jugg good on a new warrior?") == (
        "Do you mean Helm of the Juggernaut?"
    )
    assert clarify_reply(item, "is blorf worth using?") == (
        'I don\'t know "blorf". Which item do you mean?'
    )
    assert clarify_reply(item, "is cbow or lbow better?") is None
    assert clarify_reply(item, "what is a white bag?") is None
    assert clarify_reply(item, "What is Thessal?", terms=THESSAL) is None
    assert clarify_reply(item, "how do I complete it?") is None
    weak = _gap("item", 0.4)
    assert clarify_reply(weak, "is jugg good?") is None

    klass = _gap("class", intent="dps")
    assert clarify_reply(klass, "how much damage does this do") == CLASS_CLARIFY_TEXT
    assert clarify_reply(klass, "best attack wizard") is None
    nest = [
        {"name": "The Nest", "kind": "dungeon", "matched": "nest", "where": ""},
    ]
    assert clarify_reply(klass, "what rings drop in the nest", terms=nest) is None

    dungeon = _gap("dungeon", intent="dungeon")
    assert clarify_reply(dungeon, "how do I complete it") == DUNGEON_CLARIFY_TEXT
    assert clarify_reply(dungeon, "how do I complete the nest", terms=nest) is None

    player = _gap("player", intent="player")
    assert clarify_reply(player, "what gear does he have") == PLAYER_CLARIFY_TEXT
    assert clarify_reply(player, "Look up player Turbine") is None

    nothing = _gap("nothing")
    assert clarify_reply(nothing, "is jugg good?") is None
    assert reply_kind(DUNGEON_CLARIFY_TEXT) == "clarify"
    assert reply_kind(PLAYER_CLARIFY_TEXT) == "clarify"
    assert reply_kind(ITEM_CLARIFY_TEXT) == "clarify"

    for gate in ("standalone", "followup", "conflict", "stored"):
        questions = _questions_for(gate, "is jugg good on a warrior?", "set")
        assert set(questions["missing"]["criteria"]) == {
            "nothing",
            "class",
            "item",
            "dungeon",
            "player",
        }


def test_close_intents_ask_only_on_a_real_tie():
    tie = JevDecision(
        called=True,
        gate="standalone",
        intent="dps",
        intent_confidence=0.48,
        probabilities={"dps": 0.48, "item_info": 0.40},
    )
    text = clarify_reply(tie, "is that staff any good")
    assert text is not None
    assert text.startswith("Are you asking about")
    winner = JevDecision(
        called=True,
        gate="standalone",
        intent="dps",
        intent_confidence=0.9,
        probabilities={"dps": 0.9, "item_info": 0.8},
    )
    assert clarify_reply(winner, "is that staff any good") is None
    wide = JevDecision(
        called=True,
        gate="standalone",
        intent="dps",
        intent_confidence=0.7,
        probabilities={"dps": 0.7, "item_info": 0.2},
    )
    assert clarify_reply(wide, "is that staff any good") is None


@pytest.mark.asyncio
async def test_known_terms_are_sent_with_the_jev_request(monkeypatch):
    _patch_http(monkeypatch)
    _Client.body = _answer("player", 0.4, {"player": 0.4, "dungeon": 0.4})
    await disambiguate(
        None,
        _settings(),
        "who is thessal",
        use_cache=False,
        known_terms="Thessal the Mermaid Goddess (boss, Ocean Trench)",
    )
    assert _Client.payload["state"]["known_game_terms"].startswith("Thessal")


@pytest.mark.asyncio
async def test_what_is_jugg_asks_and_skips_claude(
    redis_client, anon_settings, monkeypatch
):
    _enable(anon_settings)
    _patch_http(monkeypatch)
    _Client.body = _answer("item_info", 0.88, {"item_info": 0.88, "other": 0.05})
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "What is jugg?", "session_id": "jev-jugg"},
        )
        text = await _read_sse_text(response)
    assert text == "Do you mean Helm of the Juggernaut?"
    assert calls == []
    quota = quota_for(None, build_request(peer=CALLER[0]), anon_settings)
    assert await peek(redis_client, quota) == 0


@pytest.mark.asyncio
async def test_yes_after_nickname_skips_claude(
    redis_client, anon_settings, monkeypatch
):
    _enable(anon_settings)
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={
                "message": "yes",
                "session_id": "jev-yes",
                "history": [
                    {"role": "user", "content": "What is jugg?"},
                    {
                        "role": "assistant",
                        "content": "Do you mean Helm of the Juggernaut?",
                    },
                ],
            },
        )
        text = await _read_sse_text(response)
    assert "[item:Helm of the Juggernaut]" in text
    assert calls == []


@pytest.mark.asyncio
async def test_class_clarify_skips_claude_and_quota(
    redis_client, anon_settings, monkeypatch
):
    _enable(anon_settings)
    _patch_http(monkeypatch)
    _Client.body = _answer("item_info", 0.4, {"item_info": 0.4, "dps": 0.3, "other": 0.2})
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "how much damage does my staff do", "session_id": "jev-class"},
        )
        text = await _read_sse_text(response)
    assert CLASS_CLARIFY_TEXT in text
    assert calls == []
    quota = quota_for(None, build_request(peer=CALLER[0]), anon_settings)
    assert await peek(redis_client, quota) == 0


@pytest.mark.asyncio
async def test_boss_clarify_does_not_scrape_a_player(
    redis_client, anon_settings, monkeypatch
):
    from api.services.game_names import GAME_NAMES_KEY

    _enable(anon_settings)
    _patch_http(monkeypatch)
    _Client.body = _answer(
        "player",
        0.9,
        {"player": 0.74},
        player="Thessal",
        player_p=0.8,
    )
    await redis_client.set(
        GAME_NAMES_KEY,
        json.dumps(
            {
                "thessal": {
                    "name": "Thessal the Mermaid Goddess",
                    "kind": "boss",
                    "where": "Ocean Trench",
                }
            }
        ),
    )
    scrapes = {"n": 0}

    async def fake_scrape(_redis, username, *, ttl_seconds):
        scrapes["n"] += 1
        return PlayerProfile(username=username)

    monkeypatch.setattr("api.services.stored_answers.get_or_scrape_player", fake_scrape)
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={"message": "who is thessal", "session_id": "jev-boss"},
        )
        text = await _read_sse_text(response)
    assert "Do you mean the boss Thessal" in text
    assert scrapes["n"] == 0
    assert calls == []


@pytest.mark.asyncio
async def test_second_clarify_goes_to_claude(
    redis_client, anon_settings, monkeypatch
):
    _enable(anon_settings)
    _patch_http(monkeypatch)
    _Client.body = _answer("item_info", 0.4, {"item_info": 0.4, "dps": 0.3})
    client, calls = _stream_client(redis_client, anon_settings, monkeypatch)
    async with client as http:
        response = await http.post(
            "/chat/stream",
            json={
                "message": "how much damage does my staff do",
                "session_id": "jev-again",
                "history": [
                    {"role": "user", "content": "how much damage does my staff do"},
                    {"role": "assistant", "content": CLASS_CLARIFY_TEXT},
                ],
            },
        )
        text = await _read_sse_text(response)
    assert CLASS_CLARIFY_TEXT not in text
    assert calls


@pytest.mark.asyncio
async def test_game_name_index_is_authority_when_present(redis_client):
    from api.services.dungeon_guide import PAGE_CACHE_PREFIX
    from api.services.game_names import GAME_NAMES_KEY
    from api.services.jev_route import is_game_name

    await redis_client.set(
        f"{PAGE_CACHE_PREFIX}ocean-trench",
        json.dumps(
            {
                "drops": [
                    {"name": "Coral Bow", "drops_from": "Thessal the Mermaid Goddess"}
                ]
            }
        ),
    )
    await redis_client.set(
        GAME_NAMES_KEY,
        json.dumps({"shatters": {"name": "The Shatters", "kind": "dungeon", "where": ""}}),
    )
    assert await is_game_name(redis_client, "shatters") is True
    assert await is_game_name(redis_client, "thessal") is False
    assert await is_game_name(redis_client, "Nightmvre") is False
