"""Server-side chat history sync for signed-in accounts.

Regression context: found live Sep 14 - chats started while signed in on an
incognito window "disappeared" after signing back in, because history lived
only in that browser's localStorage, which incognito tears down when the
last incognito window closes. This makes the account the unit of
persistence instead.
"""
from __future__ import annotations

from api.identity import AuthenticatedUser
from api.routers import chat_sessions as chat_sessions_router
from api.services import chat_sessions


async def test_upsert_then_list_roundtrips_a_session(anon_settings):
    await chat_sessions.upsert_session(
        anon_settings,
        "Player@Example.com",
        "session-1",
        title="Best attack ninja build",
        messages=[{"role": "user", "content": "Best attack ninja build"}],
        updated_at=1000,
    )
    sessions = await chat_sessions.list_sessions(anon_settings, "player@example.com")
    assert len(sessions) == 1
    assert sessions[0]["id"] == "session-1"
    assert sessions[0]["title"] == "Best attack ninja build"
    assert sessions[0]["messages"] == [{"role": "user", "content": "Best attack ninja build"}]


async def test_upsert_overwrites_the_same_session_id(anon_settings):
    await chat_sessions.upsert_session(
        anon_settings, "a@b.com", "s1", title="First", messages=[], updated_at=1000
    )
    await chat_sessions.upsert_session(
        anon_settings, "a@b.com", "s1", title="Updated", messages=[{"role": "user"}], updated_at=2000
    )
    sessions = await chat_sessions.list_sessions(anon_settings, "a@b.com")
    assert len(sessions) == 1
    assert sessions[0]["title"] == "Updated"
    assert sessions[0]["updatedAt"] == 2000


async def test_sessions_are_isolated_per_account(anon_settings):
    await chat_sessions.upsert_session(
        anon_settings, "a@b.com", "s1", title="A's chat", messages=[], updated_at=1000
    )
    await chat_sessions.upsert_session(
        anon_settings, "c@d.com", "s2", title="C's chat", messages=[], updated_at=1000
    )
    a_sessions = await chat_sessions.list_sessions(anon_settings, "a@b.com")
    c_sessions = await chat_sessions.list_sessions(anon_settings, "c@d.com")
    assert [s["id"] for s in a_sessions] == ["s1"]
    assert [s["id"] for s in c_sessions] == ["s2"]


async def test_delete_session_removes_only_that_one(anon_settings):
    await chat_sessions.upsert_session(
        anon_settings, "a@b.com", "keep", title="Keep", messages=[], updated_at=1000
    )
    await chat_sessions.upsert_session(
        anon_settings, "a@b.com", "drop", title="Drop", messages=[], updated_at=2000
    )
    await chat_sessions.delete_session(anon_settings, "a@b.com", "drop")
    sessions = await chat_sessions.list_sessions(anon_settings, "a@b.com")
    assert [s["id"] for s in sessions] == ["keep"]


async def test_list_orders_newest_first(anon_settings):
    await chat_sessions.upsert_session(
        anon_settings, "a@b.com", "old", title="Old", messages=[], updated_at=1000
    )
    await chat_sessions.upsert_session(
        anon_settings, "a@b.com", "new", title="New", messages=[], updated_at=5000
    )
    sessions = await chat_sessions.list_sessions(anon_settings, "a@b.com")
    assert [s["id"] for s in sessions] == ["new", "old"]


async def test_replace_all_bulk_upserts_local_sessions(anon_settings):
    await chat_sessions.replace_all(
        anon_settings,
        "a@b.com",
        [
            {"id": "s1", "title": "First", "messages": [], "updatedAt": 1000},
            {"id": "s2", "title": "Second", "messages": [], "updatedAt": 2000},
        ],
    )
    sessions = await chat_sessions.list_sessions(anon_settings, "a@b.com")
    assert {s["id"] for s in sessions} == {"s1", "s2"}


async def test_cap_drops_oldest_sessions_past_the_limit(anon_settings):
    anon_settings.chat_sessions_max_per_account = 2
    for i in range(3):
        await chat_sessions.upsert_session(
            anon_settings, "a@b.com", f"s{i}", title=f"chat {i}", messages=[], updated_at=1000 + i
        )
    sessions = await chat_sessions.list_sessions(anon_settings, "a@b.com")
    assert len(sessions) == 2
    # The oldest (s0) was dropped; the two newest survive.
    assert {s["id"] for s in sessions} == {"s1", "s2"}


async def test_unknown_email_returns_no_sessions(anon_settings):
    assert await chat_sessions.list_sessions(anon_settings, "nobody@example.com") == []


# --- router-level: require_user gate -----------------------------------


def _user(email: str) -> AuthenticatedUser:
    return AuthenticatedUser(subject=email, email=email, claims={"email": email})


async def test_router_list_sessions_returns_this_users_sessions_only(anon_settings):
    await chat_sessions.upsert_session(
        anon_settings, "me@example.com", "mine", title="Mine", messages=[], updated_at=1000
    )
    await chat_sessions.upsert_session(
        anon_settings, "other@example.com", "theirs", title="Theirs", messages=[], updated_at=1000
    )
    result = await chat_sessions_router.list_sessions(anon_settings, _user("me@example.com"))
    assert [s.id for s in result.sessions] == ["mine"]


async def test_router_sync_pushes_local_sessions_then_returns_merged_list(anon_settings):
    from api.models.chat_session import ChatSessionPayload, ChatSessionSyncRequest

    # Server already has one session for this account from another device.
    await chat_sessions.upsert_session(
        anon_settings, "me@example.com", "server-only", title="Server", messages=[], updated_at=1000
    )
    payload = ChatSessionSyncRequest(
        sessions=[
            ChatSessionPayload(id="local-only", title="Local", messages=[], updatedAt=2000)
        ]
    )
    result = await chat_sessions_router.sync_sessions(
        payload, anon_settings, _user("me@example.com")
    )
    ids = {s.id for s in result.sessions}
    assert ids == {"server-only", "local-only"}


def test_postgres_ddl_widens_integer_to_bigint():
    from api.services.db import postgres_ddl

    widened = postgres_ddl(
        "CREATE TABLE chat_sessions (updated_at INTEGER NOT NULL)"
    )
    assert "BIGINT" in widened
    assert "INTEGER" not in widened
    # Do not turn BIGINT into BBIGINT on a second pass.
    assert postgres_ddl(widened) == widened
    assert "BYTEA" in postgres_ddl("data BYTEA NOT NULL, created_at INTEGER")


async def test_upsert_accepts_a_javascript_millisecond_timestamp(anon_settings):
    """The browser sends Date.now(), which overflows Postgres INTEGER."""
    stamp = 1_789_716_549_690
    await chat_sessions.upsert_session(
        anon_settings,
        "a@b.com",
        "s1",
        title="Live chat",
        messages=[],
        updated_at=stamp,
    )
    sessions = await chat_sessions.list_sessions(anon_settings, "a@b.com")
    assert sessions[0]["updatedAt"] == stamp
