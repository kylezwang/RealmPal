"""Admin role + notifications feed. The modal is not a user setting."""
from __future__ import annotations

import httpx

from api.auth import create_jwt
from api.config import get_settings
from api.dependencies import get_optional_user, get_redis
from api.identity import AuthenticatedUser
from api.main import create_app
from api.services import accounts, admin_events, entitlements, product_feedback
from api.services.admin_access import is_admin, jwt_role

CALLER = ("198.51.100.9", 44321)


def _client(redis_client, settings, user=None) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_settings] = lambda: settings
    if user is not None:
        app.dependency_overrides[get_optional_user] = lambda: user
    transport = httpx.ASGITransport(app=app, client=CALLER)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _user(email: str, ign: str) -> AuthenticatedUser:
    return AuthenticatedUser(
        subject=email,
        email=email,
        claims={"email": email, "ign": ign},
    )


async def test_turbine_ign_is_admin(anon_settings):
    assert await is_admin(_user("a@example.com", "Turbine"), anon_settings) is True
    assert await is_admin(_user("a@example.com", "turbine"), anon_settings) is True


async def test_other_ign_is_not_admin(anon_settings):
    assert await is_admin(_user("a@example.com", "SomeoneElse"), anon_settings) is False
    assert await is_admin(None, anon_settings) is False


async def test_admin_email_grants_access_without_ign(tmp_path):
    from api.config import Settings

    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key-not-real",
        jwt_secret="test-jwt-secret",
        pii_hash_secret="test-pii-secret",
        entitlements_db_path=str(tmp_path / "entitlements.db"),
        accounts_db_path=str(tmp_path / "accounts.db"),
        uploads_db_path=str(tmp_path / "uploads.db"),
        chat_sessions_db_path=str(tmp_path / "chat_sessions.db"),
        product_feedback_db_path=str(tmp_path / "product_feedback.db"),
        admin_events_db_path=str(tmp_path / "admin_events.db"),
        admin_igns="",
        admin_emails="ops@example.com",
    )
    assert await is_admin(_user("ops@example.com", "NotAdmin"), settings) is True
    assert await is_admin(_user("other@example.com", "NotAdmin"), settings) is False


async def test_jwt_role_is_admin_for_turbine(anon_settings):
    assert await jwt_role("a@example.com", "Turbine", anon_settings) == "admin"
    assert await jwt_role("a@example.com", "SomeoneElse", anon_settings) == "user"


