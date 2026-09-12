"""Local-only testers that skip quotas while DEBUG=true."""
from __future__ import annotations

from typing import Optional

from ..config import Settings
from ..identity import AuthenticatedUser
from . import accounts


async def is_debug_unlimited(
    user: Optional[AuthenticatedUser], settings: Settings
) -> bool:
    """True for a signed-in account whose IGN is on DEBUG_UNLIMITED_IGNS."""
    allowed = settings.debug_unlimited_ign_set
    if not user or not allowed:
        return False
    ign = str((user.claims or {}).get("ign") or "").strip()
    if not ign and user.email:
        ign = await accounts.get_ign(user.email, settings) or ""
    return ign.lower() in allowed
