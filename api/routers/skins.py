"""Render a class skin with clothing and accessory dyes applied."""
from typing import Annotated, Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import Settings, get_settings
from ..dependencies import enforce_lookup_rate_limit, get_redis
from ..models.skin import SkinPortrait
from ..services.scraper import ScraperError
from ..services.skin_visualizer import render_skin_portrait
from ..services.validation import sanitize_lookup_name

router = APIRouter(prefix="/skins", tags=["skins"])


@router.get(
    "/render",
    response_model=SkinPortrait,
    dependencies=[Depends(enforce_lookup_rate_limit)],
)
async def render_skin(
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    class_name: Optional[str] = Query(None),
    skin: Optional[str] = Query(None),
    clothing: Optional[str] = Query(None),
    accessory: Optional[str] = Query(None),
) -> SkinPortrait:
    """Composite a RealmEye skin portrait (base sprite + clothing + accessory dyes)."""
    if not (class_name or skin):
        raise HTTPException(status_code=400, detail="class_name or skin is required")
    class_name = sanitize_lookup_name(class_name, field="class_name") if class_name else None
    skin = sanitize_lookup_name(skin, field="skin") if skin else None
    clothing = sanitize_lookup_name(clothing, field="clothing") if clothing else None
    accessory = sanitize_lookup_name(accessory, field="accessory") if accessory else None
    try:
        return await render_skin_portrait(
            redis,
            class_name=class_name,
            skin_name=skin,
            clothing=clothing,
            accessory=accessory,
            ttl_seconds=settings.wiki_ttl_seconds,
        )
    except ScraperError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
