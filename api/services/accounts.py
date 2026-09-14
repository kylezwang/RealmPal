"""
Local email+password accounts.

Magic links stay as a fallback (Forgot password / "email me a link"), but
the primary sign-in path is a password so we don't depend on a paid email
API. Entra External ID would send OTP mail as part of Azure's identity
service later; until that is wired, this store is the account.

Backed by `api/services/db.py`: SQLite locally (default), Postgres in any
deployment with `DATABASE_URL` set.

One row per email. Password is stored as PBKDF2-SHA256 (stdlib hashlib),
never plaintext. `create` refuses a duplicate; `verify` uses a dummy hash
when the email is unknown so a miss and a bad password take similar time.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional

from ..config import Settings
from . import db

_PBKDF2_ROUNDS = 210_000

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS accounts (
        email TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS preferences (
        email TEXT PRIMARY KEY,
        train_on_data INTEGER NOT NULL DEFAULT 1
    )
    """,
)
# Case-insensitive uniqueness on IGN, functional index so `LOWER(ign) =
# LOWER(?)` (used everywhere below instead of SQLite-only `COLLATE NOCASE`)
# hits an index on both backends. Run separately and best-effort: older
# local DBs can already have more than one row sharing an IGN from before
# this index existed, which would make creation fail - the app still works
# without it, just without the fast uniqueness check.
_IGN_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS accounts_ign_nocase "
    "ON accounts (LOWER(ign)) WHERE ign IS NOT NULL AND ign != ''"
)

# Kept for tests that reach past the public API to seed/mutate rows directly.
_connection = db.sqlite_connection

# Schema created lazily on first use per resolved path/DSN - see the same
# note in entitlements.py.
_ready: set[str] = set()


async def init_db(settings: Settings) -> None:
    key = settings.database_url.strip() or settings.accounts_db_path
    if key in _ready:
        return
    await db.run_ddl(settings, settings.accounts_db_path, _SCHEMA)
    await db.add_column_if_missing(settings, settings.accounts_db_path, "accounts", "ign", "TEXT")
    await db.run_ddl_safe(settings, settings.accounts_db_path, _IGN_INDEX)
    _ready.add(key)


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

    await init_db(settings)
    try:
        await db.execute(
            settings,
            settings.accounts_db_path,
            """
            INSERT INTO accounts (email, password_hash, ign, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (email, stored, ign or None, int(time.time())),
        )
        return True
    except db.UniqueViolation:
        return False


async def emails_for_ign(ign: str, settings: Settings) -> list[str]:
    """Every account that claims this IGN. Case-insensitive.

    Older local DBs can have more than one row (the unique index was added
    after the first test accounts). Sign-in must try each password rather
    than only the first row happens to come back first.
    """
    ign = (ign or "").strip()
    if not ign:
        return []

    await init_db(settings)
    rows = await db.fetchall(
        settings, settings.accounts_db_path,
        "SELECT email FROM accounts WHERE LOWER(ign) = LOWER(?)", (ign,),
    )
    return [row[0] for row in rows if row and row[0]]


async def email_for_ign(ign: str, settings: Settings) -> Optional[str]:
    """Resolve a stored IGN to the account email. Case-insensitive."""
    emails = await emails_for_ign(ign, settings)
    return emails[0] if emails else None


async def get_ign(email: str, settings: Settings) -> Optional[str]:
    email = _normalize(email)
    if not email:
        return None

    await init_db(settings)
    row = await db.fetchone(
        settings, settings.accounts_db_path,
        "SELECT ign FROM accounts WHERE email = ?", (email,),
    )
    return row[0] if row else None


async def verify(email: str, password: str, settings: Settings) -> bool:
    """True only if this email exists and the password matches."""
    email = _normalize(email)

    await init_db(settings)
    row = await db.fetchone(
        settings, settings.accounts_db_path,
        "SELECT password_hash FROM accounts WHERE email = ?", (email,),
    )
    stored = row[0] if row else None
    return _verify_password(password, stored or _DUMMY_HASH)


async def get_train_on_data(email: str, settings: Settings) -> bool:
    """Default on: no row means the user has not opted out."""
    email = _normalize(email)
    if not email:
        return True

    await init_db(settings)
    row = await db.fetchone(
        settings, settings.accounts_db_path,
        "SELECT train_on_data FROM preferences WHERE email = ?", (email,),
    )
    return True if row is None else bool(row[0])


async def set_train_on_data(email: str, value: bool, settings: Settings) -> bool:
    email = _normalize(email)
    if not email:
        return True
    flag = 1 if value else 0

    await init_db(settings)
    await db.execute(
        settings,
        settings.accounts_db_path,
        """
        INSERT INTO preferences (email, train_on_data) VALUES (?, ?)
        ON CONFLICT(email) DO UPDATE SET train_on_data = excluded.train_on_data
        """,
        (email, flag),
    )
    return bool(flag)