async def test_guest_cannot_read_notifications(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.get("/admin/notifications")
    assert response.status_code == 403


async def test_non_admin_cannot_read_notifications(redis_client, anon_settings):
    async with _client(
        redis_client, anon_settings, user=_user("player@example.com", "NotTurbine")
    ) as http:
        response = await http.get("/admin/notifications")
    assert response.status_code == 403


async def test_usage_sets_is_admin_for_turbine(redis_client, anon_settings):
    async with _client(
        redis_client, anon_settings, user=_user("player@example.com", "Turbine")
    ) as http:
        body = (await http.get("/chat/usage")).json()
    assert body["is_admin"] is True


async def test_usage_hides_admin_for_other_accounts(redis_client, anon_settings):
    async with _client(
        redis_client, anon_settings, user=_user("player@example.com", "NotTurbine")
    ) as http:
        body = (await http.get("/chat/usage")).json()
    assert body["is_admin"] is False


async def test_feedback_reply_template_fills_submitter():
    draft = admin_events.feedback_reply_template(
        {
            "email": "player@example.com",
            "ign": "Nolan",
            "rating": "okay",
            "what_works": "Farm guides",
            "what_to_improve": "More biomes",
            "anything_else": "Thanks",
        }
    )
    assert draft["reply_email"] == "player@example.com"
    assert "Hi Nolan" in draft["reply_body"]
    assert "Farm guides" in draft["reply_body"]
    assert "More biomes" in draft["reply_body"]
    assert draft["mailto"].startswith("mailto:player@example.com?")
    assert "subject=" in draft["mailto"]
    empty = admin_events.feedback_reply_template({"email": "", "ign": "Guest"})
    assert empty["mailto"] == ""
    assert empty["reply_email"] is None


async def test_admin_feed_merges_existing_stores(redis_client, anon_settings):
    admin_events.reset_ready_for_tests()
    product_feedback.reset_ready_for_tests()
    await accounts.create("new@example.com", "long-enough", anon_settings, ign="Rogue")
    await product_feedback.insert_feedback(
        anon_settings,
        rating="great",
        what_works="Sprites",
        what_to_improve="Dungeon loot",
        anything_else="",
        email="fan@example.com",
        ign="Fan",
    )
    await entitlements.upsert(
        "paid@example.com",
        status="active",
        settings=anon_settings,
        stripe_subscription_id="sub_test_1",
    )
    await admin_events.record_chat_turn(
        anon_settings,
        tier="guest",
        cost_usd=0.0134,
        email=None,
        ign=None,
    )
    await admin_events.record_chat_turn(
        anon_settings,
        tier="paid",
        cost_usd=0.04,
        email="paid@example.com",
        ign="Rogue",
    )

    async with _client(
        redis_client, anon_settings, user=_user("admin@example.com", "Turbine")
    ) as http:
        response = await http.get("/admin/notifications")
    assert response.status_code == 200
    body = response.json()
    assert "spend_today_usd" in body
    assert "spend_budget_usd" in body
    kinds = {item["kind"] for item in body["items"]}
    assert kinds == {"chat", "feedback", "account", "subscription"}
    chats = [item for item in body["items"] if item["kind"] == "chat"]
    assert any(item["tier"] == "guest" and abs(float(item["cost_usd"]) - 0.0134) < 1e-6 for item in chats)
    assert any(item["tier"] == "paid" and item["email"] == "paid@example.com" for item in chats)
    feedback = next(item for item in body["items"] if item["kind"] == "feedback")
    assert feedback["email"] == "fan@example.com"
    assert feedback["mailto"].startswith("mailto:fan@example.com?")
    assert "Dungeon loot" in feedback["reply_body"]
    account = next(item for item in body["items"] if item["kind"] == "account")
    assert account["ign"] == "Rogue"
    sub = next(item for item in body["items"] if item["kind"] == "subscription")
    assert sub["stripe_subscription_id"] == "sub_test_1"
    assert sub["status"] == "active"


async def test_register_turbine_session_includes_admin_role(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        created = await http.post(
            "/auth/register",
            json={
                "email": "founder@example.com",
                "password": "long-enough",
                "confirm_password": "long-enough",
                "ign": "Turbine",
            },
        )
        other = await http.post(
            "/auth/register",
            json={
                "email": "player@example.com",
                "password": "long-enough",
                "confirm_password": "long-enough",
                "ign": "NotTurbine",
            },
        )
    assert created.status_code == 200
    assert created.json()["role"] == "admin"
    assert other.status_code == 200
    assert other.json()["role"] == "user"
    token = create_jwt(
        {"email": "spy@example.com", "ign": "NotTurbine", "role": "admin"},
        anon_settings,
    )
    async with _client(redis_client, anon_settings) as http:
        forged = await http.get(
            "/admin/notifications",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert forged.status_code == 403


def test_notifications_modal_is_admin_gated_not_a_route():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    menu = (root / "web" / "components" / "chat" / "AccountMenu.tsx").read_text(
        encoding="utf-8"
    )
    modal = (
        root / "web" / "components" / "chat" / "AdminNotificationsModal.tsx"
    ).read_text(encoding="utf-8")
    page = (root / "web" / "app" / "account" / "notifications" / "page.tsx").read_text(
        encoding="utf-8"
    )
    assert "usage?.is_admin" in menu
    assert "AdminNotificationsModal" in menu
    assert 'router.push("/account/notifications")' not in menu
    assert "Reply by email" in modal
    assert "fetchAdminNotifications" in modal
    assert "createPortal" in modal
    assert "router.replace" not in page
    assert "useRouter" not in page


def test_stale_chunk_error_boundary_exists_and_self_heals():
    """A stale chunk after a deploy left every button dead with no UI at all."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    boundary = root / "web" / "app" / "global-error.tsx"
    assert boundary.exists(), "output: export needs a global-error boundary"
    text = boundary.read_text(encoding="utf-8")
    assert "ChunkLoadError" in text
    assert "window.location.reload" in text
    # Reload must be rate-limited, or a genuinely broken build loops forever.
    assert "sessionStorage" in text
    assert "RELOAD_COOLDOWN_MS" in text


def test_oldest_changelog_block_splits_into_prelaunch_phase():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    text = (root / "web" / "lib" / "changelog.ts").read_text(encoding="utf-8")
    modal = (root / "web" / "components" / "chat" / "ChangelogModal.tsx").read_text(
        encoding="utf-8"
    )
    sep13 = text.split('version: "2026.09.13"', 1)[1].split("version:", 1)[0]
    bullets = sep13.count('\n      "')
    assert 18 <= bullets <= 24
    assert 'version: "prelaunch"' in text
    assert "Development phases before going live" in text
    assert "phase: true" in text
    assert "entry.phase" in modal


def test_markdown_paragraph_children_are_inline_elements():
    """Regression: an item token inside a markdown paragraph rendered a <div>
    inside a <p>, which is invalid HTML the browser reparents, so every reply
    containing an item threw two hydration errors."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sprite = (root / "web" / "components" / "chat" / "SpriteZoom.tsx").read_text(
        encoding="utf-8"
    )
    trigger = sprite.split("export function SpriteZoomTrigger", 1)[1]
    # The anchor and its popover menu sit inside a paragraph, so both are spans.
    assert "<span ref={anchorRef}" in trigger
    assert "<div ref={anchorRef}" not in trigger
    assert "ref={menuRef}" in trigger
    assert "<div\n            ref={menuRef}" not in trigger
    assert "useRef<HTMLSpanElement>" in sprite
    # The full-size overlay is portaled out, so it may stay a div.
    assert "createPortal" in sprite
