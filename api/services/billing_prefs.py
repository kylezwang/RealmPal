"""Per-email on-demand spend cap for paid Claude overage.

Default is $0: included Claude replies only. A paying user can raise the
cap (Cursor-style) so extra replies bill at CLAUDE_OVERAGE_USD.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Optional

from ..config import Settings

ALLOWED_CAPS_USD = (0.0, 20.0, 50.0, 100.0)
PRESET_CAPS_USD = (20.0, 50.0, 100.0)
MAX_SPEND_CAP_USD = 200.0

_write_lock = asyncio.Lock()
_ready: set[str] = set()


def _connection(db_path: str) -> sqlite3.Connection:
    from . import entitlements

    return entitlements._connection(db_path)


def _ensure_column(db_path: str) -> None:
    resolved = str(Path(db_path).resolve())
    if resolved in _ready:
        return
    conn = _connection(db_path)
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(entitlements)").fetchall()
    }
    if "spend_cap_cents" not in cols:
        conn.execute(
            "ALTER TABLE entitlements ADD COLUMN spend_cap_cents INTEGER NOT NULL DEFAULT 0"
        )
    _ready.add(resolved)


def _normalize(email: str) -> str:
    return (email or "").strip().lower()


async def get_spend_cap_usd(email: str, settings: Settings) -> float:
    email = _normalize(email)
    if not email:
        return 0.0

    def _read() -> int:
        _ensure_column(settings.entitlements_db_path)
        conn = _connection(settings.entitlements_db_path)
        row = conn.execute(
            "SELECT spend_cap_cents FROM entitlements WHERE email = ?",
            (email,),
        ).fetchone()
        return int(row[0]) if row else 0

    cents = await asyncio.to_thread(_read)
    return max(0.0, cents / 100.0)


async def set_spend_cap_usd(
    email: str, spend_cap_usd: float, settings: Settings
) -> float:
    email = _normalize(email)
    if not email:
        return 0.0
    value = max(0.0, min(float(spend_cap_usd), MAX_SPEND_CAP_USD))
    cents = int(round(value * 100))

    def _write() -> None:
        _ensure_column(settings.entitlements_db_path)
        conn = _connection(settings.entitlements_db_path)
        conn.execute(
            "UPDATE entitlements SET spend_cap_cents = ?, updated_at = ? WHERE email = ?",
            (cents, int(time.time()), email),
        )

    async with _write_lock:
        await asyncio.to_thread(_write)
    return cents / 100.0


async def customer_id(email: str, settings: Settings) -> Optional[str]:
    email = _normalize(email)
    if not email:
        return None

    def _read() -> Optional[str]:
        conn = _connection(settings.entitlements_db_path)
        row = conn.execute(
            "SELECT stripe_customer_id FROM entitlements WHERE email = ?",
            (email,),
        ).fetchone()
        return row[0] if row and row[0] else None

    return await asyncio.to_thread(_read)
