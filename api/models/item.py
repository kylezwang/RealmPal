from pydantic import BaseModel
from typing import Optional


class ItemProfile(BaseModel):
    name: str
    type: Optional[str] = None
    tier: Optional[str] = None
    description: Optional[str] = None
    # Ordered infobox rows from the item's RealmEye wiki page (Tier, MP Cost,
    # On Equip, Effect(s), Damage, ...). Keys like "Reskin(s)" are dropped
    # at scrape time | we never want reskin variants in recommendations.
    stats: dict = {}
    sprite_url: Optional[str] = None
    # Shiny recast of the same item, when the wiki shows one. Distinct from
    # limited-edition / reskin versions, which we do not scrape as sprites.
    shiny_sprite_url: Optional[str] = None
    drop_locations: list[str] = []
    wiki_url: Optional[str] = None
    limited_edition: bool = False
    # Wiki "Reskin of" / original item, when this page is a Limited Edition clone.
    original_name: Optional[str] = None
    # Set on GET /items when class_name is passed. Not stored in Redis.
    wearable: Optional[bool] = None
    # Awakened unique enchant for this item, filled at GET time from the
    # RealmEye enchanting store. Not stored on the item wiki profile.
    awakened_enchant: Optional[str] = None
