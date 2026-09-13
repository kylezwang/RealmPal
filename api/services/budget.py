"""
Global spend ceiling and kill switch.

Per-identity quotas stop one person from running up the bill, but they don't
stop a crowd: a thousand visitors each spending their free allowance is a
thousand allowances of Claude usage (Foundry CCU or direct Anthropic). This
tracks what the day has actually cost and refuses new work once the budget
is gone, so the worst case is a temporary outage rather than a surprise
invoice.

Cost is recorded in micro-dollars (millionths of a dollar) as an integer.
Redis counters are integers, and floating point accumulation over thousands
of increments would drift. Foundry invoices the same dollar amount as Claude
Consumption Units at `foundry_ccu_usd` ($0.01 at list; 100 CCU = $1).

Two ways chat can be switched off:

  * Automatically, when the day's recorded spend reaches the budget.
  * Manually, by setting the kill switch key in Redis | no redeploy needed,
    which matters when the thing you need to stop is costing money.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from ..config import Settings

KILL_SWITCH_KEY = "killswitch:chat"

# Keep a couple of days so the previous day stays inspectable.
_SPEND_TTL_SECONDS = 60 * 60 * 48

_DEFAULT_DISABLED_REASON = "Realm Pal is temporarily unavailable. Please try again later."
_BUDGET_REASON = (
    "Realm Pal has hit its daily usage limit. It'll be back tomorrow | "
    "this keeps a hobby project affordable to run."
)


@dataclass(frozen=True)
class BudgetState:
    """What today has cost, against what it's allowed to cost."""

    spent_micros: int
    limit_micros: int

    @property
    def exhausted(self) -> bool:
        return self.spent_micros >= self.limit_micros

    @property
    def spent_usd(self) -> float:
        return self.spent_micros / 1_000_000

    @property
    def limit_usd(self) -> float:
        return self.limit_micros / 1_000_000

    @property
    def remaining_usd(self) -> float:
        return max(0.0, (self.limit_micros - self.spent_micros) / 1_000_000)


def today_key(now: Optional[datetime] = None) -> str:
    """Spend counter key for the current UTC day."""
    moment = now or datetime.now(timezone.utc)
    return f"budget:spend:{moment.strftime('%Y-%m-%d')}"


def rates_for_model(settings: Settings, model: str = "") -> tuple[float, float]:
    """Per-million token prices for the model that actually ran."""
    light = (settings.claude_light_model or "").strip()
    if light and model == light and model != settings.claude_model:
        return (
            settings.light_model_input_cost_per_mtok_usd,
            settings.light_model_output_cost_per_mtok_usd,
        )
    return (
        settings.model_input_cost_per_mtok_usd,
        settings.model_output_cost_per_mtok_usd,
    )


def cost_micros(
    settings: Settings,
    input_tokens: int,
    output_tokens: int,
    *,
    model: str = "",
) -> int:
    """
    Cost of one Claude call in micro-dollars.

    Prices are quoted per million tokens, and a micro-dollar is a millionth
    of a dollar, so `tokens * price_per_million` already lands in micros.
    Foundry bills the same list rates rolled up as Claude Consumption Units.
    """
    input_rate, output_rate = rates_for_model(settings, model)
    return round(
        max(0, input_tokens) * input_rate + max(0, output_tokens) * output_rate
    )


def cost_ccu(settings: Settings, micros: int) -> float:
    """
    Claude Consumption Units for a spend already expressed in micro-dollars.

    Azure Marketplace meters CCU at `foundry_ccu_usd` each ($0.01 at list,
    so 100 CCU = $1). Token rates did not change; CCU is the invoice line.
    """
    price = settings.foundry_ccu_usd
    if price <= 0 or micros <= 0:
        return 0.0
    return round((micros / 1_000_000) / price, 4)


