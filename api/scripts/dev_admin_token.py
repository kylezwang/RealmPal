"""Mint a local dev session for the account that owns an IGN, for UI checks.

Prints only the JWT for a local account that already exists, so an admin-only
screen can be exercised without knowing the account's password. Local dev only.

Usage:
    api/.venv/Scripts/python.exe api/scripts/dev_admin_token.py Turbine
"""
from __future__ import annotations

import asyncio
import sys

from api.auth import create_jwt
from api.config import Settings
from api.services import accounts, entitlements
from api.services.admin_access import jwt_role


async def main() -> None:
    ign = sys.argv[1] if len(sys.argv) > 1 else "Turbine"
    settings = Settings()
    email = await accounts.email_for_ign(ign, settings)
    if not email:
        print(f"NO_ACCOUNT for ign {ign!r}")
        return
    stored_ign = await accounts.get_ign(email, settings)
    role = await jwt_role(email, stored_ign, settings)
    paid = await entitlements.is_active(email, settings)
    token = create_jwt(
        {"email": email, "paid": paid, "ign": stored_ign, "role": role}, settings
    )
    print(f"ROLE={role}")
    print(f"IGN={stored_ign}")
    print(f"TOKEN={token}")


if __name__ == "__main__":
    asyncio.run(main())
