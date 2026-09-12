"""
Chat LLM client.

Production uses Microsoft Foundry's Anthropic Messages surface
(`https://<resource>.services.ai.azure.com/anthropic`). Direct Anthropic is
the local fallback until that resource exists. The OpenAI-shaped Foundry
path (`/openai/deployments/...`) is rejected — mixing those produces 404s
and is also a way to point prompts at the wrong host.

Endpoint strings are allowlisted so a poisoned FOUNDRY_BASE_URL cannot
redirect player prompts (IGN lookups, scraped profiles) at an attacker.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Union
from urllib.parse import urlparse

from anthropic import AsyncAnthropic
from loguru import logger

if TYPE_CHECKING:
    from ..config import Settings

FOUNDRY_TOKEN_SCOPE = "https://ai.azure.com/.default"

# Azure AI resource names: letters, digits, hyphens; start and end alphanumeric.
_RESOURCE_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$", re.IGNORECASE)
_FOUNDRY_HOST_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?\.services\.ai\.azure\.com$",
    re.IGNORECASE,
)

_entra_credential: Any = None


class LlmConfigError(ValueError):
    """Misconfigured chat backend. Fail closed rather than guess a host."""


def validate_foundry_target(*, resource: str = "", base_url: str = "") -> None:
    """
    Reject anything that isn't the Foundry Anthropic surface.

    `resource` and `base_url` are mutually exclusive; callers that have both
    should have already failed. This only checks the shape of whichever one
    is present, so a crafted URL cannot exfiltrate chat prompts off Azure.
    """
    name = resource.strip()
    url = base_url.strip()
    if name and url:
        raise LlmConfigError(
            "FOUNDRY_RESOURCE and FOUNDRY_BASE_URL are mutually exclusive"
        )
    if name:
        if not _RESOURCE_RE.fullmatch(name):
            raise LlmConfigError(
                "FOUNDRY_RESOURCE must be an Azure resource name "
                "(letters, digits, hyphens)"
            )
        return
    if not url:
        raise LlmConfigError("Foundry needs FOUNDRY_RESOURCE or FOUNDRY_BASE_URL")
    _validate_foundry_base_url(url)


def _validate_foundry_base_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise LlmConfigError("FOUNDRY_BASE_URL must be https")
    if parsed.username or parsed.password:
        raise LlmConfigError("FOUNDRY_BASE_URL must not include credentials")
    if parsed.query or parsed.fragment:
        raise LlmConfigError("FOUNDRY_BASE_URL must not include a query or fragment")
    if parsed.port not in (None, 443):
        raise LlmConfigError("FOUNDRY_BASE_URL must use port 443")
    host = (parsed.hostname or "").lower()
    if not _FOUNDRY_HOST_RE.fullmatch(host):
        raise LlmConfigError(
            "FOUNDRY_BASE_URL host must be <resource>.services.ai.azure.com"
        )
    path = parsed.path.rstrip("/") or "/"
    if path != "/anthropic":
        raise LlmConfigError(
            "FOUNDRY_BASE_URL path must be /anthropic "
            "(not the OpenAI-shaped /openai/deployments path)"
        )


def _entra_token_provider():
    """
    Cached DefaultAzureCredential. Built once so managed identity / Azure CLI
    login isn't reconstructed on every chat request.
    """
    global _entra_credential
    if _entra_credential is None:
        from azure.identity.aio import DefaultAzureCredential

        _entra_credential = DefaultAzureCredential()

    credential = _entra_credential

    async def _token() -> str:
        acquired = await credential.get_token(FOUNDRY_TOKEN_SCOPE)
        return acquired.token

    return _token


def build_chat_client(settings: Settings) -> Union[AsyncAnthropic, Any]:
    """
    Foundry client when configured, otherwise direct Anthropic.

    On `dev`, `prefer_anthropic` routes to the local key even if Foundry
    vars are still in .env. Master leaves that flag off so Foundry wins.
    The Foundry key and the Anthropic key are never interchangeable: a
    leftover ANTHROPIC_API_KEY must not be forwarded to the Azure endpoint.
    """
    if settings.llm_provider == "foundry":
        return _build_foundry_client(settings)
    return AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.anthropic_timeout_seconds,
    )


def _build_foundry_client(settings: Settings) -> Any:
    from anthropic import AsyncAnthropicFoundry

    resource = settings.foundry_resource.strip()
    base_url = settings.foundry_base_url.strip()
    validate_foundry_target(resource=resource, base_url=base_url)

    kwargs: dict[str, Any] = {"timeout": settings.anthropic_timeout_seconds}
    if resource:
        kwargs["resource"] = resource
    else:
        kwargs["base_url"] = base_url.rstrip("/") + "/"

    if settings.foundry_use_entra:
        kwargs["azure_ad_token_provider"] = _entra_token_provider()
        auth = "entra"
    else:
        kwargs["api_key"] = settings.foundry_api_key
        auth = "api_key"

    logger.bind(
        provider="foundry",
        auth=auth,
        resource=resource or None,
        host=urlparse(base_url).hostname if base_url else None,
    ).info("Opening Foundry chat client")
    return AsyncAnthropicFoundry(**kwargs)
