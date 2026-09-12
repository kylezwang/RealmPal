"""
Minimal auth utilities | JWT creation/validation and magic link email.
Passwords live in api/services/accounts.py; this module only signs
sessions and (optionally) magic-link tokens.
"""
import time
import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger
import jwt as pyjwt

from .config import Settings


def create_jwt(payload: dict[str, Any], settings: Settings) -> str:
    data = {**payload, "iat": int(time.time()), "exp": int(time.time()) + settings.jwt_expiry_days * 86400}
    return pyjwt.encode(data, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_jwt(token: str, secret: str, algorithm: str) -> dict:
    return pyjwt.decode(token, secret, algorithms=[algorithm])


def session_claims_from_header(
    authorization: str | None, settings: Settings
) -> dict[str, Any] | None:
    """Best-effort RealmPal session JWT claims. None if missing/invalid."""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    try:
        return decode_jwt(value.strip(), settings.jwt_secret, settings.jwt_algorithm)
    except Exception:
        return None


def email_from_session_header(authorization: str | None, settings: Settings) -> str | None:
    """Best-effort email from a RealmPal session JWT. None if missing/invalid."""
    claims = session_claims_from_header(authorization, settings)
    if not claims:
        return None
    email = claims.get("email")
    return email.strip().lower() if isinstance(email, str) and email.strip() else None


@dataclass(frozen=True)
class MagicLinkClaims:
    email: str
    jti: str
    exp: int


def create_magic_token(email: str, secret: str, ttl_minutes: int = 30) -> str:
    """Sign a magic-link token. `jti` lets the caller enforce single-use."""
    payload = {
        "email": email,
        "magic": True,
        "jti": uuid.uuid4().hex,
        "exp": int(time.time()) + ttl_minutes * 60,
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def decode_magic_token(token: str, secret: str) -> MagicLinkClaims:
    data = pyjwt.decode(token, secret, algorithms=["HS256"])
    if not data.get("magic"):
        raise ValueError("Not a magic link token")
    jti = data.get("jti")
    if not jti:
        # Pre-dates the single-use rollout. Treat as unusable rather than
        # silently skipping the replay check.
        raise ValueError("Magic link token missing jti")
    return MagicLinkClaims(email=data["email"], jti=jti, exp=int(data["exp"]))


async def send_magic_link(email: str, settings: Settings) -> None:
    """
    Send a magic link email. In production, use a transactional email provider
    (Resend, Postmark, SendGrid). For MVP, log that one was generated.

    The link itself (and the token inside it) is a bearer credential for a
    signed-in session - paid or not - and must never reach a log sink, so
    only `email` is bound here. `logger.info("...", email=email)` would
    look equivalent but isn't:
    loguru treats unbound kwargs as str.format() args, which a message with
    no "{email}" placeholder silently swallows | that's an accident, not a
    guarantee, so bind explicitly instead of relying on it.
    """
    token = create_magic_token(
        email, settings.effective_magic_link_secret, settings.magic_link_ttl_minutes
    )
    link = f"{settings.app_url}/auth/verify?token={token}"

    logger.bind(email=email).info("Magic link generated")

    # TODO: Replace with real email provider (Resend recommended)
    # async with httpx.AsyncClient() as client:
    #     await client.post("https://api.resend.com/emails", ...)
    _ = link  # sent to the provider below once wired up; never logged
