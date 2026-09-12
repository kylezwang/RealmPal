"""
Access token verification.

These cases are the reason api/identity.py exists: each one is a way a caller
could otherwise claim an identity that isn't theirs.
"""
from __future__ import annotations

import json
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from api.identity import (
    IdentityError,
    bearer_token,
    verify_access_token,
)

from .conftest import AUDIENCE, ISSUER


async def test_valid_token_yields_the_subject(auth_settings, jwks_server, make_token):
    user = await verify_access_token(make_token(), auth_settings)
    assert user.subject == "user-abc-123"
    assert user.email == "player@example.com"
    # Tenancy keys off the verified subject, nothing else.
    assert user.tenant_key == "user-abc-123"


async def test_token_signed_by_another_key_is_rejected(
    auth_settings, jwks_server, make_token
):
    attacker_key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(IdentityError):
        await verify_access_token(make_token(attacker_key), auth_settings)


async def test_hs256_algorithm_confusion_is_rejected(
    auth_settings, jwks_server, public_jwk
):
    """
    The classic attack: re-sign the token with HS256 using the provider's
    public key as the shared secret. The algorithm allowlist must refuse it
    before any key material is loaded.
    """
    forged = pyjwt.encode(
        {
            "sub": "attacker",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": int(time.time()) + 600,
        },
        json.dumps(public_jwk),
        algorithm="HS256",
        headers={"kid": public_jwk["kid"]},
    )
    with pytest.raises(IdentityError, match="Unsupported token algorithm"):
        await verify_access_token(forged, auth_settings)


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"aud": "some-other-app"}, "audience from a different application"),
        ({"iss": "https://evil.example/v2.0"}, "issuer we don't trust"),
        ({"exp": int(time.time()) - 60}, "already expired"),
        ({"sub": ""}, "no usable subject"),
    ],
    ids=["wrong_audience", "wrong_issuer", "expired", "empty_subject"],
)
async def test_invalid_claims_are_rejected(
    auth_settings, jwks_server, make_token, overrides, reason
):
    with pytest.raises(IdentityError):
        await verify_access_token(make_token(**overrides), auth_settings)


async def test_token_missing_sub_entirely_is_rejected(
    auth_settings, jwks_server, signing_key, public_jwk
):
    token = pyjwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 600},
        signing_key,
        algorithm="ES256",
        headers={"kid": public_jwk["kid"]},
    )
    with pytest.raises(IdentityError):
        await verify_access_token(token, auth_settings)


async def test_unknown_kid_is_rejected(auth_settings, jwks_server, make_token):
    with pytest.raises(IdentityError, match="Unknown token signing key"):
        await verify_access_token(make_token(kid="not-a-real-key"), auth_settings)


@pytest.mark.parametrize("garbage", ["", "   ", "not-a-jwt", "a.b.c"])
async def test_malformed_tokens_are_rejected(auth_settings, jwks_server, garbage):
    with pytest.raises(IdentityError):
        await verify_access_token(garbage, auth_settings)


async def test_unconfigured_provider_refuses_everything(
    anon_settings, jwks_server, make_token
):
    """A half-configured deployment must fail closed, not accept anything."""
    assert anon_settings.auth_configured is False
    with pytest.raises(IdentityError, match="not configured"):
        await verify_access_token(make_token(), anon_settings)


async def test_partial_configuration_is_not_treated_as_configured():
    from api.config import Settings

    partial = Settings(
        _env_file=None,
        anthropic_api_key="x",
        auth_jwks_url="https://example/jwks.json",
        auth_issuer="https://example",
        # audience deliberately missing
    )
    assert partial.auth_configured is False


async def test_symmetric_algorithms_cannot_be_configured():
    """Even if someone sets HS256 in env, it must not become allowed."""
    from api.config import Settings

    settings = Settings(_env_file=None, anthropic_api_key="x", auth_algorithms="HS256,none")
    assert settings.auth_algorithm_list == ()


async def test_keys_are_cached_across_verifications(
    auth_settings, jwks_server, make_token
):
    for _ in range(5):
        await verify_access_token(make_token(), auth_settings)
    assert jwks_server["fetches"] == 1


async def test_key_rotation_is_picked_up(
    auth_settings, jwks_server, make_token, monkeypatch
):
    """A new `kid` should trigger exactly one refetch, then verify."""
    await verify_access_token(make_token(), auth_settings)
    assert jwks_server["fetches"] == 1

    rotated_key = ec.generate_private_key(ec.SECP256R1())
    rotated_jwk = json.loads(
        pyjwt.algorithms.ECAlgorithm.to_jwk(rotated_key.public_key())
    )
    rotated_jwk.update({"kid": "rotated-key-2", "alg": "ES256", "use": "sig"})
    jwks_server["keys"][rotated_jwk["kid"]] = rotated_jwk

    # The throttle would otherwise suppress a refetch this soon after the first.
    monkeypatch.setattr("api.identity._MIN_REFETCH_INTERVAL_SECONDS", 0)

    user = await verify_access_token(
        make_token(rotated_key, kid="rotated-key-2"), auth_settings
    )
    assert user.subject == "user-abc-123"
    assert jwks_server["fetches"] == 2


async def test_unknown_kid_flood_does_not_hammer_the_provider(
    auth_settings, jwks_server, make_token
):
    """
    Junk `kid`s force a JWKS lookup, so without a throttle an attacker could
    use us to generate load against the identity provider.
    """
    for i in range(25):
        with pytest.raises(IdentityError):
            await verify_access_token(make_token(kid=f"junk-{i}"), auth_settings)
    assert jwks_server["fetches"] == 1


async def test_empty_key_set_is_not_cached(
    auth_settings, jwks_server, make_token, public_jwk, monkeypatch
):
    """
    Caching an empty JWKS would lock out every user until the TTL expired, so
    a momentary blip at the provider must not become a sustained outage.
    """
    jwks_server["keys"] = {}
    with pytest.raises(IdentityError):
        await verify_access_token(make_token(), auth_settings)

    jwks_server["keys"] = {public_jwk["kid"]: public_jwk}
    monkeypatch.setattr("api.identity._MIN_REFETCH_INTERVAL_SECONDS", 0)

    user = await verify_access_token(make_token(), auth_settings)
    assert user.subject == "user-abc-123"


@pytest.mark.parametrize(
    "header, expected",
    [
        ("Bearer abc123", "abc123"),
        ("bearer abc123", "abc123"),
        ("BEARER abc123", "abc123"),
        ("Bearer   abc123  ", "abc123"),
        ("Basic abc123", None),
        ("abc123", None),
        ("Bearer", None),
        ("Bearer ", None),
        ("", None),
        (None, None),
    ],
)
def test_bearer_token_parsing(header, expected):
    assert bearer_token(header) == expected
