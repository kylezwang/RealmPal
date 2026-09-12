"""
Temporary store for images users attach in chat.

Rows live in SQLite and are deleted once `expires_at` passes so a flood of
screenshots cannot grow the file forever. `train_on_data` is copied from the
caller's preference at upload time: later training jobs should only read
rows that opted in. We still store opted-out files for the TTL so the chat
can reference them, then they recycle the same way.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from ..config import Settings

_write_lock = asyncio.Lock()
_connections: dict[str, sqlite3.Connection] = {}


def _connection(db_path: str) -> sqlite3.Connection:
    resolved = str(Path(db_path).resolve())
    conn = _connections.get(resolved)
    if conn is not None:
        return conn

    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
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
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_uploads_expires ON uploads(expires_at)"
    )
    _connections[resolved] = conn
    return conn


def _purge(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "DELETE FROM uploads WHERE expires_at <= ?", (int(time.time()),)
    )
    return cur.rowcount


async def init_db(settings: Settings) -> None:
    def _init() -> None:
        conn = _connection(settings.uploads_db_path)
        _purge(conn)

    await asyncio.to_thread(_init)


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

    def _write() -> None:
        conn = _connection(settings.uploads_db_path)
        _purge(conn)
        conn.execute(
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

    async with _write_lock:
        await asyncio.to_thread(_write)

    return {
        "id": upload_id,
        "filename": filename,
        "expires_at": expires,
        "train_on_data": train_on_data,
    }


async def purge_expired(settings: Settings) -> int:
    def _run() -> int:
        return _purge(_connection(settings.uploads_db_path))

    async with _write_lock:
        return await asyncio.to_thread(_run)
