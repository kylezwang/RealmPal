from api.auth import create_jwt
from api.config import Settings
from api.identity import AuthenticatedUser
from api.services.dev_access import is_debug_unlimited


def _settings(tmp_path, *, debug: bool) -> Settings:
    return Settings(
        _env_file=None,
        anthropic_api_key="test-key-not-real",
        jwt_secret="test-jwt-secret",
        pii_hash_secret="test-pii-secret",
        entitlements_db_path=str(tmp_path / "entitlements.db"),
        accounts_db_path=str(tmp_path / "accounts.db"),
        uploads_db_path=str(tmp_path / "uploads.db"),
        debug=debug,
        debug_unlimited_igns="Turbine",
    )


async def test_turbine_is_unlimited_only_while_debug(tmp_path):
    user = AuthenticatedUser(
        subject="player@example.com",
        email="player@example.com",
        claims={"email": "player@example.com", "ign": "Turbine"},
    )
    assert await is_debug_unlimited(user, _settings(tmp_path, debug=True)) is True
    assert await is_debug_unlimited(user, _settings(tmp_path, debug=False)) is False


async def test_other_igns_stay_metered_even_in_debug(tmp_path):
    user = AuthenticatedUser(
        subject="player@example.com",
        email="player@example.com",
        claims={"email": "player@example.com", "ign": "NotTurbine"},
    )
    assert await is_debug_unlimited(user, _settings(tmp_path, debug=True)) is False


async def test_ign_match_is_case_insensitive(tmp_path):
    user = AuthenticatedUser(
        subject="player@example.com",
        email="player@example.com",
        claims={"email": "player@example.com", "ign": "turbine"},
    )
    assert await is_debug_unlimited(user, _settings(tmp_path, debug=True)) is True


async def test_usage_hides_the_free_counter_for_debug_turbine(
    redis_client, tmp_path, monkeypatch
):
    from httpx import ASGITransport, AsyncClient

    from api.dependencies import get_redis
    from api.main import create_app
    from api.config import get_settings

    settings = _settings(tmp_path, debug=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_settings] = lambda: settings
    token = create_jwt(
        {"email": "player@example.com", "ign": "Turbine"}, settings
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        body = (
            await http.get(
                "/chat/usage", headers={"Authorization": f"Bearer {token}"}
            )
        ).json()
    assert body["remaining"] == settings.paid_message_limit
    assert body["scope"] == "user"
