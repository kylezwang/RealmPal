"""
Server-side chat history sync for signed-in accounts.

Chats used to live entirely in the browser's localStorage
(`realm_pal_sessions:{email}` in web/lib/chatHistory.ts). That works fine
within one browser profile, but an incognito window's localStorage is torn
down as soon as the last incognito window closes - so "sign in, start a few
chats, close incognito, sign back in (a new incognito session)" looked like
chat history vanishing even though the *account* was never touched. Found
live Sep 14.

This store makes a signed-in account, not a browser, the unit of chat
persistence: every session a signed-in user creates gets mirrored here too,
and signing in anywhere (a fresh browser, a new incognito session, a
different device) pulls those back down and merges them with whatever is
already local. localStorage stays as the fast path for first paint and as
the *only* storage for anonymous/guest sessions - there is no email to key
a server row on for those, so this module is strictly additive for
signed-in accounts, never a replacement for local storage.

Backed by `api/services/db.py`: SQLite locally (default), Postgres in any
deployment with `DATABASE_URL` set - same pattern as entitlements.py and
accounts.py.
"""
from __future__ import annotations

import json
import time
from typing import Optional, TypedDict

from ..config import Settings
from . import db

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        email TEXT NOT NULL,
        session_id TEXT NOT NULL,
        title TEXT NOT NULL,
        messages TEXT NOT NULL,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (email, session_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_email ON chat_sessions(email)",
)

# Schema created lazily on first use per resolved path/DSN - same pattern as
# entitlements.py / accounts.py.
_ready: set[str] = set()


class SessionPayload(TypedDict):
    id: str
    title: str
    messages: list[dict]
    updatedAt: int


async def init_db(settings: Settings) -> None:
    key = settings.database_url.strip() or settings.chat_sessions_db_path
    if key in _ready:
        return
    await db.run_ddl(settings, settings.chat_sessions_db_path, _SCHEMA)
    _ready.add(key)


def _normalize(email: str) -> str:
    return (email or "").strip().lower()


async def list_sessions(settings: Settings, email: str) -> list[SessionPayload]:
    """Every session for this account, newest first."""
    await init_db(settings)
    email = _normalize(email)
    if not email:
        return []
    rows = await db.fetchall(
        settings,
        settings.chat_sessions_db_path,
        """
        SELECT session_id, title, messages, updated_at
        FROM chat_sessions
        WHERE email = ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (email, settings.chat_sessions_max_per_account),
    )
    out: list[SessionPayload] = []
    for session_id, title, messages_json, updated_at in rows:
        try:
            messages = json.loads(messages_json)
        except (TypeError, ValueError):
            messages = []
        out.append(
            {
                "id": session_id,
                "title": title,
                "messages": messages,
                "updatedAt": int(updated_at),
            }
        )
    return out


async def upsert_session(
    settings: Settings,
    email: str,
    session_id: str,
    *,
    title: str,
    messages: list[dict],
    updated_at: Optional[int] = None,
) -> None:
    """Write (or overwrite) one session. `updated_at` defaults to now."""
    await init_db(settings)
    email = _normalize(email)
    if not email or not session_id:
        return
    await db.execute(
        settings,
        settings.chat_sessions_db_path,
        """
        INSERT INTO chat_sessions (email, session_id, title, messages, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(email, session_id) DO UPDATE SET
            title = excluded.title,
            messages = excluded.messages,
            updated_at = excluded.updated_at
        """,
        (
            email,
            session_id,
            title[:200],
            json.dumps(messages),
            int(updated_at if updated_at is not None else time.time() * 1000),
        ),
    )
    await _enforce_cap(settings, email)


async def _enforce_cap(settings: Settings, email: str) -> None:
    """Drop the oldest sessions past the per-account cap. One account's
    chat history must not grow the table without bound."""
    await db.execute(
        settings,
        settings.chat_sessions_db_path,
        """
        DELETE FROM chat_sessions
        WHERE email = ? AND session_id NOT IN (
            SELECT session_id FROM chat_sessions
            WHERE email = ?
            ORDER BY updated_at DESC
            LIMIT ?
        )
        """,
        (email, email, settings.chat_sessions_max_per_account),
    )


async def delete_session(settings: Settings, email: str, session_id: str) -> None:
    await init_db(settings)
    email = _normalize(email)
    if not email or not session_id:
        return
    await db.execute(
        settings,
        settings.chat_sessions_db_path,
        "DELETE FROM chat_sessions WHERE email = ? AND session_id = ?",
        (email, session_id),
    )


async def replace_all(settings: Settings, email: str, sessions: list[SessionPayload]) -> None:
    """Bulk upsert used by the client's post-login merge sync - each local
    session gets pushed up so a chat started on this browser before the
    server ever knew about it (e.g. the very first sync after this feature
    shipped) doesn't get lost on the next device."""
    for session in sessions[: settings.chat_sessions_max_per_account]:
        await upsert_session(
            settings,
            email,
            session.get("id") or "",
            title=str(session.get("title") or "New chat"),
            messages=session.get("messages") or [],
            updated_at=session.get("updatedAt"),
        )
