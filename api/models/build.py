"""Stat-scaling knowledge graph for class ability builds.

Nodes are classes, the eight 8/8 stats, and ability items. Edges record
which abilities actually scale with a given stat on a given class | that
is what makes an "attack Bard" different from a default lute Bard.
"""
from typing import Optional

from pydantic import BaseModel, Field


# Canonical 8/8 stats. RealmShark's DPS boards use "Mana" for MP and have
# no dedicated HP board; we still keep HP in the graph so recommendations
# can talk about all eight stats the same way a player would.
PLAYER_STATS = (
    "HP",
    "MP",
    "Attack",
    "Defense",
    "Speed",
    "Dexterity",
    "Vitality",
    "Wisdom",
)

STAT_ALIASES: dict[str, str] = {
    "hp": "HP",
    "life": "HP",
    "health": "HP",
    "mp": "MP",
    "mana": "MP",
    "att": "Attack",
    "atk": "Attack",
    "attack": "Attack",
    "def": "Defense",
    "defense": "Defense",
    "defence": "Defense",
    "spd": "Speed",
    "speed": "Speed",
    "dex": "Dexterity",
    "dexterity": "Dexterity",
    "vit": "Vitality",
    "vitality": "Vitality",
    "wis": "Wisdom",
    "wisdom": "Wisdom",
}

CLASS_ALIASES: dict[str, tuple[str, ...]] = {
    "Rogue": ("rogue", "rogues", "rog", "cloak"),
    "Archer": ("archer", "archers", "arch", "quiver"),
    "Wizard": ("wizard", "wizards", "wiz", "spell"),
    "Priest": ("priest", "priests", "tome"),
    "Warrior": ("warrior", "warriors", "war", "helm"),
    "Knight": ("knight", "knights", "shield"),
    "Paladin": ("paladin", "paladins", "pally", "seal"),
    "Assassin": ("assassin", "assassins", "sin", "poison"),
    "Necromancer": ("necromancer", "necromancers", "necro", "skull"),
    "Huntress": ("huntress", "huntresses", "hunt", "trap"),
    "Mystic": ("mystic", "mystics", "myst", "orb"),
    "Trickster": ("trickster", "tricksters", "trix", "prism"),
    "Sorcerer": ("sorcerer", "sorcerers", "sorc", "scepter"),
    "Ninja": ("ninja", "ninjas", "star"),
    "Samurai": ("samurai", "sam", "wakizashi"),
    "Bard": ("bard", "bards", "lute"),
    "Summoner": ("summoner", "summoners", "summ", "mace"),
    "Kensei": ("kensei", "ken", "sheath"),
    "Druid": ("druid", "druids", "sigil"),
}

# RealmEye wiki hub for each class's ability slot (traps, lutes, ...).
CLASS_ABILITY_HUB: dict[str, str] = {
    "Rogue": "cloaks",
    "Archer": "quivers",
    "Wizard": "spells",
    "Priest": "tomes",
    "Warrior": "helms",
    "Knight": "shields",
    "Paladin": "seals",
    "Assassin": "poisons",
    "Necromancer": "skulls",
    "Huntress": "traps",
    "Mystic": "orbs",
    "Trickster": "prisms",
    "Sorcerer": "scepters",
    "Ninja": "stars",
    "Samurai": "wakizashi",
    "Bard": "lutes",
    "Summoner": "maces",
    "Kensei": "sheaths",
    "Druid": "sigils",
}

# Armor wiki hub for the class's armor type. Rings are universal
# (/wiki/rings) — not class- or character-specific.
RINGS_HUB = "rings"

# RealmEye keeps one list page per 8/8 stat. The Ring agent must read
# attack-rings for Attack — never magic-rings (those +140 values are MP).
STAT_RING_HUB: dict[str, str] = {
    "HP": "health-rings",
    "MP": "magic-rings",
    "Attack": "attack-rings",
    "Defense": "defense-rings",
    "Speed": "speed-rings",
    "Dexterity": "dexterity-rings",
    "Vitality": "vitality-rings",
    "Wisdom": "wisdom-rings",
}

# Official T7 names. T6 is Unbound; T5 is Exalted; T7 is Transcendent.
# HP/MP use Health/Magic, not HP/MP, in the item name.
# Fallback On Equip: combat T7 is +11; Health/Magic T7 is +160.
T7_RING_NAME: dict[str, str] = {
    "HP": "Ring of Transcendent Health",
    "MP": "Ring of Transcendent Magic",
    "Attack": "Ring of Transcendent Attack",
    "Defense": "Ring of Transcendent Defense",
    "Speed": "Ring of Transcendent Speed",
    "Dexterity": "Ring of Transcendent Dexterity",
    "Vitality": "Ring of Transcendent Vitality",
    "Wisdom": "Ring of Transcendent Wisdom",
}

