"""
Deployment namespacing for Redis keys and the Qdrant collection.

Two environments pointed at one Redis or one Qdrant used to share state
silently: `settings.qdrant_collection` was defined and then ignored, with
"realm_pal" hardcoded in both the ingestion and retrieval paths.
"""
from __future__ import annotations

import pytest

from api.config import Settings
from api.redis_namespace import NamespacedRedis, namespaced
from api.services import ingestion
from api.services.rate_limit import quota_for

from .conftest import build_request


def _settings(namespace: str = "") -> Settings:
    return Settings(
        _env_file=None,
        anthropic_api_key="test-key-not-real",
        jwt_secret="test-jwt-secret",
        pii_hash_secret="test-pii-secret",
        deployment_namespace=namespace,
    )


# --- configuration --------------------------------------------------------


def test_no_namespace_leaves_names_untouched():
    """A single-environment deployment shouldn't pay for this feature."""
    settings = _settings()
    assert settings.qdrant_collection_name == "realm_pal"
    assert settings.redis_key_prefix == ""


def test_namespace_scopes_the_collection_and_key_prefix():
    settings = _settings("staging")
    assert settings.qdrant_collection_name == "realm_pal_staging"
    assert settings.redis_key_prefix == "staging:"


def test_environments_do_not_collide():
    staging = _settings("staging")
    production = _settings("prod")
    assert staging.qdrant_collection_name != production.qdrant_collection_name
    assert staging.redis_key_prefix != production.redis_key_prefix


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Staging", "staging"),
        ("  prod  ", "prod"),
        ("pr-od", "prod"),
        ("eu_west_1", "eu_west_1"),
        ("a/b:c", "abc"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_namespace_is_normalized_for_use_in_identifiers(raw, expected):
    assert _settings(raw).namespace_slug == expected


def test_custom_collection_name_is_honoured():
    """The setting used to be dead config; make sure it's read now."""
    settings = Settings(
        _env_file=None,
        anthropic_api_key="x", qdrant_collection="other_index", deployment_namespace="dev"
    )
    assert settings.qdrant_collection_name == "other_index_dev"


def test_ingestion_and_retrieval_agree_on_the_collection(monkeypatch):
    """
    Writing to one collection and reading from another would look like an
    empty knowledge base rather than an error, so pin them together.
    """
    settings = _settings("dev")
    monkeypatch.setattr(ingestion, "get_settings", lambda: settings)
    assert ingestion.collection() == settings.qdrant_collection_name


# --- Redis key prefixing --------------------------------------------------


async def test_keys_written_through_the_wrapper_are_prefixed(redis_client):
    client = namespaced(redis_client, "prod:")
    await client.set("greeting", "hello")

    assert await redis_client.get("prod:greeting") == "hello"
    assert await redis_client.get("greeting") is None


async def test_namespaces_are_isolated_from_each_other(redis_client):
    staging = namespaced(redis_client, "staging:")
    production = namespaced(redis_client, "prod:")

    await staging.set("shared-cache-key", "staging value")
    await production.set("shared-cache-key", "prod value")

    assert await staging.get("shared-cache-key") == "staging value"
    assert await production.get("shared-cache-key") == "prod value"


async def test_empty_prefix_returns_the_client_unchanged(redis_client):
    assert namespaced(redis_client, "") is redis_client


async def test_counter_and_expiry_commands_are_prefixed(redis_client):
    client = namespaced(redis_client, "prod:")
    assert await client.incr("counter") == 1
    assert await client.incr("counter") == 2
    await client.expire("counter", 60)

    assert await redis_client.get("prod:counter") == "2"
    assert 0 < await client.ttl("counter") <= 60


async def test_setex_prefixes_only_the_key(redis_client):
    client = namespaced(redis_client, "prod:")
    await client.setex("temp", 30, "value")
    assert await redis_client.get("prod:temp") == "value"
    assert 0 < await redis_client.ttl("prod:temp") <= 30


async def test_keyword_arguments_are_passed_through(redis_client):
    """wiki_scaling takes a lock with set(key, "1", nx=True, ex=120)."""
    client = namespaced(redis_client, "prod:")
    assert await client.set("lock", "1", nx=True, ex=120) is True
    assert await client.set("lock", "1", nx=True, ex=120) is None
    assert 0 < await redis_client.ttl("prod:lock") <= 120


async def test_variadic_key_commands_prefix_every_key(redis_client):
    client = namespaced(redis_client, "prod:")
    await client.set("a", "1")
    await client.set("b", "2")

    assert await client.exists("a", "b") == 2
    assert await redis_client.exists("a", "b") == 0

    await client.delete("a", "b")
    assert await client.exists("a", "b") == 0


async def test_list_commands_are_prefixed(redis_client):
    client = namespaced(redis_client, "prod:")
    await client.lpush("feedback:log", "one")
    await client.lpush("feedback:log", "two")
    await client.ltrim("feedback:log", 0, 0)

    assert await redis_client.llen("prod:feedback:log") == 1
    assert await redis_client.llen("feedback:log") == 0


async def test_connection_commands_pass_through(redis_client):
    client = namespaced(redis_client, "prod:")
    assert await client.ping() is True


async def test_unclassified_command_raises_rather_than_leaking_a_key(redis_client):
    """
    Silently passing an unprefixed key through is the exact failure this
    module prevents, so an unreviewed command must fail loudly instead.
    """
    client = namespaced(redis_client, "prod:")
    with pytest.raises(AttributeError, match="not classified"):
        _ = client.getrange


async def test_wrapper_exposes_the_raw_client_for_diagnostics(redis_client):
    client = namespaced(redis_client, "prod:")
    assert isinstance(client, NamespacedRedis)
    assert client.unprefixed is redis_client
    assert client.key("thing") == "prod:thing"


# --- quotas land inside the namespace ------------------------------------


async def test_quota_counters_are_namespaced(redis_client):
    """Otherwise staging traffic would burn production users' allowances."""
    settings = _settings("staging")
    client = namespaced(redis_client, settings.redis_key_prefix)

    quota = quota_for(None, build_request(peer="198.51.100.7"), settings)
    await client.incr(quota.key)

    assert await redis_client.get(f"staging:{quota.key}") == "1"
    assert await redis_client.get(quota.key) is None
