"""
Chat backend selection: Microsoft Foundry vs direct Anthropic fallback.

These cases are why api/services/llm.py exists. A poisoned FOUNDRY_BASE_URL
would send player prompts (IGN lookups, scraped profiles) off Azure. Mixing
the OpenAI-shaped Foundry path produces 404s. Entra and a Foundry key must
not both be sent. Direct Anthropic stays available until the resource exists.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.config import Settings
from api.services.llm import (
    LlmConfigError,
    build_chat_client,
    validate_foundry_target,
)


def _settings(**overrides) -> Settings:
    base = {
        "anthropic_api_key": "test-key-not-real",
        "jwt_secret": "test-jwt-secret",
        "pii_hash_secret": "test-pii-secret",
    }
    base.update(overrides)
    # _env_file=None: these assert exact provider selection off explicit
    # overrides only, so they must not inherit Foundry/JWT values a developer
    # happens to have in their real .env.
    return Settings(_env_file=None, **base)


# --- target allowlist -----------------------------------------------------


def test_foundry_resource_name_is_accepted():
    validate_foundry_target(resource="realmpal-foundry")


def test_foundry_base_url_is_accepted():
    validate_foundry_target(
        base_url="https://realmpal-foundry.services.ai.azure.com/anthropic"
    )
    validate_foundry_target(
        base_url="https://realmpal-foundry.services.ai.azure.com/anthropic/"
    )


@pytest.mark.parametrize(
    "resource",
    [
        "https://evil.example/anthropic",
        "realmpal.services.ai.azure.com",
        "../openai",
        "a b",
        "",
        "x" * 80,
    ],
)
def test_malformed_resource_names_are_rejected(resource):
    with pytest.raises(LlmConfigError):
        validate_foundry_target(resource=resource)


@pytest.mark.parametrize(
    "url",
    [
        "http://realmpal.services.ai.azure.com/anthropic",
        "https://evil.example/anthropic",
        "https://realmpal.services.ai.azure.com.evil.example/anthropic",
        "https://realmpal.services.ai.azure.com/openai/deployments/claude",
        "https://realmpal.services.ai.azure.com/anthropic?steal=1",
        "https://user:pass@realmpal.services.ai.azure.com/anthropic",
        "https://realmpal.services.ai.azure.com:8443/anthropic",
        "https://realmpal.services.ai.azure.com/anthropic/../openai",
        "https://127.0.0.1/anthropic",
    ],
)
def test_foundry_base_url_cannot_be_steered_off_azure(url):
    with pytest.raises(LlmConfigError):
        validate_foundry_target(base_url=url)


def test_resource_and_base_url_together_are_rejected():
    with pytest.raises(LlmConfigError):
        validate_foundry_target(
            resource="realmpal",
            base_url="https://realmpal.services.ai.azure.com/anthropic",
        )


# --- settings selection ---------------------------------------------------


def test_direct_anthropic_is_the_local_fallback():
    settings = _settings()
    assert settings.llm_provider == "anthropic"
    assert settings.foundry_configured is False
    assert settings.foundry_auth == ""


def test_foundry_resource_selects_foundry_over_a_leftover_anthropic_key():
    settings = _settings(
        foundry_resource="realmpal-foundry",
        foundry_api_key="foundry-key-not-real",
        anthropic_api_key="sk-ant-should-not-be-sent",
        prefer_anthropic=False,
    )
    assert settings.llm_provider == "foundry"
    assert settings.foundry_auth == "api_key"


def test_prefer_anthropic_uses_the_local_key_even_when_foundry_is_set():
    settings = _settings(
        foundry_resource="realmpal-foundry",
        foundry_api_key="foundry-key-not-real",
        anthropic_api_key="sk-ant-dev-key",
        prefer_anthropic=True,
    )
    assert settings.llm_provider == "anthropic"


def test_foundry_entra_does_not_need_a_foundry_key():
    settings = _settings(
        foundry_resource="realmpal-foundry",
        foundry_use_entra=True,
        anthropic_api_key="",
    )
    assert settings.llm_provider == "foundry"
    assert settings.foundry_auth == "entra"


def test_foundry_without_credentials_fails_closed():
    with pytest.raises(ValidationError, match="FOUNDRY_USE_ENTRA"):
        _settings(
            foundry_resource="realmpal-foundry",
            anthropic_api_key="",
        )


def test_entra_and_foundry_key_are_mutually_exclusive():
    with pytest.raises(ValidationError, match="mutually exclusive"):
        _settings(
            foundry_resource="realmpal-foundry",
            foundry_use_entra=True,
            foundry_api_key="foundry-key-not-real",
        )


def test_resource_and_base_url_settings_are_mutually_exclusive():
    with pytest.raises(ValidationError, match="mutually exclusive"):
        _settings(
            foundry_resource="realmpal-foundry",
            foundry_base_url="https://realmpal-foundry.services.ai.azure.com/anthropic",
            foundry_api_key="foundry-key-not-real",
        )


def test_missing_llm_credentials_fail_closed():
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        _settings(anthropic_api_key="")


def test_poisoned_foundry_url_is_rejected_at_settings_load():
    with pytest.raises(ValidationError, match="FOUNDRY_BASE_URL"):
        _settings(
            foundry_base_url="https://evil.example/anthropic",
            foundry_api_key="foundry-key-not-real",
            anthropic_api_key="",
        )


# --- client construction --------------------------------------------------


def test_direct_client_uses_the_anthropic_key_and_not_foundry(monkeypatch):
    captured: dict = {}

    class FakeAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("api.services.llm.AsyncAnthropic", FakeAnthropic)
    client = build_chat_client(_settings())
    assert isinstance(client, FakeAnthropic)
    assert captured["api_key"] == "test-key-not-real"


def test_foundry_key_client_does_not_forward_the_anthropic_key(monkeypatch):
    captured: dict = {}

    class FakeFoundry:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("anthropic.AsyncAnthropicFoundry", FakeFoundry)
    settings = _settings(
        foundry_resource="realmpal-foundry",
        foundry_api_key="foundry-key-not-real",
        anthropic_api_key="sk-ant-should-not-be-sent",
        prefer_anthropic=False,
    )
    client = build_chat_client(settings)
    assert isinstance(client, FakeFoundry)
    assert captured["api_key"] == "foundry-key-not-real"
    assert captured["resource"] == "realmpal-foundry"
    assert "azure_ad_token_provider" not in captured
    assert captured["api_key"] != settings.anthropic_api_key


def test_foundry_entra_client_sends_no_api_key(monkeypatch):
    captured: dict = {}

    class FakeFoundry:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("anthropic.AsyncAnthropicFoundry", FakeFoundry)
    monkeypatch.setattr(
        "api.services.llm._entra_token_provider", lambda: "token-provider"
    )
    settings = _settings(
        foundry_resource="realmpal-foundry",
        foundry_use_entra=True,
        anthropic_api_key="",
    )
    client = build_chat_client(settings)
    assert isinstance(client, FakeFoundry)
    assert captured["azure_ad_token_provider"] == "token-provider"
    assert "api_key" not in captured
    assert captured["resource"] == "realmpal-foundry"
