"""Monthly Claude pool + optional on-demand overage for paid accounts.

Guest/free daily message quotas and this paid meter all skip a turn that
never calls Claude. Only a real model call consumes a daily message, an
included reply, or, after that, $0.08 against the user's spend cap.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from fastapi import HTTPException
from loguru import logger

from ..config import Settings
from ..identity import AuthenticatedUser
from ..models.chat import PaywallResponse
from . import billing_prefs, daily_quests
from .dev_access import is_debug_unlimited
from .rate_limit import hash_identifier

OVERAGE_REASON_POOL = "claude_pool"
OVERAGE_REASON_CAP = "spend_cap"


@dataclass(frozen=True)
class ClaudeUsage:
    used: int
    included: int
    remaining: int
    spend_cap_usd: float
    on_demand_spent_usd: float
    month: str


def _month_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


def _bucket(email: str, settings: Settings) -> str:
    return hash_identifier((email or "").strip().lower(), settings)


def _count_key(email: str, settings: Settings) -> str:
    return f"claude:month:{_bucket(email, settings)}:{_month_stamp()}"


def _overage_key(email: str, settings: Settings) -> str:
    return f"claude:overage-cents:{_bucket(email, settings)}:{_month_stamp()}"


async def peek_claude_usage(
    redis: aioredis.Redis,
    email: str,
    settings: Settings,
) -> ClaudeUsage:
    included = settings.paid_claude_included + await daily_quests.peek_paid_bonus(
        redis, email, settings
    )
    raw = await redis.get(_count_key(email, settings))
    used = int(raw or 0)
    overage_raw = await redis.get(_overage_key(email, settings))
    overage_cents = int(overage_raw or 0)
    cap = await billing_prefs.get_spend_cap_usd(email, settings)
    return ClaudeUsage(
        used=used,
        included=included,
        remaining=max(0, included - used),
        spend_cap_usd=cap,
        on_demand_spent_usd=overage_cents / 100.0,
        month=_month_stamp(),
    )


async def consume_claude_reply(
    redis: aioredis.Redis,
    user: Optional[AuthenticatedUser],
    settings: Settings,
    *,
    paid: bool,
) -> None:
    """Count one Claude call, or raise 402 if the included pool and cap are spent."""
    if not paid or user is None or not user.email:
        return
    if await is_debug_unlimited(user, settings):
        return

    email = user.email
    used = int(await redis.incr(_count_key(email, settings)))
    await redis.expire(_count_key(email, settings), 40 * 24 * 3600)
    included = settings.paid_claude_included + await daily_quests.peek_paid_bonus(
        redis, email, settings
    )
    if used <= included:
        return

    extra = used - included
    extra_cost = extra * settings.claude_overage_usd
    cap = await billing_prefs.get_spend_cap_usd(email, settings)
    if extra_cost > cap + 1e-9:
        await redis.decr(_count_key(email, settings))
        reason = OVERAGE_REASON_CAP if cap > 0 else OVERAGE_REASON_POOL
        message = (
            f"You've reached your ${cap:.0f} usage cap this month. "
            "Raise it in Settings to keep going. Stored answers stay free."
            if reason == OVERAGE_REASON_CAP
            else (
                f"You've used your {included} included Claude replies this month. "
                "Stored answers stay free. Enable usage to keep going at "
                f"${settings.claude_overage_usd:.2f} per Claude reply."
            )
        )
        logger.bind(email_hash=_bucket(email, settings), used=used, cap=cap).info(
            "Paid Claude pool exhausted"
        )
        raise HTTPException(
            status_code=402,
            detail=PaywallResponse(
                message=message,
                checkout_url=None,
                scope="user",
                used=min(used - 1, included),
                limit=included,
                remaining=0,
                reason=reason,
                spend_cap_usd=cap,
            ).model_dump(),
        )

    cents = int(round(settings.claude_overage_usd * 100))
    await redis.incrby(_overage_key(email, settings), cents)
    await redis.expire(_overage_key(email, settings), 40 * 24 * 3600)