# Fallback On Equip from the same RealmEye list pages, used only when
# the hub row is missing. Combat T7 is +11; Health/Magic T7 is +160.
# T0–T6 names of each stat line → the T7 Transcendent ring.
_LOWER_TIER_PREFIXES = (
    "Ring of Unbound ",
    "Ring of Exalted ",
    "Ring of Paramount ",
    "Ring of Superior ",
    "Ring of Greater ",
    "Ring of Minor ",
    "Ring of ",
)
_T7_STAT_SUFFIX = {
    "Attack": "Attack",
    "Defense": "Defense",
    "Speed": "Speed",
    "Dexterity": "Dexterity",
    "Vitality": "Vitality",
    "Wisdom": "Wisdom",
    "Health": "Health",
    "Magic": "Magic",
}


def upgrade_tiered_ring_name(name: str) -> str:
    """Map Unbound/Exalted/... rings to the T7 Transcendent ring of that line."""
    raw = (name or "").strip()
    lower = raw.lower()
    for suffix, canon in _T7_STAT_SUFFIX.items():
        t7 = T7_RING_NAME[
            "HP" if canon == "Health" else "MP" if canon == "Magic" else canon
        ]
        if lower == t7.lower():
            return t7
        for prefix in _LOWER_TIER_PREFIXES:
            if lower == f"{prefix}{suffix}".lower():
                return t7
    return raw


T7_RING_BONUS: dict[str, tuple[int, str]] = {
    "HP": (160, "+160 HP, +50 MP"),
    "MP": (160, "+50 HP, +160 MP"),
    "Attack": (11, "+50 HP, +50 MP, +11 ATT"),
    "Defense": (11, "+50 HP, +50 MP, +11 DEF"),
    "Speed": (11, "+50 HP, +50 MP, +11 SPD"),
    "Dexterity": (11, "+50 HP, +50 MP, +11 DEX"),
    "Vitality": (11, "+50 HP, +50 MP, +11 VIT"),
    "Wisdom": (11, "+50 HP, +50 MP, +11 WIS"),
}

CLASS_ARMOR_HUB: dict[str, str] = {
    "Rogue": "leather-armors",
    "Assassin": "leather-armors",
    "Trickster": "leather-armors",
    "Archer": "leather-armors",
    "Huntress": "leather-armors",
    "Druid": "leather-armors",
    "Ninja": "leather-armors",
    "Warrior": "heavy-armors",
    "Knight": "heavy-armors",
    "Paladin": "heavy-armors",
    "Samurai": "heavy-armors",
    "Kensei": "heavy-armors",
    "Wizard": "robes",
    "Necromancer": "robes",
    "Mystic": "robes",
    "Priest": "robes",
    "Sorcerer": "robes",
    "Summoner": "robes",
    "Bard": "robes",
}

# (classes, weapon hubs, label). Sister-class DPS weapons only transfer inside a group.
WEAPON_FAMILIES: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("Rogue", "Assassin", "Trickster"), ("daggers", "dual-blades"), "daggers / dual blades"),
    (("Wizard", "Necromancer", "Mystic"), ("staves", "spellblades"), "staves / spellblades"),
    (("Archer", "Huntress", "Bard"), ("bows", "longbows"), "bows / longbows"),
    (("Priest", "Sorcerer", "Summoner", "Druid"), ("wands", "morning-stars"), "wands / morning stars"),
    (("Warrior", "Knight", "Paladin"), ("swords", "flails"), "swords / flails"),
    (("Ninja", "Samurai", "Kensei"), ("katanas", "tachis"), "katanas / tachis"),
)

WEAPON_SHARE_GROUPS: tuple[tuple[str, ...], ...] = tuple(
    classes for classes, _hubs, _label in WEAPON_FAMILIES
)


def weapon_family(class_name: str) -> tuple[tuple[str, ...], str]:
    """Weapon wiki hubs and a label for this class, or empty."""
    for classes, hubs, label in WEAPON_FAMILIES:
        if class_name in classes:
            return hubs, label
    return (), ""


class ItemEnchant(BaseModel):
    """One on-character enchant from a RealmShark leaderboard row."""

    slot: Optional[int] = None
    name: str = ""
    value: str = ""


class EquipmentSlot(BaseModel):
    slot: str
    item_name: str
    rarity: Optional[str] = None
    enchants: list[ItemEnchant] = Field(default_factory=list)


class Loadout(BaseModel):
    rank: int
    player_name: str
    dps: Optional[float] = None
    ability_name: Optional[str] = None
    weapon_name: Optional[str] = None
    equipment: list[EquipmentSlot] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)
    total_damage: Optional[float] = None
    weapon_damage: Optional[float] = None
    ability_damage: Optional[float] = None
    debug: dict = Field(default_factory=dict)


class AbilityScalingEdge(BaseModel):
    """Class --[scales_with stat]--> ability item."""

    class_name: str
    stat: str
    ability_names: list[str]
    build_id: str
    label: str
    note: Optional[str] = None


class StatScalingGraph(BaseModel):
    """Compact adjacency list: class -> stat -> ability items that scale."""

    season: Optional[str] = None
    seasonal: bool = True
    source_url: str = "https://tracker.realmshark.cc/dps-leaderboards"
    edges: list[AbilityScalingEdge] = Field(default_factory=list)
    top_loadouts: dict[str, list[Loadout]] = Field(default_factory=dict)
