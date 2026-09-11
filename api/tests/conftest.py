"""Shared fixtures for the security-path tests."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

import fakeredis.aioredis
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from starlette.requests import Request

from api import identity
from api.config import Settings

ISSUER = "https://test-tenant.ciamlogin.com/tid/v2.0"
AUDIENCE = "test-client-id"
JWKS_URL = "https://test-tenant.example/discovery/v2.0/keys"


@pytest.fixture
def signing_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def public_jwk(signing_key: ec.EllipticCurvePrivateKey) -> dict[str, Any]:
    jwk = json.loads(pyjwt.algorithms.ECAlgorithm.to_jwk(signing_key.public_key()))
    jwk.update({"kid": "test-key-1", "alg": "ES256", "use": "sig"})
    return jwk


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(
        anthropic_api_key="test-key-not-real",
        auth_jwks_url=JWKS_URL,
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
        auth_algorithms="RS256,ES256",
        jwt_secret="test-jwt-secret",
        pii_hash_secret="test-pii-secret",
    )


@pytest.fixture
def anon_settings() -> Settings:
    """Settings with no identity provider configured, as in local dev."""
    return Settings(
        anthropic_api_key="test-key-not-real",
        jwt_secret="test-jwt-secret",
        pii_hash_secret="test-pii-secret",
    )


@pytest.fixture
def jwks_server(public_jwk, monkeypatch):
    """
    Stub the JWKS endpoint and count fetches.

    Patching `_fetch_jwks` keeps these tests off the network while still
    exercising the cache, rotation, and refetch-throttle logic around it.
    """
    state = {"fetches": 0, "keys": {public_jwk["kid"]: public_jwk}}

    async def fake_fetch(url: str) -> dict[str, dict[str, Any]]:
        state["fetches"] += 1
        if not state["keys"]:
            raise identity.IdentityError("Identity provider returned an empty key set")
        return dict(state["keys"])

    monkeypatch.setattr(identity, "_fetch_jwks", fake_fetch)
    identity.reset_jwks_cache()
    yield state
    identity.reset_jwks_cache()


@pytest.fixture
def make_token(signing_key, public_jwk):
    """Mint a token that is valid unless the test overrides a claim."""

    def _make(
        key: Optional[ec.EllipticCurvePrivateKey] = None,
        *,
        alg: str = "ES256",
        kid: Optional[str] = None,
        **claim_overrides: Any,
    ) -> str:
        claims: dict[str, Any] = {
            "sub": "user-abc-123",
            "email": "player@example.com",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
        }
        claims.update(claim_overrides)
        return pyjwt.encode(
            claims,
            key if key is not None else signing_key,
            algorithm=alg,
            headers={"kid": kid if kid is not None else public_jwk["kid"]},
        )

    return _make


@pytest.fixture
async def redis_client():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()


def build_request(
    *,
    peer: Optional[str] = "203.0.113.10",
    headers: Optional[dict[str, str]] = None,
) -> Request:
    """A minimal Starlette request with a controllable peer address."""
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/chat/stream",
        "raw_path": b"/chat/stream",
        "query_string": b"",
        "headers": raw_headers,
        "client": (peer, 54321) if peer else None,
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)