def today_error_key(provider: str, now: Optional[datetime] = None) -> str:
    """Per-provider stream-failure counter for the current UTC day."""
    moment = now or datetime.now(timezone.utc)
    safe = "".join(c for c in provider.strip().lower() if c.isalnum() or c == "_") or "unknown"
    return f"llm:errors:{moment.strftime('%Y-%m-%d')}:{safe}"


async def disabled_reason(redis: aioredis.Redis, settings: Settings) -> Optional[str]:
    """
    Why chat is unavailable, or None when it's fine.

    Checks the manual switch first: if someone flipped it, that's a
    deliberate decision and shouldn't be masked by budget state.
    """
    if not settings.chat_enabled:
        return _DEFAULT_DISABLED_REASON

    try:
        switched_off = await redis.get(KILL_SWITCH_KEY)
    except Exception:
        # Never let a Redis blip take chat down by itself.
        logger.exception("Could not read the chat kill switch")
        switched_off = None

    if switched_off:
        return switched_off if isinstance(switched_off, str) else _DEFAULT_DISABLED_REASON

    state = await budget_state(redis, settings)
    if state.exhausted:
        logger.bind(
            spent_usd=round(state.spent_usd, 4), limit_usd=round(state.limit_usd, 4)
        ).warning("Daily spend budget exhausted; refusing new chat requests")
        return _BUDGET_REASON

    return None


async def budget_state(redis: aioredis.Redis, settings: Settings) -> BudgetState:
    """Today's recorded spend against the daily limit."""
    limit = settings.daily_cost_budget_micros
    try:
        raw = await redis.get(today_key())
        spent = int(raw) if raw is not None else 0
    except Exception:
        # Failing open is the right call: a Redis read problem shouldn't take
        # the product down, and per-identity quotas still apply.
        logger.exception("Could not read today's spend")
        spent = 0
    return BudgetState(spent_micros=max(0, spent), limit_micros=limit)


async def record_usage(
    redis: aioredis.Redis,
    settings: Settings,
    *,
    input_tokens: int,
    output_tokens: int,
    provider: str = "",
    model: str = "",
) -> int:
    """
    Add one call's cost to today's total. Returns the new total in micros.

    Called after a response finishes, when real token counts are known, so
    the budget reflects actual spend rather than an estimate. `provider` is
    log-only: Foundry and direct Anthropic share the same daily dollar cap.
    """
    micros = cost_micros(settings, input_tokens, output_tokens, model=model)
    if micros <= 0:
        return (await budget_state(redis, settings)).spent_micros

    key = today_key()
    try:
        total = await redis.incrby(key, micros)
        if total == micros:
            await redis.expire(key, _SPEND_TTL_SECONDS)
    except Exception:
        logger.exception("Could not record chat spend")
        return micros

    backend = provider or settings.llm_provider
    logger.bind(
        provider=backend,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(micros / 1_000_000, 6),
        cost_ccu=cost_ccu(settings, micros),
        day_total_usd=round(total / 1_000_000, 4),
        day_total_ccu=cost_ccu(settings, total),
        budget_usd=round(settings.daily_cost_budget_micros / 1_000_000, 4),
    ).info("Recorded chat spend")
    return int(total)


async def record_llm_failure(
    redis: aioredis.Redis,
    settings: Settings,
    *,
    provider: str = "",
) -> None:
    """
    Count a failed stream without touching the spend counter.

    Token usage is unknown when the provider errors out, so this is a
    monitoring signal (spikes of Foundry 401s, timeouts, 429s) rather than
    a budget increment. Failures here must not raise into the chat stream.
    """
    backend = provider or settings.llm_provider
    key = today_error_key(backend)
    try:
        total = await redis.incr(key)
        if total == 1:
            await redis.expire(key, _SPEND_TTL_SECONDS)
    except Exception:
        logger.exception("Could not record LLM failure counter")
        return
    logger.bind(provider=backend, day_errors=total).warning("Recorded chat stream failure")
