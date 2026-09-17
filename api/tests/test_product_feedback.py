"""Header Feedback modal writes a scannable product_feedback row."""
from __future__ import annotations

import httpx

from api.config import get_settings
from api.dependencies import get_optional_user, get_redis
from api.identity import AuthenticatedUser
from api.main import create_app
from api.services import product_feedback

CALLER = ("198.51.100.9", 44321)


def _client(redis_client, settings, user=None) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_settings] = lambda: settings
    if user is not None:
        app.dependency_overrides[get_optional_user] = lambda: user
    transport = httpx.ASGITransport(app=app, client=CALLER)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_insert_roundtrips_a_row(anon_settings):
    row = await product_feedback.insert_feedback(
        anon_settings,
        rating="great",
        what_works="Farm guides are fast",
        what_to_improve="Need more biomes",
        anything_else="Love it",
        email="Player@Example.com",
        ign="Turbine",
    )
    listed = await product_feedback.list_recent(anon_settings)
    assert len(listed) == 1
    assert listed[0]["id"] == row["id"]
    assert listed[0]["rating"] == "great"
    assert listed[0]["what_works"] == "Farm guides are fast"
    assert listed[0]["what_to_improve"] == "Need more biomes"
    assert listed[0]["anything_else"] == "Love it"
    assert listed[0]["email"] == "player@example.com"
    assert listed[0]["ign"] == "Turbine"
    assert listed[0]["created_at"]


async def test_site_feedback_persists_for_a_guest(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post(
            "/chat/site-feedback",
            json={
                "rating": "okay",
                "what_works": "Item sprites",
                "what_to_improve": "",
                "anything_else": "",
            },
        )
    assert response.status_code == 200
    rows = await product_feedback.list_recent(anon_settings)
    assert len(rows) == 1
    assert rows[0]["rating"] == "okay"
    assert rows[0]["what_works"] == "Item sprites"
    assert rows[0]["email"] is None


async def test_site_feedback_attaches_signed_in_email(redis_client, anon_settings):
    user = AuthenticatedUser(
        subject="user-1",
        email="me@example.com",
        claims={"email": "me@example.com"},
    )
    async with _client(redis_client, anon_settings, user=user) as http:
        response = await http.post(
            "/chat/site-feedback",
            json={
                "rating": "rough",
                "what_works": "",
                "what_to_improve": "Wrong dungeon advice",
                "anything_else": "",
                "ign": "Turbine",
            },
        )
    assert response.status_code == 200
    rows = await product_feedback.list_recent(anon_settings)
    assert rows[0]["email"] == "me@example.com"
    assert rows[0]["ign"] == "Turbine"
    assert rows[0]["what_to_improve"] == "Wrong dungeon advice"


async def test_empty_answers_are_rejected(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post(
            "/chat/site-feedback",
            json={"rating": "great", "what_works": "  ", "what_to_improve": ""},
        )
    assert response.status_code == 400
    assert await product_feedback.list_recent(anon_settings) == []


async def test_rate_limit_caps_repeat_submits(redis_client, anon_settings):
    anon_settings.product_feedback_limit = 1
    payload = {
        "rating": "great",
        "what_works": "Speed",
        "what_to_improve": "",
        "anything_else": "",
    }
    async with _client(redis_client, anon_settings) as http:
        first = await http.post("/chat/site-feedback", json=payload)
        second = await http.post("/chat/site-feedback", json=payload)
    assert first.status_code == 200
    assert second.status_code == 429
    assert len(await product_feedback.list_recent(anon_settings)) == 1


def test_header_feedback_replaces_quota_chip():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    header = (root / "web" / "components" / "chat" / "ChatInterface.tsx").read_text(
        encoding="utf-8"
    )
    sidebar = (root / "web" / "components" / "chat" / "ChatSidebar.tsx").read_text(
        encoding="utf-8"
    )
    modal = (root / "web" / "components" / "chat" / "FeedbackModal.tsx").read_text(
        encoding="utf-8"
    )
    assert "freeInDepthPromptsLeft" not in header
    assert "FeedbackModal" in header
    assert "onOpenFeedback" in sidebar
    assert "freeInDepthPromptsLeft" not in sidebar
    assert "How has RealmPal been" in modal
    assert "sendSiteFeedback" in modal
    menu = (root / "web" / "components" / "chat" / "AccountMenu.tsx").read_text(
        encoding="utf-8"
    )
    assert "freeInDepthPromptsLeft" in menu
    assert "onOpenPaywall" in menu
    assert "showsFreeInDepthQuota" in menu


def test_mobile_hides_skin_look_suggestion():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    prompts = (root / "web" / "lib" / "examplePrompts.ts").read_text(encoding="utf-8")
    leftover = (root / "web" / "components" / "chat" / "LeftoverAskBar.tsx").read_text(
        encoding="utf-8"
    )
    chat = (root / "web" / "components" / "chat" / "ChatInterface.tsx").read_text(
        encoding="utf-8"
    )
    assert 'SKIN_LOOK_PROMPT_ID = "skin-look"' in prompts
    assert "hidden min-w-0 md:block" in prompts
    assert "examplePromptShellClass" in leftover
    assert "grid-cols-3 md:grid-cols-4" in leftover
    assert "examplePromptShellClass" not in chat
