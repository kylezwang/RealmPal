"""
Durable entitlement store: real subscription state for the "paid" flag.

Before this, a Stripe payment minted a magic link that, once redeemed,
produced a JWT with `paid: true` on it. Nothing else was ever checked again
- a chargeback, a cancellation, or a refund left that JWT working exactly as
before until it expired (up to `JWT_EXPIRY_DAYS`). Stripe webhooks now write
subscription status here, and the chat path (`api/routers/chat.py`) reads it
back instead of trusting the JWT claim indefinitely.

SQLite, not Postgres: this table is one row per paying email, nowhere near
the scale where SQLite's single-writer model would hurt, and it matches the
plan already written down at the top of BACKLOG.md ("SQLite on a mounted
volume until billing lands, then Azure Postgres"). A stdlib `sqlite3`
connection wrapped in `asyncio.to_thread` avoids a new dependency for that
scale; a module-level lock serializes writes since SQLite doesn't do
multi-writer concurrency safely on its own.

Fail-closed on "we've never heard of this email": `api/routers/auth.py`
lets anyone request a sign-in link for any address, independent of payment,
so an unknown email is the ordinary shape of a brand-new free sign-in - not
a rare pre-existing customer this store just hasn't heard about yet.
Treating "unknown" as active would hand every new sign-up the paid tier for
free. Only a row with an active/trialing status counts; everything else,
including no row at all, does not.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from ..config import Settings

# Stripe subscription statuses that should count as "can use the paid tier".
# Everything else (canceled, unpaid, past_due, incomplete_expired, ...) does not.
_ACTIVE_STATUSES = frozenset({"active", "trialing"})

_write_lock = asyncio.Lock()
_connections: dict[str, sqlite3.Connection] = {}


def _connection(db_path: str) -> sqlite3.Connection:
    """One cached connection per resolved path, created (and schema'd) lazily."""
    resolved = str(Path(db_path).resolve())
    conn = _connections.get(resolved)
    if conn is not None:
        return conn

    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entitlements (
            email TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            updated_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_entitlements_customer "
        "ON entitlements(stripe_customer_id)"
    )
    _connections[resolved] = conn
    return conn


async def init_db(settings: Settings) -> None:
    """Create the DB file and schema if they don't exist yet. Call at startup."""
    await asyncio.to_thread(_connection, settings.entitlements_db_path)


def _normalize(email: str) -> str:
    return (email or "").strip().lower()


async def upsert(
    email: str,
    *,
    status: str,
    settings: Settings,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
) -> None:
    """Write (or overwrite) one email's subscription status."""
    email = _normalize(email)
    if not email:
        return

    def _write() -> None:
        conn = _connection(settings.entitlements_db_path)
        conn.execute(
            """
            INSERT INTO entitlements (email, status, stripe_customer_id, stripe_subscription_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                status = excluded.status,
                stripe_customer_id = COALESCE(excluded.stripe_customer_id, entitlements.stripe_customer_id),
                stripe_subscription_id = COALESCE(excluded.stripe_subscription_id, entitlements.stripe_subscription_id),
                updated_at = excluded.updated_at
            """,
            (email, status, stripe_customer_id, stripe_subscription_id, int(time.time())),
        )

    async with _write_lock:
        await asyncio.to_thread(_write)


async def set_status_by_customer(
    stripe_customer_id: str, status: str, settings: Settings
) -> Optional[str]:
    """
    Update the row matching a Stripe customer ID (subscription.updated /
    subscription.deleted only carry the customer, not the email). Returns
    the affected email, or None if no row matched.
    """
    if not stripe_customer_id:
        return None

    def _write() -> Optional[str]:
        conn = _connection(settings.entitlements_db_path)
        row = conn.execute(
            "SELECT email FROM entitlements WHERE stripe_customer_id = ?",
            (stripe_customer_id,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE entitlements SET status = ?, updated_at = ? WHERE stripe_customer_id = ?",
            (status, int(time.time()), stripe_customer_id),
        )
        return row[0]

    async with _write_lock:
        email = await asyncio.to_thread(_write)
    if email:
        logger.bind(status=status).info("Entitlement status updated from Stripe webhook")
    else:
        logger.bind(customer_id_known=False).warning(
            "Stripe subscription event for a customer with no entitlement row"
        )
    return email


async def get_status(email: str, settings: Settings) -> Optional[str]:
    """Raw stored status, or None if this email has no row at all. Mainly
    for tests and diagnostics; `is_active` is what callers should use."""
    email = _normalize(email)
    if not email:
        return None

    def _read() -> Optional[str]:
        conn = _connection(settings.entitlements_db_path)
        row = conn.execute(
            "SELECT status FROM entitlements WHERE email = ?", (email,)
        ).fetchone()
        return row[0] if row else None

    return await asyncio.to_thread(_read)


async def get_stripe_customer_id(email: str, settings: Settings) -> Optional[str]:
    """Stripe customer ID for this email, or None if no row / never had one.

    Used to open a Stripe Customer Portal session so a paid user can cancel
    or update their payment method themselves instead of emailing support.
    """
    email = _normalize(email)
    if not email:
        return None

    def _read() -> Optional[str]:
        conn = _connection(settings.entitlements_db_path)
        row = conn.execute(
            "SELECT stripe_customer_id FROM entitlements WHERE email = ?", (email,)
        ).fetchone()
        return row[0] if row and row[0] else None

    return await asyncio.to_thread(_read)


async def is_active(email: str, settings: Settings) -> bool:
    """
    True only if this email has a row here with an active/trialing status.

    Fail-closed: no row (including an email that has simply never been
    through Stripe checkout) means not entitled, not "trust it anyway."
    """
    email = _normalize(email)
    if not email:
        return False

    def _read() -> Optional[str]:
        conn = _connection(settings.entitlements_db_path)
        row = conn.execute(
            "SELECT status FROM entitlements WHERE email = ?", (email,)
        ).fetchone()
        return row[0] if row else None

    status = await asyncio.to_thread(_read)
    return status in _ACTIVE_STATUSES
