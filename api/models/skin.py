from typing import Optional

from pydantic import BaseModel


class DyeChip(BaseModel):
    name: str
    item_id: int = 0
    sprite_sheet_url: Optional[str] = None
    sprite_x: Optional[int] = None
    sprite_y: Optional[int] = None
    sprite_size: int = 48


class SkinPortrait(BaseModel):
    class_name: str
    class_id: int
    skin_name: str
    skin_id: int
    clothing: Optional[DyeChip] = None
    accessory: Optional[DyeChip] = None
    portrait_data_uri: str
    realmeye_url: str
