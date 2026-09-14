"""
Temporary store for images users attach in chat.

Rows are deleted once `expires_at` passes so a flood of screenshots cannot
grow the store forever. `train_on_data` is copied from the caller's
preference at upload time: later training jobs should only read rows that
opted in. We still store opted-out files for the TTL so the chat can
reference them, then they recycle the same way.

Backed by `api/services/db.py`: SQLite locally (default), Postgres in any
deployment with `DATABASE_URL` set. The `data` column is the one place the
two backends' DDL actually differs (SQLite's `BLOB` vs Postgres's `BYTEA`),
everything else is portable.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from ..config import Settings
from . import db

_SCHEMA_SQLITE = (
    """
    CREATE TABLE IF NOT EXISTS uploads (
        id TEXT PRIMARY KEY,
        email TEXT,
        session_id TEXT,
        filename TEXT NOT NULL,
        content_type TEXT NOT NULL,
        data BLOB NOT NULL,
        train_on_data INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_uploads_expires ON uploads(expires_at)",
)
_SCHEMA_POSTGRES = (
    """
    CREATE TABLE IF NOT EXISTS uploads (
        id TEXT PRIMARY KEY,
        email TEXT,
        session_id TEXT,
        filename TEXT NOT NULL,
        content_type TEXT NOT NULL,
        data BYTEA NOT NULL,
        train_on_data INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_uploads_expires ON uploads(expires_at)",
)

# Kept for tests that reach past the public API to seed/mutate rows directly.
_connection = db.sqlite_connection

# Schema created lazily on first use per resolved path/DSN - see the same
# note in entitlements.py.
_ready: set[str] = set()


async def _ensure_schema(settings: Settings) -> None:
    key = settings.database_url.strip() or settings.uploads_db_path
    if key in _ready:
        return
    await db.run_ddl(
        settings, settings.uploads_db_path, _SCHEMA_SQLITE,
        postgres_statements=_SCHEMA_POSTGRES,
    )
    _ready.add(key)


async def init_db(settings: Settings) -> None:
    """Call at startup: creates the table, then sweeps anything already
    expired (e.g. from a long-stopped dev server)."""
    await _ensure_schema(settings)
    await purge_expired(settings)


async def store(
    *,
    data: bytes,
    filename: str,
    content_type: str,
    settings: Settings,
    email: Optional[str] = None,
    session_id: Optional[str] = None,
    train_on_data: bool = True,
) -> dict:
    now = int(time.time())
    expires = now + max(1, settings.upload_ttl_days) * 86400
    upload_id = uuid.uuid4().hex

    await _ensure_schema(settings)
    await purge_expired(settings)
    await db.execute(
        settings,
        settings.uploads_db_path,
        """
        INSERT INTO uploads
          (id, email, session_id, filename, content_type, data,
           train_on_data, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            upload_id,
            (email or "").strip().lower() or None,
            session_id or None,
            filename,
            content_type,
            data,
            1 if train_on_data else 0,
            now,
            expires,
        ),
    )

    return {
        "id": upload_id,
        "filename": filename,
        "expires_at": expires,
        "train_on_data": train_on_data,
    }


async def purge_expired(settings: Settings) -> int:
    await _ensure_schema(settings)
    rows = await db.fetchall(
        settings, settings.uploads_db_path,
        "SELECT id FROM uploads WHERE expires_at <= ?", (int(time.time()),),
    )
    if not rows:
        return 0
    await db.execute(
        settings, settings.uploads_db_path,
        "DELETE FROM uploads WHERE expires_at <= ?", (int(time.time()),),
    )
    return len(rows)
