from typing import Optional

from pydantic import BaseModel


class DungeonLayout(BaseModel):
    caption: str = "Example Layout"
    url: str


class DungeonDrop(BaseModel):
    name: str
    sprite_url: Optional[str] = None
    wiki_url: Optional[str] = None
    wiki_slug: Optional[str] = None
    drops_from: Optional[str] = None


class DungeonGuide(BaseModel):
    title: str
    url: str = ""
    portal_url: Optional[str] = None
    difficulty: Optional[float] = None
    graves_url: Optional[str] = None
    layouts: list[DungeonLayout] = []
    drops: list[DungeonDrop] = []
    tips: list[str] = []
    large_portal: bool = False
