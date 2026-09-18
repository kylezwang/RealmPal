"""
Shared storage backend for the small local stores (accounts, entitlements,
uploads, billing prefs).

Two backends behind one tiny interface, chosen once via `settings.
database_url`:

- SQLite (default, `DATABASE_URL` unset): one file under `data/`, zero
  extra infra to run, what local dev and tests use.
- Postgres (`DATABASE_URL` set, e.g. Azure Database for PostgreSQL in a
  deployment): durable across container restarts/redeploys and safe with
  more than one replica writing at once, unlike SQLite on a shared volume.
  BACKLOG.md originally planned "SQLite on a mounted volume until billing
  lands, then Postgres" - billing landed Sep 13, 2026, this module is that
  migration.

Every call site writes queries with `?` placeholders (SQLite's style).
`execute`/`fetchone`/`fetchall`/`execute_returning` rewrite them to
Postgres's `$1, $2, ...` under the hood, so the same query string works
unmodified on both backends instead of every store carrying two copies of
every query. The one thing that isn't portable across both engines is a
handful of DDL statements (SQLite's `BLOB` vs Postgres's `BYTEA`); callers
pass `postgres_statements` to `run_ddl` only where that matters.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional, Sequence

try:
    import asyncpg
except ImportError:  # pragma: no cover - only required when DATABASE_URL is set
    asyncpg = None  # type: ignore[assignment]

from ..config import Settings


class UniqueViolation(Exception):
    """A write hit a UNIQUE/PRIMARY KEY constraint, on either backend."""


_QMARK = re.compile(r"\?")
# SQLite INTEGER is 64-bit. Postgres INTEGER is int32. A JS Date.now()
# millisecond timestamp (e.g. 1_789_716_549_690) overflows int32 and 500s
# chat-session sync. Found live Sep 18 on POST /chat/sessions/sync.
_SQLITE_INTEGER = re.compile(r"\bINTEGER\b", re.I)


def _pg_placeholders(query: str) -> str:
    """Rewrite `?` positional placeholders to Postgres's `$1, $2, ...`."""
    n = 0

    def _sub(_match: "re.Match[str]") -> str:
        nonlocal n
        n += 1
        return f"${n}"

    return _QMARK.sub(_sub, query)


def postgres_ddl(statement: str) -> str:
    """Same CREATE/ALTER text, with INTEGER widened to BIGINT.

    Callers write SQLite DDL. SQLite INTEGER holds a millisecond timestamp;
    Postgres INTEGER does not. BIGINT is the Postgres type that matches.
    """
    return _SQLITE_INTEGER.sub("BIGINT", statement)


def is_postgres(settings: Settings) -> bool:
    return bool(settings.database_url.strip())


# --- SQLite backend ---------------------------------------------------------

_sqlite_conns: dict[str, sqlite3.Connection] = {}
_sqlite_write_lock = asyncio.Lock()


def sqlite_connection(db_path: str) -> sqlite3.Connection:
    """One cached connection per resolved file path, WAL mode. Kept as a
    module-level function (not folded into `execute`) because a few tests
    reach in directly to seed/mutate rows the API doesn't expose."""
    resolved = str(Path(db_path).resolve())
    conn = _sqlite_conns.get(resolved)
    if conn is not None:
        return conn

    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    _sqlite_conns[resolved] = conn
    return conn


# --- Postgres backend --------------------------------------------------------

_pg_pools: dict[str, Any] = {}
_pg_pool_lock = asyncio.Lock()


async def pg_pool(database_url: str):
    if asyncpg is None:
        raise RuntimeError(
            "DATABASE_URL is set but asyncpg is not installed. "
            "Add asyncpg to api/requirements.txt and reinstall."
        )
    pool = _pg_pools.get(database_url)
    if pool is not None:
        return pool
    async with _pg_pool_lock:
        pool = _pg_pools.get(database_url)
        if pool is not None:
            return pool
        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=8)
        _pg_pools[database_url] = pool
        return pool


# --- Unified calls ------------------------------------------------------

async def run_ddl(
    settings: Settings,
    db_path: str,
    statements: Sequence[str],
    *,
    postgres_statements: Optional[Sequence[str]] = None,
) -> None:
    """Run schema statements at startup (CREATE TABLE / CREATE INDEX)."""
    stmts = postgres_statements if (is_postgres(settings) and postgres_statements is not None) else statements

    if is_postgres(settings):
        pool = await pg_pool(settings.database_url)
        async with pool.acquire() as conn:
            for stmt in stmts:
                await conn.execute(postgres_ddl(stmt))
            await widen_existing_integers(conn)
        return

    def _run() -> None:
        conn = sqlite_connection(db_path)
        for stmt in stmts:
            conn.execute(stmt)

    async with _sqlite_write_lock:
        await asyncio.to_thread(_run)


