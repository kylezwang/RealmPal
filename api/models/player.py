from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class EquipmentItem(BaseModel):
    name: str
    # Full multi-line tooltip text exactly as RealmEye shows it on hover
    # (rarity/name/tier line + stat bonus lines), for reproducing that same
    # hover-for-details UX in our own UI.
    tooltip: str
    wiki_url: Optional[str] = None
    # Items are cropped from the same shared sprite sheet as pets, e.g.
    # <span class="item" style="background-position:-19536px -0px"></span>
    sprite_sheet_url: Optional[str] = None
    sprite_x: Optional[int] = None
    sprite_y: Optional[int] = None
    sprite_size: Optional[int] = None
    # RealmEye renders a rarity-tiered "slot" frame behind each item icon
    # (e.g. Divine = 4 gold diamonds) via a `::before` pseudo-element cropped
    # from its own sprite sheet, plus a colored glow via `filter: drop-shadow`
    # on the icon itself. Both are keyed off the item's rarity tier.
    slot_sprite_sheet_url: Optional[str] = None
    slot_sprite_x: Optional[int] = None
    slot_sprite_y: Optional[int] = None
    slot_sprite_size: Optional[int] = None
    glow_color: Optional[str] = None  # e.g. "rgb(191, 170, 64)" for Divine


class CharacterStats(BaseModel):
    """One character's eight RotMG stats, in in-game/RealmEye HUD order.

    RealmEye stores these on `span.player-stats` as `data-stats` (base)
    and `data-bonuses` (from equipped items).
    """

    hp: Optional[int] = None
    mp: Optional[int] = None
    attack: Optional[int] = None
    defense: Optional[int] = None
    speed: Optional[int] = None
    dexterity: Optional[int] = None
    vitality: Optional[int] = None
    wisdom: Optional[int] = None


class CharacterSummary(BaseModel):
    class_name: str
    fame: Optional[int] = None
    place: Optional[int] = None
    # RealmEye links a character's class placement (e.g. "#366") to that
    # class's leaderboard, e.g. /top-druids/501 | None when the character
    # isn't ranked (no placement shown at all).
    place_url: Optional[str] = None
    # Character portrait, cropped the same way as pets/items but from its own
    # sheet (RealmEye: .../s/ht/img/sheets.png), e.g.
    # <a class="character" style="background-position: -12100px -550px">
    sprite_sheet_url: Optional[str] = None
    sprite_x: Optional[int] = None
    sprite_y: Optional[int] = None
    sprite_width: Optional[int] = None
    sprite_height: Optional[int] = None
    # "8/8" style maxed-stats readout shown next to the character on RealmEye
    stats_maxed: Optional[str] = None
    # Per-stat values from RealmEye's hover data on that 8/8 badge.
    stats: Optional[CharacterStats] = None
    stat_bonuses: Optional[CharacterStats] = None
    equipment: list[EquipmentItem] = []


class ExaltationEntry(BaseModel):
    """
    One row of RealmEye's "Exaltations" tab | exaltation bonuses are earned
    per-class (via the Cyclic Chest dungeon), so this is keyed by class
    rather than by individual character, unlike `CharacterSummary`.
    Max HP/MP exalt up to +25 each; the other six stats exalt up to +5 each.
    """

    class_name: str
    exaltation_count: Optional[int] = None
    max_hp: Optional[int] = None
    max_mp: Optional[int] = None
    attack: Optional[int] = None
    defense: Optional[int] = None
    speed: Optional[int] = None
    dexterity: Optional[int] = None
    vitality: Optional[int] = None
    wisdom: Optional[int] = None
    # Same per-class portrait crop as CharacterSummary's sprite_*.
    sprite_sheet_url: Optional[str] = None
    sprite_x: Optional[int] = None
    sprite_y: Optional[int] = None
    sprite_width: Optional[int] = None
    sprite_height: Optional[int] = None


class PetInfo(BaseModel):
    name: str
    tier: Optional[str] = None
    sprite_url: Optional[str] = None  # legacy fallback: standalone wiki image
    # RealmEye renders pets as a crop of a single shared sprite sheet, e.g.
    # <span class="pet" data-item="32639" title="Reaper"
    #       style="background-position: -336px -288px;"></span>
    # These fields let the frontend replicate that exact crop via CSS.
    sprite_sheet_url: Optional[str] = None
    sprite_x: Optional[int] = None
    sprite_y: Optional[int] = None
    sprite_size: Optional[int] = None


class PlayerProfile(BaseModel):
    username: str
    guild: Optional[str] = None
    guild_rank: Optional[str] = None
    fame: Optional[int] = None
    rank: Optional[int] = None
    account_fame: Optional[int] = None
    # Total exaltation count shown in the summary table (e.g. "513"), same
    # source as fame/rank | separate from the per-class breakdown below,
    # which is only worth scraping/showing when someone actually asks.
    total_exaltations: Optional[int] = None
    characters: list[CharacterSummary] = []
    exaltations: list[ExaltationEntry] = []
    top_pet: Optional[PetInfo] = None
    last_seen: Optional[str] = None
    created: Optional[str] = None
    scraped_at: datetime = None

    def model_post_init(self, __context):
        if self.scraped_at is None:
            self.scraped_at = datetime.utcnow()
