"""On-demand dungeon guide media from RealmEye wiki pages."""
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException

from ..config import Settings, get_settings
from ..dependencies import get_redis
from ..models.dungeon import DungeonDrop, DungeonGuide, DungeonLayout
from ..services.dungeon_guide import _skip_dungeon_drop, load_dungeon_guide

router = APIRouter(prefix="/dungeons", tags=["dungeons"])


@router.get("/{name}", response_model=DungeonGuide)
async def get_dungeon(
    name: str,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> DungeonGuide:
    """Match a dungeon on RealmEye indexes and return portal, graves, layouts, drops."""
    media = await load_dungeon_guide(
        redis, name, ttl_seconds=settings.scrape_ttl_hours * 3600
    )
    if not media or not media.get("title"):
        raise HTTPException(status_code=404, detail=f"Dungeon '{name}' not found")
    drops = []
    for drop in media.get("drops") or []:
        if _skip_dungeon_drop(drop.get("name") or ""):
            continue
        slug = drop.get("wiki_slug")
        drops.append(
            DungeonDrop(
                name=drop.get("name") or "",
                sprite_url=drop.get("sprite_url"),
                wiki_slug=slug,
                wiki_url=(
                    f"https://www.realmeye.com/wiki/{slug}" if slug else None
                ),
                drops_from=drop.get("drops_from") or None,
            )
        )
    return DungeonGuide(
        title=media["title"],
        url=media.get("url") or "",
        portal_url=media.get("portal_url"),
        difficulty=media.get("difficulty"),
        graves_url=media.get("graves_url"),
        layouts=[
            DungeonLayout(caption=row.get("caption") or "Example Layout", url=row["url"])
            for row in media.get("layouts") or []
            if row.get("url")
        ],
        drops=drops,
        tips=list(media.get("tips") or []),
        large_portal=bool(media.get("large_portal")),
    )
