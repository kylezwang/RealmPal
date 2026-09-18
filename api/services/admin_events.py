"""Admin notification feed: Claude-turn costs plus existing store rows.

Feedback, new accounts, and Stripe rows are read from their own tables so
production history is visible on day one. Chat costs start after this
deploy (they were never stored per turn).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

from ..config import Settings
from . import accounts, db, entitlements, product_feedback
from .budget import budget_state


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS admin_chat_events (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        tier TEXT NOT NULL,
        cost_usd REAL NOT NULL,
        email TEXT,
        ign TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_admin_chat_created ON admin_chat_events(created_at)",
)

_ready: set[str] = set()


def reset_ready_for_tests() -> None:
    _ready.clear()


async def init_db(settings: Settings) -> None:
    key = settings.database_url.strip() or settings.admin_events_db_path
    if key in _ready:
        return
    await db.run_ddl(settings, settings.admin_events_db_path, _SCHEMA)
    _ready.add(key)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat()
    return str(value or "")


def feedback_reply_template(row: dict) -> dict:
    """Mailto draft filled from the submitter's answers. Empty mailto if no email."""
    email = str(row.get("email") or "").strip()
    ign = str(row.get("ign") or "").strip() or "there"
    rating = str(row.get("rating") or "").strip() or "(none)"
    works = str(row.get("what_works") or "").strip() or "(none)"
    improve = str(row.get("what_to_improve") or "").strip() or "(none)"
    extra = str(row.get("anything_else") or "").strip() or "(none)"
    subject = "Thanks for your RealmPal feedback"
    body = (
        f"Hi {ign},\n\n"
        "Thanks for the feedback. I read it and wanted to follow up.\n\n"
        f"Rating: {rating}\n"
        f"What works: {works}\n"
        f"What to improve: {improve}\n"
        f"Anything else: {extra}\n\n"
        "Best,\n"
        "Turbine\n"
    )
    mailto = ""
    if email:
        mailto = f"mailto:{email}?subject={quote(subject)}&body={quote(body)}"
    return {
        "reply_email": email or None,
        "reply_subject": subject,
        "reply_body": body,
        "mailto": mailto,
    }


async def record_chat_turn(
    settings: Settings,
    *,
    tier: str,
    cost_usd: float,
    email: Optional[str] = None,
    ign: Optional[str] = None,
) -> None:
    """One Claude reply. Must not raise into the chat stream."""
    import uuid

    try:
        await init_db(settings)
        await db.execute(
            settings,
            settings.admin_events_db_path,
            """
            INSERT INTO admin_chat_events (id, created_at, tier, cost_usd, email, ign)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                datetime.now(timezone.utc).isoformat(),
                (tier or "guest")[:16],
                float(max(0.0, cost_usd)),
                (email or "").strip().lower() or None,
                (ign or "").strip()[:32] or None,
            ),
        )
    except Exception:
        return


async def list_chat_events(settings: Settings, limit: int = 50) -> list[dict]:
    await init_db(settings)
    rows = await db.fetchall(
        settings,
        settings.admin_events_db_path,
        """
        SELECT created_at, tier, cost_usd, email, ign
        FROM admin_chat_events
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 200)),),
    )
    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "kind": "chat",
                "created_at": row[0],
                "tier": row[1],
                "cost_usd": float(row[2] or 0),
                "email": row[3],
                "ign": row[4],
            }
        )
    return out


async def list_recent_accounts(settings: Settings, limit: int = 50) -> list[dict]:
    await accounts.init_db(settings)
    rows = await db.fetchall(
        settings,
        settings.accounts_db_path,
        """
        SELECT email, ign, created_at FROM accounts
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 200)),),
    )
    return [
        {
            "kind": "account",
            "created_at": _iso(row[2]),
            "email": row[0],
            "ign": row[1],
        }
        for row in rows
    ]


async def list_recent_subscriptions(settings: Settings, limit: int = 50) -> list[dict]:
    await entitlements.init_db(settings)
    rows = await db.fetchall(
        settings,
        settings.entitlements_db_path,
        """
        SELECT email, status, stripe_subscription_id, updated_at
        FROM entitlements
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 200)),),
    )
    return [
        {
            "kind": "subscription",
            "created_at": _iso(row[3]),
            "email": row[0],
            "status": row[1],
            "stripe_subscription_id": row[2],
        }
        for row in rows
    ]


async def build_feed(settings: Settings, *, redis, limit: int = 80) -> dict:
    chats = await list_chat_events(settings, limit)
    feedback_rows = await product_feedback.list_recent(settings, limit)
    account_rows = await list_recent_accounts(settings, limit)
    sub_rows = await list_recent_subscriptions(settings, limit)
    items: list[dict] = list(chats)
    items.extend(account_rows)
    items.extend(sub_rows)
    for row in feedback_rows:
        item = {
            "kind": "feedback",
            "created_at": row["created_at"],
            "email": row["email"],
            "ign": row["ign"],
            "rating": row["rating"],
            "what_works": row["what_works"],
            "what_to_improve": row["what_to_improve"],
            "anything_else": row["anything_else"],
        }
        item.update(feedback_reply_template(item))
        items.append(item)
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    spend = await budget_state(redis, settings)
    return {
        "spend_today_usd": round(spend.spent_micros / 1_000_000, 4),
        "spend_budget_usd": round(spend.limit_micros / 1_000_000, 4),
        "items": items[:limit],
    }