async def run_ddl_safe(settings: Settings, db_path: str, statement: str) -> None:
    """Same as `run_ddl` for one statement, but swallows a constraint
    violation instead of raising - used for the IGN unique index, which can
    fail if older rows already share an IGN. Best-effort: the app still
    works without that index, just without the fast uniqueness check."""
    try:
        await run_ddl(settings, db_path, (statement,))
    except sqlite3.IntegrityError:
        pass
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        if asyncpg is not None and isinstance(exc, asyncpg.PostgresError):
            pass
        else:
            raise


async def add_column_if_missing(
    settings: Settings, db_path: str, table: str, column: str, coltype: str
) -> None:
    """Portable `ALTER TABLE ... ADD COLUMN` for a column that might
    already exist. Postgres supports `ADD COLUMN IF NOT EXISTS` directly;
    SQLite does not (only CREATE TABLE/INDEX/VIEW/TRIGGER take IF NOT
    EXISTS), so on that backend check `PRAGMA table_info` first. `table`/
    `column`/`coltype` are always internal literals, never user input."""
    if is_postgres(settings):
        pool = await pg_pool(settings.database_url)
        async with pool.acquire() as conn:
            await conn.execute(
                postgres_ddl(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype}"
                )
            )
        return

    def _run() -> None:
        conn = sqlite_connection(db_path)
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")

    async with _sqlite_write_lock:
        await asyncio.to_thread(_run)


async def widen_existing_integers(conn: Any) -> None:
    """ALTER leftover int32 columns on tables created before INTEGER was
    rewritten to BIGINT. CREATE TABLE IF NOT EXISTS does not change types.
    Column names come from information_schema, never from the request."""
    rows = await conn.fetch(
        """
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
          AND data_type = 'integer'
        """
    )
    for row in rows:
        schema = row["table_schema"]
        table = row["table_name"]
        column = row["column_name"]
        await conn.execute(
            f'ALTER TABLE "{schema}"."{table}" ALTER COLUMN "{column}" TYPE BIGINT'
        )


async def execute(settings: Settings, db_path: str, query: str, params: tuple = ()) -> None:
    if is_postgres(settings):
        pool = await pg_pool(settings.database_url)
        try:
            async with pool.acquire() as conn:
                await conn.execute(_pg_placeholders(query), *params)
        except asyncpg.UniqueViolationError as exc:  # type: ignore[union-attr]
            raise UniqueViolation(str(exc)) from exc
        return

    def _run() -> None:
        conn = sqlite_connection(db_path)
        try:
            conn.execute(query, params)
        except sqlite3.IntegrityError as exc:
            raise UniqueViolation(str(exc)) from exc

    async with _sqlite_write_lock:
        await asyncio.to_thread(_run)


async def execute_returning(
    settings: Settings, db_path: str, query: str, params: tuple = ()
) -> Optional[tuple]:
    """Like `execute`, but for an UPDATE/INSERT ... RETURNING statement -
    keeps a read-then-write pair atomic under one lock/transaction instead
    of racing a separate SELECT against the write."""
    if is_postgres(settings):
        pool = await pg_pool(settings.database_url)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(_pg_placeholders(query), *params)
            return tuple(row.values()) if row is not None else None

    def _run() -> Optional[tuple]:
        conn = sqlite_connection(db_path)
        row = conn.execute(query, params).fetchone()
        return tuple(row) if row is not None else None

    async with _sqlite_write_lock:
        return await asyncio.to_thread(_run)


async def fetchone(settings: Settings, db_path: str, query: str, params: tuple = ()) -> Optional[tuple]:
    if is_postgres(settings):
        pool = await pg_pool(settings.database_url)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(_pg_placeholders(query), *params)
            return tuple(row.values()) if row is not None else None

    def _run() -> Optional[tuple]:
        conn = sqlite_connection(db_path)
        row = conn.execute(query, params).fetchone()
        return tuple(row) if row is not None else None

    return await asyncio.to_thread(_run)


async def fetchall(settings: Settings, db_path: str, query: str, params: tuple = ()) -> list[tuple]:
    if is_postgres(settings):
        pool = await pg_pool(settings.database_url)
        async with pool.acquire() as conn:
            rows = await conn.fetch(_pg_placeholders(query), *params)
            return [tuple(r.values()) for r in rows]

    def _run() -> list[tuple]:
        conn = sqlite_connection(db_path)
        return [tuple(r) for r in conn.execute(query, params).fetchall()]

    return await asyncio.to_thread(_run)
