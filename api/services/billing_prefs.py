"""Per-email on-demand spend cap for paid Claude overage.

Default is $0: included Claude replies only. A paying user can raise the
cap (Cursor-style) so extra replies bill at CLAUDE_OVERAGE_USD.

Shares the `entitlements` table/backend (api/services/entitlements.py,
api/services/db.py) rather than a table of its own - one row per email
either way, no reason to split it.
"""
from __future__ import annotations

import time
from typing import Optional

from ..config import Settings
from . import db, entitlements

ALLOWED_CAPS_USD = (0.0, 20.0, 50.0, 100.0)
PRESET_CAPS_USD = (20.0, 50.0, 100.0)
MAX_SPEND_CAP_USD = 200.0

_ready: set[str] = set()


async def _ensure_column(settings: Settings) -> None:
    key = settings.database_url.strip() or settings.entitlements_db_path
    if key in _ready:
        return
    # The base table lives in entitlements.py - make sure it exists before
    # altering it (tests hit this store directly without going through
    # entitlements first).
    await entitlements.init_db(settings)
    await db.add_column_if_missing(
        settings, settings.entitlements_db_path,
        "entitlements", "spend_cap_cents", "INTEGER NOT NULL DEFAULT 0",
    )
    _ready.add(key)


def _normalize(email: str) -> str:
    return (email or "").strip().lower()


async def get_spend_cap_usd(email: str, settings: Settings) -> float:
    email = _normalize(email)
    if not email:
        return 0.0

    await _ensure_column(settings)
    row = await db.fetchone(
        settings, settings.entitlements_db_path,
        "SELECT spend_cap_cents FROM entitlements WHERE email = ?", (email,),
    )
    cents = int(row[0]) if row else 0
    return max(0.0, cents / 100.0)


async def set_spend_cap_usd(
    email: str, spend_cap_usd: float, settings: Settings
) -> float:
    email = _normalize(email)
    if not email:
        return 0.0
    value = max(0.0, min(float(spend_cap_usd), MAX_SPEND_CAP_USD))
    cents = int(round(value * 100))

    await _ensure_column(settings)
    await db.execute(
        settings, settings.entitlements_db_path,
        "UPDATE entitlements SET spend_cap_cents = ?, updated_at = ? WHERE email = ?",
        (cents, int(time.time()), email),
    )
    return cents / 100.0


async def customer_id(email: str, settings: Settings) -> Optional[str]:
    email = _normalize(email)
    if not email:
        return None

    row = await db.fetchone(
        settings, settings.entitlements_db_path,
        "SELECT stripe_customer_id FROM entitlements WHERE email = ?", (email,),
    )
    return row[0] if row and row[0] else None
