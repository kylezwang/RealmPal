"""
Local email+password accounts.

Magic links stay as a fallback (Forgot password / "email me a link"), but
the primary sign-in path is a password so we don't depend on a paid email
API. Entra External ID would send OTP mail as part of Azure's identity
service later; until that is wired, this SQLite store is the account.

One row per email. Password is stored as PBKDF2-SHA256 (stdlib hashlib),
never plaintext. `create` refuses a duplicate; `verify` uses a dummy hash
when the email is unknown so a miss and a bad password take similar time.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

from ..config import Settings

_PBKDF2_ROUNDS = 210_000
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
        CREATE TABLE IF NOT EXISTS accounts (
            email TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            ign TEXT,
            created_at INTEGER NOT NULL
        )
        """
    )
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()
    }
    if "ign" not in columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN ign TEXT")
    try:
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS accounts_ign_nocase
            ON accounts (ign COLLATE NOCASE)
            WHERE ign IS NOT NULL AND ign != ''
            """
        )
    except sqlite3.IntegrityError:
        # Older rows may share an IGN; lookup still works without the index.
        pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preferences (
            email TEXT PRIMARY KEY,
            train_on_data INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    _connections[resolved] = conn
    return conn


async def init_db(settings: Settings) -> None:
    await asyncio.to_thread(_connection, settings.accounts_db_path)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds_s, salt_hex, digest_hex = stored.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    try:
        rounds = int(rounds_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(actual, expected)


# Precomputed so a missing-email lookup still pays a PBKDF2 cost.
_DUMMY_HASH = hash_password("not-a-real-password")


def _normalize(email: str) -> str:
    return (email or "").strip().lower()


async def create(
    email: str, password: str, settings: Settings, *, ign: str = ""
) -> bool:
    """Insert a new account. Returns False if the email is already taken."""
    email = _normalize(email)
    if not email:
        return False
    stored = hash_password(password)
    ign = (ign or "").strip()

    def _write() -> bool:
        conn = _connection(settings.accounts_db_path)
        try:
            conn.execute(
                """
                INSERT INTO accounts (email, password_hash, ign, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (email, stored, ign or None, int(time.time())),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    async with _write_lock:
        return await asyncio.to_thread(_write)


async def emails_for_ign(ign: str, settings: Settings) -> list[str]:
    """Every account that claims this IGN. Case-insensitive.

    Older local DBs can have more than one row (the unique index was added
    after the first test accounts). Sign-in must try each password rather
    than only the first row SQLite happens to return.
    """
    ign = (ign or "").strip()
    if not ign:
        return []

    def _read() -> list[str]:
        conn = _connection(settings.accounts_db_path)
        rows = conn.execute(
            "SELECT email FROM accounts WHERE ign = ? COLLATE NOCASE",
            (ign,),
        ).fetchall()
        return [row[0] for row in rows if row and row[0]]

    return await asyncio.to_thread(_read)


async def email_for_ign(ign: str, settings: Settings) -> Optional[str]:
    """Resolve a stored IGN to the account email. Case-insensitive."""
    emails = await emails_for_ign(ign, settings)
    return emails[0] if emails else None


async def get_ign(email: str, settings: Settings) -> Optional[str]:
    email = _normalize(email)
    if not email:
        return None

    def _read() -> Optional[str]:
        conn = _connection(settings.accounts_db_path)
        row = conn.execute(
            "SELECT ign FROM accounts WHERE email = ?", (email,)
        ).fetchone()
        return row[0] if row else None

    return await asyncio.to_thread(_read)


async def verify(email: str, password: str, settings: Settings) -> bool:
    """True only if this email exists and the password matches."""
    email = _normalize(email)

    def _read() -> Optional[str]:
        conn = _connection(settings.accounts_db_path)
        row = conn.execute(
            "SELECT password_hash FROM accounts WHERE email = ?", (email,)
        ).fetchone()
        return row[0] if row else None

    stored = await asyncio.to_thread(_read)
    return _verify_password(password, stored or _DUMMY_HASH)


async def get_train_on_data(email: str, settings: Settings) -> bool:
    """Default on: no row means the user has not opted out."""
    email = _normalize(email)
    if not email:
        return True

    def _read() -> bool:
        conn = _connection(settings.accounts_db_path)
        row = conn.execute(
            "SELECT train_on_data FROM preferences WHERE email = ?", (email,)
        ).fetchone()
        return True if row is None else bool(row[0])

    return await asyncio.to_thread(_read)


async def set_train_on_data(email: str, value: bool, settings: Settings) -> bool:
    email = _normalize(email)
    if not email:
        return True
    flag = 1 if value else 0

    def _write() -> bool:
        conn = _connection(settings.accounts_db_path)
        conn.execute(
            """
            INSERT INTO preferences (email, train_on_data) VALUES (?, ?)
            ON CONFLICT(email) DO UPDATE SET train_on_data = excluded.train_on_data
            """,
            (email, flag),
        )
        return bool(flag)

    async with _write_lock:
        return await asyncio.to_thread(_write)
