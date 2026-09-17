"""Site-level Feedback modal store.

Per-message thumbs-up/down still lives in Redis (`POST /chat/feedback`).
This table is the header Feedback button: a few general questions, one row
per submit, meant to be scanned in Azure Query Editor:

    SELECT created_at, rating, what_works, what_to_improve, anything_else, email
    FROM product_feedback
    ORDER BY created_at DESC
    LIMIT 100;

Backed by `api/services/db.py`: SQLite locally (default), the same Azure
Postgres database as accounts/chat_sessions when `DATABASE_URL` is set.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, TypedDict

from ..config import Settings
from . import db

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS product_feedback (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        email TEXT,
        rating TEXT NOT NULL,
        what_works TEXT NOT NULL,
        what_to_improve TEXT NOT NULL,
        anything_else TEXT NOT NULL,
        ign TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_product_feedback_created ON product_feedback(created_at)",
)

_ready: set[str] = set()
_TEXT_CAP = 4000
_IGN_CAP = 32


class FeedbackRow(TypedDict):
    id: str
    created_at: str
    email: Optional[str]
    rating: str
    what_works: str
    what_to_improve: str
    anything_else: str
    ign: Optional[str]


async def init_db(settings: Settings) -> None:
    key = settings.database_url.strip() or settings.product_feedback_db_path
    if key in _ready:
        return
    await db.run_ddl(settings, settings.product_feedback_db_path, _SCHEMA)
    _ready.add(key)


def _clip(value: str, cap: int) -> str:
    return (value or "").strip()[:cap]


async def insert_feedback(
    settings: Settings,
    *,
    rating: str,
    what_works: str = "",
    what_to_improve: str = "",
    anything_else: str = "",
    email: Optional[str] = None,
    ign: Optional[str] = None,
) -> FeedbackRow:
    await init_db(settings)
    row: FeedbackRow = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "email": (email or "").strip().lower() or None,
        "rating": rating,
        "what_works": _clip(what_works, _TEXT_CAP),
        "what_to_improve": _clip(what_to_improve, _TEXT_CAP),
        "anything_else": _clip(anything_else, _TEXT_CAP),
        "ign": _clip(ign or "", _IGN_CAP) or None,
    }
    await db.execute(
        settings,
        settings.product_feedback_db_path,
        """
        INSERT INTO product_feedback (
            id, created_at, email, rating, what_works, what_to_improve, anything_else, ign
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["id"],
            row["created_at"],
            row["email"],
            row["rating"],
            row["what_works"],
            row["what_to_improve"],
            row["anything_else"],
            row["ign"],
        ),
    )
    return row


async def list_recent(settings: Settings, limit: int = 50) -> list[FeedbackRow]:
    """Newest first. Used by tests; ops scans the table in Azure Postgres."""
    await init_db(settings)
    rows = await db.fetchall(
        settings,
        settings.product_feedback_db_path,
        """
        SELECT id, created_at, email, rating, what_works, what_to_improve, anything_else, ign
        FROM product_feedback
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 500)),),
    )
    out: list[FeedbackRow] = []
    for row in rows:
        out.append(
            {
                "id": row[0],
                "created_at": row[1],
                "email": row[2],
                "rating": row[3],
                "what_works": row[4],
                "what_to_improve": row[5],
                "anything_else": row[6],
                "ign": row[7],
            }
        )
    return out


def reset_ready_for_tests() -> None:
    """Tests that swap DATABASE_URL / db path between cases."""
    _ready.clear()
