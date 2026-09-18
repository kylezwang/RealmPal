"""Server-side admin role. The notifications modal is not a user setting."""
from __future__ import annotations

from typing import Optional

from ..config import Settings
from ..identity import AuthenticatedUser
from . import accounts


async def is_admin(
    user: Optional[AuthenticatedUser], settings: Settings
) -> bool:
    """True only for a signed-in account named in ADMIN_IGNS or ADMIN_EMAILS."""
    if not user:
        return False
    email = (user.email or "").strip().lower()
    if email and email in settings.admin_email_set:
        return True
    ign = str((user.claims or {}).get("ign") or "").strip()
    if not ign and email:
        ign = await accounts.get_ign(email, settings) or ""
    return bool(ign) and ign.lower() in settings.admin_ign_set


async def jwt_role(
    email: Optional[str], ign: Optional[str], settings: Settings
) -> str:
    """Convenience claim on new sessions. /admin still re-checks is_admin."""
    cleaned = (email or "").strip().lower()
    user = AuthenticatedUser(
        subject=cleaned or "unknown",
        email=cleaned or None,
        claims={"ign": (ign or "").strip()},
    )
    return "admin" if await is_admin(user, settings) else "user"
