"""
Minimal auth utilities | JWT creation/validation and magic link email.
No passwords. No account dashboard. Just email -> magic link -> JWT.
"""
import time
from typing import Any

import httpx
import jwt as pyjwt
from loguru import logger

from .config import Settings


def create_jwt(payload: dict[str, Any], settings: Settings) -> str:
    data = {**payload, "iat": int(time.time()), "exp": int(time.time()) + settings.jwt_expiry_days * 86400}
    return pyjwt.encode(data, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_jwt(token: str, secret: str, algorithm: str) -> dict:
    return pyjwt.decode(token, secret, algorithms=[algorithm])


def create_magic_token(email: str, secret: str, ttl_minutes: int = 30) -> str:
    payload = {"email": email, "magic": True, "exp": int(time.time()) + ttl_minutes * 60}
    return pyjwt.encode(payload, secret, algorithm="HS256")


def decode_magic_token(token: str, secret: str) -> str:
    data = pyjwt.decode(token, secret, algorithms=["HS256"])
    if not data.get("magic"):
        raise ValueError("Not a magic link token")
    return data["email"]


async def send_magic_link(email: str, settings: Settings) -> None:
    """
    Send a magic link email. In production, use a transactional email provider
    (Resend, Postmark, SendGrid). For MVP, log the link.
    """
    token = create_magic_token(email, settings.jwt_secret)
    link = f"{settings.app_url}/auth/verify?token={token}"

    logger.info("Magic link generated", email=email, link=link)

    # TODO: Replace with real email provider (Resend recommended)
    # async with httpx.AsyncClient() as client:
    #     await client.post("https://api.resend.com/emails", ...)
