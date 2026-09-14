"""
Durable entitlement store: real subscription state for the "paid" flag.

Before this, a Stripe payment minted a magic link that, once redeemed,
produced a JWT with `paid: true` on it. Nothing else was ever checked again
- a chargeback, a cancellation, or a refund left that JWT working exactly as
before until it expired (up to `JWT_EXPIRY_DAYS`). Stripe webhooks now write
subscription status here, and the chat path (`api/routers/chat.py`) reads it
back instead of trusting the JWT claim indefinitely.

Backed by `api/services/db.py`: SQLite locally (default), Postgres in any
deployment with `DATABASE_URL` set (see that module and BACKLOG.md history
for why - one row per paying email is tiny either way, but SQLite on a
shared volume across Container Apps replicas is not safe with concurrent
writers, so a real deployment needs the Postgres path).

Fail-closed on "we've never heard of this email": `api/routers/auth.py`
lets anyone request a sign-in link for any address, independent of payment,
so an unknown email is the ordinary shape of a brand-new free sign-in - not
a rare pre-existing customer this store just hasn't heard about yet.
Treating "unknown" as active would hand every new sign-up the paid tier for
free. Only a row with an active/trialing status counts; everything else,
including no row at all, does not.
"""
from __future__ import annotations

import time
from typing import Optional

from loguru import logger

from ..config import Settings
from . import db

# Stripe subscription statuses that should count as "can use the paid tier".
# Everything else (canceled, unpaid, past_due, incomplete_expired, ...) does not.
_ACTIVE_STATUSES = frozenset({"active", "trialing"})

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS entitlements (
        email TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        updated_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_entitlements_customer "
    "ON entitlements(stripe_customer_id)",
)

# Kept for the handful of tests/other modules that reach past the public API
# (billing_prefs.py shares this table; test_payments.py inspects raw rows).
_connection = db.sqlite_connection

# Schema is created lazily on first use per resolved path/DSN, same as the
# old per-path cached sqlite3.Connection did implicitly - so every function
# below calls this first instead of requiring every caller (including every
# test) to remember to call `init_db` explicitly before touching the store.
_ready: set[str] = set()


async def init_db(settings: Settings) -> None:
    """Create the table/indexes if they don't exist yet. Cheap to call
    more than once - only actually runs DDL the first time per path/DSN."""
    key = settings.database_url.strip() or settings.entitlements_db_path
    if key in _ready:
        return
    await db.run_ddl(settings, settings.entitlements_db_path, _SCHEMA)
    _ready.add(key)


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

    await init_db(settings)
    await db.execute(
        settings,
        settings.entitlements_db_path,
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

    await init_db(settings)
    row = await db.execute_returning(
        settings,
        settings.entitlements_db_path,
        """
        UPDATE entitlements SET status = ?, updated_at = ?
        WHERE stripe_customer_id = ?
        RETURNING email
        """,
        (status, int(time.time()), stripe_customer_id),
    )
    email = row[0] if row else None
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

    await init_db(settings)
    row = await db.fetchone(
        settings, settings.entitlements_db_path,
        "SELECT status FROM entitlements WHERE email = ?", (email,),
    )
    return row[0] if row else None


async def get_stripe_customer_id(email: str, settings: Settings) -> Optional[str]:
    """Stripe customer ID for this email, or None if no row / never had one.

    Used to open a Stripe Customer Portal session so a paid user can cancel
    or update their payment method themselves instead of emailing support.
    """
    email = _normalize(email)
    if not email:
        return None

    await init_db(settings)
    row = await db.fetchone(
        settings, settings.entitlements_db_path,
        "SELECT stripe_customer_id FROM entitlements WHERE email = ?", (email,),
    )
    return row[0] if row and row[0] else None


async def is_active(email: str, settings: Settings) -> bool:
    """
    True only if this email has a row here with an active/trialing status.

    Fail-closed: no row (including an email that has simply never been
    through Stripe checkout) means not entitled, not "trust it anyway."
    """
    email = _normalize(email)
    if not email:
        return False

    await init_db(settings)
    row = await db.fetchone(
        settings, settings.entitlements_db_path,
        "SELECT status FROM entitlements WHERE email = ?", (email,),
    )
    status = row[0] if row else None
    return status in _ACTIVE_STATUSES
