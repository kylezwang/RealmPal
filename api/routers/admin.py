"""Admin-only notification feed. Every handler re-checks the role."""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException

import redis.asyncio as aioredis

from ..config import Settings, get_settings
from ..dependencies import get_optional_user, get_redis
from ..identity import AuthenticatedUser
from ..services.admin_access import is_admin
from ..services import admin_events

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin(
    user: Annotated[Optional[AuthenticatedUser], Depends(get_optional_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedUser:
    if not user or not await is_admin(user, settings):
        raise HTTPException(status_code=403, detail="Admin only")
    return user


@router.get("/notifications")
async def notifications(
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
) -> dict:
    return await admin_events.build_feed(settings, redis=redis)
