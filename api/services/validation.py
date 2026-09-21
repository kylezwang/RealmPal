"""
Shared input checks for names that end up in a scrape URL or a cache key.

`REALMEYE_BASE` / `UMI_BASE` are fixed constants, so nothing a caller sends
can redirect the scraper to a different host — this isn't SSRF host
takeover. What it can still do without a check here: path traversal noise
(`..`, extra `/` segments), control/newline characters that behave oddly
inside a URL or a log line, and unbounded length feeding an expensive
Playwright navigation. Reject that before it reaches the scraper rather than
after.
"""
from __future__ import annotations

import re
from typing import Optional

from fastapi import HTTPException

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
MAX_LOOKUP_NAME_LENGTH = 80
IGN_MAX_LENGTH = 20
_IGN_RE = re.compile(r"^[A-Za-z0-9_]{1,20}$")

# Deliberately simple: this only rejects obvious garbage before it reaches
# a magic-link email. It is not trying to fully validate RFC 5321 addresses.
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,24}$")
MAX_EMAIL_LENGTH = 254  # RFC 5321 §4.5.3.1.3
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def validate_password(value: str, *, field: str = "password") -> str:
    """Reject empty, too-short, or oversized passwords before they are hashed."""
    if value is None or not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{field} is required")
    if len(value) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    if len(value) > MAX_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"{field} is too long")
    if _CONTROL_CHARS.search(value):
        raise HTTPException(status_code=400, detail=f"{field} contains invalid characters")
    return value


def validate_email(value: str, *, field: str = "email") -> str:
    """Trim, lowercase, and shape-check an email before it's used anywhere."""
    cleaned = (value or "").strip().lower()
    if not cleaned or len(cleaned) > MAX_EMAIL_LENGTH:
        raise HTTPException(status_code=400, detail=f"{field} is not a valid email address")
    if _CONTROL_CHARS.search(cleaned) or not _EMAIL_RE.match(cleaned):
        raise HTTPException(status_code=400, detail=f"{field} is not a valid email address")
    return cleaned


def sanitize_ign(value: Optional[str]) -> Optional[str]:
    """Return a RotMG IGN for chat context, or None if the value is junk.

    Matches the frontend charset (``web/lib/playerLookup.ts``). Invalid input
    is dropped rather than rejected so a bad sidebar IGN does not block chat.
    """
    cleaned = (value or "").strip()
    if not cleaned or len(cleaned) > IGN_MAX_LENGTH:
        return None
    if _CONTROL_CHARS.search(cleaned):
        return None
    if not _IGN_RE.fullmatch(cleaned):
        return None
    return cleaned


def sanitize_lookup_name(value: str, *, field: str = "name") -> str:
    """Trim and validate a user-supplied name before it reaches a scraper.

    Raises 400 rather than letting a malformed value reach Playwright.
    """
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field} is required")
    if len(cleaned) > MAX_LOOKUP_NAME_LENGTH:
        raise HTTPException(status_code=400, detail=f"{field} is too long")
    if _CONTROL_CHARS.search(cleaned):
        raise HTTPException(status_code=400, detail=f"{field} contains invalid characters")
    if "/" in cleaned or "\\" in cleaned or ".." in cleaned:
        raise HTTPException(status_code=400, detail=f"{field} contains invalid characters")
    return cleaned
