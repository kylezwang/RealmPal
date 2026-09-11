"""
Provider-agnostic identity verification.

Every managed identity provider we might use (Entra External ID, Supabase
Auth, Clerk, Cognito) issues asymmetrically signed JWTs whose public keys are
published at a JWKS endpoint. So the verification shape is identical across
all of them: match the token's `kid` against the JWKS, validate `iss`/`aud`/
`exp`, and treat the `sub` claim as the identity. Swapping providers is then a
settings change, not a rewrite.

Two rules this module exists to enforce:

  1. The identity is whatever the *verified* `sub` says, never a value the
     client hands us. `session_id` from the request body is a client-generated
     UUID | it cannot be a security or tenancy boundary.
  2. Only asymmetric algorithms are accepted. Passing a fixed algorithm
     allowlist to `jwt.decode` is what prevents the classic confusion attack
     where a caller re-signs a token with HS256 using the public key as the
     shared secret.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
import jwt as pyjwt
from loguru import logger

from .config import Settings

# Asymmetric only. RS256 covers Entra/Clerk/Cognito, ES256 covers Supabase's
# current signing keys. HS* is deliberately absent | see rule 2 above.
SUPPORTED_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"})

# A bad `kid` forces a JWKS refetch, so an attacker spraying junk tokens could
# otherwise turn us into a load generator against the provider.
_MIN_REFETCH_INTERVAL_SECONDS = 30
_JWKS_TIMEOUT_SECONDS = 5.0


class IdentityError(Exception):
    """Token could not be verified, or identity is not configured."""


@dataclass(frozen=True)
class AuthenticatedUser:
    """A verified caller. `subject` is the only trustworthy identifier here."""

    subject: str
    email: Optional[str] = None
    claims: dict[str, Any] = field(default_factory=dict)

    @property
    def tenant_key(self) -> str:
        """Stable, opaque key for namespacing this user's stored state."""
        return self.subject


@dataclass
class _JwksCacheEntry:
    keys_by_kid: dict[str, dict[str, Any]]
    expires_at: float
    last_fetch_at: float


_jwks_cache: dict[str, _JwksCacheEntry] = {}


async def _fetch_jwks(jwks_url: str) -> dict[str, dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=_JWKS_TIMEOUT_SECONDS) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            document = response.json()
    except Exception as exc:
        raise IdentityError("Could not reach the identity provider's JWKS endpoint") from exc

    keys = {key["kid"]: key for key in document.get("keys", []) if key.get("kid")}
    if not keys:
        # Caching an empty set would lock out every token until the TTL expired.
        raise IdentityError("Identity provider returned an empty key set")
    return keys


async def _resolve_signing_key(jwks_url: str, kid: str, cache_seconds: int) -> dict[str, Any]:
    """Return the JWK for `kid`, refetching once if it looks like key rotation."""
    now = time.monotonic()
    entry = _jwks_cache.get(jwks_url)

    if entry is not None and kid in entry.keys_by_kid and now < entry.expires_at:
        return entry.keys_by_kid[kid]

    stale_enough = entry is None or (now - entry.last_fetch_at) >= _MIN_REFETCH_INTERVAL_SECONDS
    if not stale_enough:
        if entry is not None and kid in entry.keys_by_kid:
            return entry.keys_by_kid[kid]
        raise IdentityError("Unknown token signing key")

    keys = await _fetch_jwks(jwks_url)
    _jwks_cache[jwks_url] = _JwksCacheEntry(
        keys_by_kid=keys,
        expires_at=now + max(cache_seconds, 1),
        last_fetch_at=now,
    )
    if kid not in keys:
        raise IdentityError("Unknown token signing key")
    return keys[kid]


async def verify_access_token(token: str, settings: Settings) -> AuthenticatedUser:
    """Verify a provider-issued access token and return the caller it names."""
    if not settings.auth_configured:
        raise IdentityError("Identity provider is not configured")

    token = (token or "").strip()
    if not token:
        raise IdentityError("Missing access token")

    allowed = settings.auth_algorithm_list
    try:
        header = pyjwt.get_unverified_header(token)
    except Exception as exc:
        raise IdentityError("Malformed access token") from exc

    algorithm = header.get("alg")
    if algorithm not in allowed:
        raise IdentityError(f"Unsupported token algorithm: {algorithm}")

    kid = header.get("kid")
    if not kid:
        raise IdentityError("Access token has no key id")

    jwk = await _resolve_signing_key(
        settings.auth_jwks_url, kid, settings.auth_jwks_cache_seconds
    )

    try:
        signing_key = pyjwt.PyJWK.from_dict(jwk).key
    except Exception as exc:
        raise IdentityError("Could not load the token signing key") from exc

    try:
        claims = pyjwt.decode(
            token,
            signing_key,
            algorithms=list(allowed),
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
            options={"require": ["exp", "sub"]},
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise IdentityError("Access token has expired") from exc
    except pyjwt.InvalidTokenError as exc:
        # Covers bad signature, wrong audience, wrong issuer, missing claims.
        raise IdentityError("Access token failed verification") from exc

    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise IdentityError("Access token has no subject")

    email = claims.get("email")
    logger.bind(subject=subject[:8], issuer=settings.auth_issuer).debug("Verified access token")
    return AuthenticatedUser(
        subject=subject,
        email=email if isinstance(email, str) else None,
        claims=claims,
    )


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Pull the token out of an `Authorization: Bearer <token>` header."""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


def reset_jwks_cache() -> None:
    """Drop cached signing keys. Used by tests and after a config change."""
    _jwks_cache.clear()
