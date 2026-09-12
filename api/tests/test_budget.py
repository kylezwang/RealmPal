"""
Cost ceilings and the kill switch.

Per-identity quotas stop one abuser but not a crowd, so the day's real spend
is tracked and chat refuses new work once the budget is gone. The failure
mode that matters is the inverse of the quota tests: these check we fail
*closed* on money and *open* on infrastructure trouble.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from api.config import Settings
from api.services.budget import (
    KILL_SWITCH_KEY,
    BudgetState,
    budget_state,
    cost_ccu,
    cost_micros,
    disabled_reason,
    record_llm_failure,
    record_usage,
    today_error_key,
    today_key,
)


def _settings(**overrides) -> Settings:
    base = {
        "anthropic_api_key": "test-key-not-real",
        "jwt_secret": "test-jwt-secret",
        "pii_hash_secret": "test-pii-secret",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


# --- cost arithmetic ------------------------------------------------------


def test_cost_is_computed_from_per_million_token_prices():
    settings = _settings(
        model_input_cost_per_mtok_usd=3.0, model_output_cost_per_mtok_usd=15.0
    )
    # 1M input tokens at $3 => $3.00 => 3,000,000 micro-dollars.
    assert cost_micros(settings, 1_000_000, 0) == 3_000_000
    assert cost_micros(settings, 0, 1_000_000) == 15_000_000


def test_a_typical_message_costs_what_we_expect():
    """8k input plus 600 output at Sonnet pricing is a few cents."""
    settings = _settings()
    micros = cost_micros(settings, 8_000, 600)
    assert micros == 33_000  # $0.033
    # Foundry invoices that as CCU at $0.01 each (100 CCU = $1).
    assert cost_ccu(settings, micros) == 3.3


def test_zero_spend_is_zero_ccu():
    assert cost_ccu(_settings(), 0) == 0.0
    assert cost_ccu(_settings(foundry_ccu_usd=0.0), 33_000) == 0.0


def test_error_counter_key_is_scoped_to_provider_and_day():
    moment = datetime(2026, 9, 11, 23, 59, tzinfo=timezone.utc)
    assert today_error_key("foundry", moment) == "llm:errors:2026-09-11:foundry"
    # Don't let a caller-supplied label punch out of the key.
    assert today_error_key("foundry:../other", moment) == "llm:errors:2026-09-11:foundryother"


def test_cost_is_never_negative():
    settings = _settings()
    assert cost_micros(settings, -100, -100) == 0


def test_daily_budget_is_derived_from_the_monthly_one():
    assert _settings(monthly_cost_budget_usd=30.0).daily_cost_budget_micros == 1_000_000
    assert _settings(monthly_cost_budget_usd=20.0).daily_cost_budget_micros == 666_667


def test_zero_budget_is_representable():
    """Setting the budget to 0 should be a usable way to halt spending."""
    assert _settings(monthly_cost_budget_usd=0.0).daily_cost_budget_micros == 0


def test_spend_key_is_scoped_to_the_utc_day():
    moment = datetime(2026, 9, 11, 23, 59, tzinfo=timezone.utc)
    assert today_key(moment) == "budget:spend:2026-09-11"


# --- budget state ---------------------------------------------------------


def test_budget_state_reports_exhaustion():
    assert BudgetState(spent_micros=5, limit_micros=10).exhausted is False
    assert BudgetState(spent_micros=10, limit_micros=10).exhausted is True
    assert BudgetState(spent_micros=11, limit_micros=10).exhausted is True


def test_budget_state_converts_to_dollars():
    state = BudgetState(spent_micros=250_000, limit_micros=1_000_000)
    assert state.spent_usd == 0.25
    assert state.limit_usd == 1.0
    assert state.remaining_usd == 0.75


def test_remaining_never_goes_negative():
    state = BudgetState(spent_micros=2_000_000, limit_micros=1_000_000)
    assert state.remaining_usd == 0.0


async def test_recording_usage_accumulates(redis_client):
    settings = _settings()
    await record_usage(redis_client, settings, input_tokens=8_000, output_tokens=600)
    await record_usage(redis_client, settings, input_tokens=8_000, output_tokens=600)

    state = await budget_state(redis_client, settings)
    assert state.spent_micros == 66_000


async def test_spend_counter_expires(redis_client):
    """Yesterday's counter shouldn't live forever."""
    settings = _settings()
    await record_usage(redis_client, settings, input_tokens=1_000, output_tokens=100)
    assert await redis_client.ttl(today_key()) > 0


async def test_zero_token_calls_do_not_create_a_counter(redis_client):
    settings = _settings()
    await record_usage(redis_client, settings, input_tokens=0, output_tokens=0)
    assert (await budget_state(redis_client, settings)).spent_micros == 0


# --- gating ---------------------------------------------------------------


async def test_chat_is_available_with_budget_left(redis_client):
    assert await disabled_reason(redis_client, _settings()) is None


async def test_chat_closes_once_the_budget_is_spent(redis_client):
    settings = _settings(monthly_cost_budget_usd=20.0)
    await redis_client.set(today_key(), settings.daily_cost_budget_micros)

    reason = await disabled_reason(redis_client, settings)
    assert reason is not None
    assert "daily usage limit" in reason


async def test_partial_spend_does_not_close_chat(redis_client):
    settings = _settings(monthly_cost_budget_usd=20.0)
    await redis_client.set(today_key(), settings.daily_cost_budget_micros - 1)
    assert await disabled_reason(redis_client, settings) is None


async def test_kill_switch_closes_chat_without_a_redeploy(redis_client):
    settings = _settings()
    await redis_client.set(KILL_SWITCH_KEY, "Down for maintenance, back shortly.")

    reason = await disabled_reason(redis_client, settings)
    assert reason == "Down for maintenance, back shortly."


async def test_kill_switch_takes_precedence_over_budget(redis_client):
    """
    A deliberate shut-off shouldn't be reported as a budget problem | the
    operator needs to see the reason they set.
    """
    settings = _settings(monthly_cost_budget_usd=20.0)
    await redis_client.set(today_key(), settings.daily_cost_budget_micros)
    await redis_client.set(KILL_SWITCH_KEY, "Investigating an incident.")

    assert await disabled_reason(redis_client, settings) == "Investigating an incident."


async def test_static_switch_closes_chat(redis_client):
    reason = await disabled_reason(redis_client, _settings(chat_enabled=False))
    assert reason is not None


async def test_clearing_the_kill_switch_reopens_chat(redis_client):
    settings = _settings()
    await redis_client.set(KILL_SWITCH_KEY, "brb")
    assert await disabled_reason(redis_client, settings) is not None

    await redis_client.delete(KILL_SWITCH_KEY)
    assert await disabled_reason(redis_client, settings) is None


# --- failure modes --------------------------------------------------------


async def test_redis_failure_does_not_take_chat_down(monkeypatch, redis_client):
    """
    Failing closed on a Redis blip would turn a cache problem into an
    outage. Per-identity quotas still apply in that window.
    """
    settings = _settings()

    async def boom(*args, **kwargs):
        raise ConnectionError("redis is unreachable")

    monkeypatch.setattr(redis_client, "get", boom)
    assert await disabled_reason(redis_client, settings) is None


async def test_corrupt_spend_counter_reads_as_zero(redis_client):
    settings = _settings()
    await redis_client.set(today_key(), "not-a-number")
    assert (await budget_state(redis_client, settings)).spent_micros == 0


async def test_recording_survives_a_redis_failure(monkeypatch, redis_client):
    settings = _settings()

    async def boom(*args, **kwargs):
        raise ConnectionError("redis is unreachable")

    monkeypatch.setattr(redis_client, "incrby", boom)
    # Should report the call's own cost rather than raising into the stream.
    assert await record_usage(
        redis_client, settings, input_tokens=1_000, output_tokens=100
    ) == cost_micros(settings, 1_000, 100)


async def test_stream_failures_are_counted_per_provider(redis_client):
    settings = _settings()
    await record_llm_failure(redis_client, settings, provider="foundry")
    await record_llm_failure(redis_client, settings, provider="foundry")
    assert int(await redis_client.get(today_error_key("foundry"))) == 2
    assert await redis_client.get(today_error_key("anthropic")) is None


async def test_recording_a_failure_survives_a_redis_blip(monkeypatch, redis_client):
    settings = _settings()

    async def boom(*args, **kwargs):
        raise ConnectionError("redis is unreachable")

    monkeypatch.setattr(redis_client, "incr", boom)
    await record_llm_failure(redis_client, settings, provider="foundry")


# --- request size caps ----------------------------------------------------


def test_oversized_message_is_rejected():
    from pydantic import ValidationError

    from api.models.chat import MAX_MESSAGE_CHARS, ChatRequest

    ChatRequest(message="a" * MAX_MESSAGE_CHARS)
    with pytest.raises(ValidationError):
        ChatRequest(message="a" * (MAX_MESSAGE_CHARS + 1))


def test_oversized_history_is_rejected():
    from pydantic import ValidationError

    from api.models.chat import MAX_HISTORY_MESSAGES, ChatMessage, ChatRequest

    turn = ChatMessage(role="user", content="hi")
    ChatRequest(message="hi", history=[turn] * MAX_HISTORY_MESSAGES)
    with pytest.raises(ValidationError):
        ChatRequest(message="hi", history=[turn] * (MAX_HISTORY_MESSAGES + 1))


def test_response_length_is_bounded():
    """Caps the worst case cost of any single answer."""
    assert _settings().max_response_tokens <= 8192
