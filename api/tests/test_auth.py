"""
Magic-link token shape: its own secret, and single-use via `jti`.

A magic link used to be a plain JWT signed with the same secret that signs
every session token, redeemable any number of times inside its 30-minute
window. Neither property holds any more: `MAGIC_LINK_SECRET` is separate
(falling back to `JWT_SECRET` only when unset), and every token carries a
`jti` the caller can mark as spent.
"""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest

from api.auth import MagicLinkClaims, create_magic_token, decode_magic_token
from api.config import Settings


def test_token_carries_a_unique_jti():
    first = create_magic_token("a@example.com", "secret-a")
    second = create_magic_token("a@example.com", "secret-a")
    claims_a = decode_magic_token(first, "secret-a")
    claims_b = decode_magic_token(second, "secret-a")
    assert claims_a.jti != claims_b.jti


def test_decode_returns_email_and_jti():
    token = create_magic_token("player@example.com", "secret-a")
    claims = decode_magic_token(token, "secret-a")
    assert isinstance(claims, MagicLinkClaims)
    assert claims.email == "player@example.com"
    assert claims.jti


def test_wrong_secret_is_rejected():
    token = create_magic_token("a@example.com", "secret-a")
    with pytest.raises(Exception):
        decode_magic_token(token, "a-different-secret")


def test_non_magic_token_is_rejected():
    """A session JWT must not be redeemable through the magic-link path."""
    token = pyjwt.encode({"email": "a@example.com", "exp": int(time.time()) + 60}, "s", algorithm="HS256")
    with pytest.raises(ValueError, match="Not a magic link"):
        decode_magic_token(token, "s")


def test_legacy_token_without_jti_is_rejected():
    """Pre-rollout tokens can't be single-use-tracked, so they must not verify."""
    token = pyjwt.encode(
        {"email": "a@example.com", "magic": True, "exp": int(time.time()) + 60},
        "s",
        algorithm="HS256",
    )
    with pytest.raises(ValueError, match="jti"):
        decode_magic_token(token, "s")


def test_expired_token_is_rejected():
    token = pyjwt.encode(
        {"email": "a@example.com", "magic": True, "jti": "x", "exp": int(time.time()) - 1},
        "s",
        algorithm="HS256",
    )
    with pytest.raises(Exception):
        decode_magic_token(token, "s")


# --- settings-level secret separation -------------------------------------


def test_falls_back_to_jwt_secret_when_unset():
    settings = Settings(_env_file=None, anthropic_api_key="x", jwt_secret="the-session-secret")
    assert settings.effective_magic_link_secret == "the-session-secret"
    assert settings.magic_link_secret_is_shared is True


def test_explicit_magic_link_secret_wins():
    settings = Settings(
        _env_file=None,
        anthropic_api_key="x",
        jwt_secret="the-session-secret",
        magic_link_secret="a-separate-magic-secret",
    )
    assert settings.effective_magic_link_secret == "a-separate-magic-secret"
    assert settings.magic_link_secret_is_shared is False


def test_a_session_secret_leak_no_longer_forges_a_magic_link():
    """The whole point: knowing JWT_SECRET must not be enough any more."""
    settings = Settings(
        _env_file=None,
        anthropic_api_key="x",
        jwt_secret="the-session-secret",
        magic_link_secret="a-separate-magic-secret",
    )
    token = create_magic_token("a@example.com", settings.effective_magic_link_secret)
    with pytest.raises(Exception):
        decode_magic_token(token, settings.jwt_secret)
