"""Class progression briefs: early / mid / late farm routes with item cards.

Sorcerer is the hand-verified ratchet (Sep 16, 2026). Other classes use the
same three-band shape, but dungeons and items follow that class's weapon
family, armor type, and store cores. Specialists fill late-game names
(Umi / RealmShark / family cores). Do not invent unverified mid-game UTs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis

from ..models.build import CLASS_ABILITY_HUB, CLASS_ARMOR_HUB, weapon_family
from .community_knowledge import (
    CLASS_STAT_SLOT_OVERRIDES,
    ITEM_UPGRADES,
    LEATHER_CORE,
    ROBE_CORE,
    TOP_RINGS,
    WEAPON_FAMILY_CORES,
)
from .realmshark import parse_query, shark_name_counts
from .wiki_scaling import UMI_BIS_PREFIX

_PROGRESSION = re.compile(
    r"\b("
    r"early[\s-]?game|mid(?:dle)?[\s-]?game|late[\s-]?game|end[\s-]?game|"
    r"early\s+(?:items?|gear|loadout)|"
    r"mid(?:dle)?\s+(?:items?|gear|loadout)|"
    r"late\s+(?:items?|gear|loadout)|"
    r"end\s*game\s+(?:items?|gear)|"
    r"progression|"
    r"leveling\s+gear|"
    r"what\s+(?:should|do)\s+i\s+(?:farm|wear)"
    r")\b",
    re.I,
)
_BAND = re.compile(
    r"\b(early|mid(?:dle)?|late|end)[\s-]?game\b"
    r"|\b(early|mid(?:dle)?|late)\s+(?:items?|gear|loadout)\b",
    re.I,
)


@dataclass(frozen=True)
class DropLine:
    name: str
    note: str = ""


@dataclass(frozen=True)
class DungeonBlock:
    dungeon: str
    note: str = ""
    items: tuple[DropLine, ...] = ()


@dataclass(frozen=True)
class Band:
    title: str
    intro: str = ""
    blocks: tuple[DungeonBlock, ...] = ()


@dataclass(frozen=True)
class ClassProgression:
    class_name: str
    early: Band
    mid: Band
    late: Band
    improvements: tuple[str, ...] = ()


def is_progression_query(message: str) -> bool:
    return bool(_PROGRESSION.search(message or ""))


def parse_progression_query(
    message: str,
) -> Optional[tuple[str, Optional[str]]]:
    """(class, requested band) when this turn is a class progression ask."""
    if not is_progression_query(message):
        return None
    class_name, _stat, _buildish = parse_query(message)
    if not class_name or class_name not in CLASS_ABILITY_HUB:
        return None
    match = _BAND.search(message or "")
    band = None
    if match:
        raw = (match.group(1) or match.group(2) or "").lower()
        if raw.startswith("mid"):
            band = "mid"
        elif raw.startswith("late") or raw.startswith("end"):
            band = "late"
        elif raw.startswith("early"):
            band = "early"
    return class_name, band


def _line(name: str, note: str = "") -> str:
    token = f"[item:{name}]"
    return f"- {token} - {note}" if note else f"- {token}"


def format_progression(guide: ClassProgression, *, band: Optional[str] = None) -> str:
    """Full three-band guide. Asked band is listed first, not exclusive."""
    order = {"early": guide.early, "mid": guide.mid, "late": guide.late}
    labels = ("early", "mid", "late")
    if band in order:
        labels = (band,) + tuple(label for label in labels if label != band)
    chunks = [f"# {guide.class_name} progression"]
    if band:
        chunks.append(
            f"You asked about **{band} game**. The later bands are what to "
            "farm toward, not a different class."
        )
    for label in labels:
        section = order[label]
        chunks.append(f"## {section.title}")
        if section.intro:
            chunks.append(section.intro)
        for block in section.blocks:
            head = f"**{block.dungeon}**"
            if block.note:
                head += f" - {block.note}"
            chunks.append(head)
            for item in block.items:
                chunks.append(_line(item.name, item.note))
    if guide.improvements:
        chunks.append("## Improvements")
        for note in guide.improvements:
            chunks.append(f"- {note}")
    return "\n\n".join(chunks)


SORCERER = ClassProgression(
    class_name="Sorcerer",
    early=Band(
        title="Early game -  Haunted Hallows (level 10+)",
        intro=(
            "**Prep:** Spider Den (Lower Forest, red spiders / orc kings) "
            "for starting gear and XP."
        ),
        blocks=(
            DungeonBlock(
                "Mad Lab",
                note="white ghosts",
                items=(
                    DropLine("Scepter of Fulmination"),
                    DropLine(
                        "Robe of the Mad Scientist",
                        "first boss",
                    ),
                    DropLine(
                        "Conducting Wand",
                        "Horrific Creation (second boss). Needs the "
                        "Awakening enchant to stay relevant later",
                    ),
                ),
            ),
            DungeonBlock(
                "Haunted Cemetery",
                note="Headless Horsemen",
                items=(
                    DropLine("Amulet of Dispersion", "ring"),
                    DropLine("Soul's Guidance", "wand"),
                ),
            ),
            DungeonBlock(
                "Snake Pit",
                items=(
                    DropLine(
                        "Wand of the Bulwark",
                        "shots travel in a slow figure-eight",
                    ),
                    DropLine("Snake Eye Ring"),
                ),
            ),
        ),
    ),
    mid=Band(
        title="Mid game -  Deep Sea Abyss and Carboniferous",
        blocks=(
            DungeonBlock(
                "Parasite Chambers",
                items=(
                    DropLine(
                        "Scepter of Devastation",
                        "best single-target scepter, scales with Attack",
                    ),
                ),
            ),
            DungeonBlock(
                "Cnidarian Reef",
                items=(
                    DropLine(
                        "Cnidaria Rod",
                        "best clearing scepter, scales with Wisdom",
                    ),
                ),
            ),
            DungeonBlock(
                "Lair of Draconis",
                items=(DropLine("Water Dragon Silk Robe"),),
            ),
        ),
    ),
    late=Band(
        title="Late game -  Exaltations, Moonlight Village, Oryx Sanctuary, Shadows",
        blocks=(
            DungeonBlock(
                "Amulet of Restoration",
                note="upgraded Amulet of Dispersion; 20% HP Soul Concentration invulnerability",
                items=(DropLine("Amulet of Restoration"),),
            ),
            DungeonBlock(
                "Moonlight Village",
                items=(
                    DropLine("Flowering Kimono"),
                    DropLine("Kagenohikari"),
                    DropLine(
                        "Tezutsu Hanabi",
                        "Firework Stockpile is the extra scepter-like burst",
                    ),
                    DropLine("Scepter of Rust"),
                    DropLine("Fortitude", "wand upgrade"),
                ),
            ),
            DungeonBlock(
                "Oryx Sanctuary",
                items=(
                    DropLine("Vesture of Duality"),
                    DropLine("Diplomatic Robe"),
                    DropLine("Astronomer's Gown"),
                ),
            ),
            DungeonBlock(
                "The Shatters / hardmode Shadows",
                items=(
                    DropLine("Dusky Catalyst"),
                    DropLine("Mantle of the Monarchy"),
                    DropLine("Fractured Hannya", "untiered ring"),
                    DropLine(
                        "The Forgotten Crown",
                        "endgame ring with Kage and Lean",
                    ),
                ),
            ),
        ),
    ),
    improvements=(
        "Conducting Wand stays mid-tier until Awakening is on it.",
        "Amulet of Dispersion upgrades into [item:Amulet of Restoration].",
        "Farm [item:Scepter of Devastation] for bosses and "
        "[item:Cnidaria Rod] for clear. Do not treat one scepter as both.",
        "A T14 morning star is the tiered wand cap if a UT wand is late.",
    ),
)


_WAND_EARLY = Band(
    title="Early game -  Haunted Hallows (level 10+)",
    intro=(
        "**Prep:** Spider Den (Lower Forest) for starting gear and XP. "
        "Buy the T6 wand, ability, and robe once you can."
    ),
    blocks=(
        DungeonBlock(
            "Mad Lab",
            items=(
                DropLine("Conducting Wand", "Horrific Creation"),
                DropLine("Robe of the Mad Scientist"),
            ),
        ),
        DungeonBlock(
            "Haunted Cemetery",
            items=(
                DropLine("Soul's Guidance", "wand"),
                DropLine("Amulet of Dispersion", "ring"),
            ),
        ),
        DungeonBlock(
            "Snake Pit",
            items=(
                DropLine("Wand of the Bulwark"),
                DropLine("Snake Eye Ring"),
            ),
        ),
    ),
)


def _armor_late_items(class_name: str) -> tuple[DropLine, ...]:
    slug = CLASS_ARMOR_HUB.get(class_name, "")
    if slug == "robes":
        return tuple(DropLine(name) for name in ROBE_CORE)
    if slug == "leather-armors":
        return tuple(DropLine(name) for name in LEATHER_CORE)
    if class_name in ("Samurai", "Kensei"):
        return (DropLine("Fungal Breastplate", "with Tools of the Tarnished"),)
    return ()


def _weapon_late_items(class_name: str) -> tuple[DropLine, ...]:
    hubs, _label = weapon_family(class_name)
    if not hubs:
        return ()
    return tuple(DropLine(name) for name in WEAPON_FAMILY_CORES.get(hubs[0], ()))


def _overlay_items(class_name: str) -> tuple[DropLine, ...]:
    seen: list[DropLine] = []
    names: set[str] = set()
    for (cls, _stat), slots in CLASS_STAT_SLOT_OVERRIDES.items():
        if cls != class_name:
            continue
        for name in slots.values():
            if name not in names:
                names.add(name)
                seen.append(DropLine(name, "overall pick for a named stat set"))
    return tuple(seen)


def _compose_family_guide(class_name: str) -> ClassProgression:
    hubs, weapon_label = weapon_family(class_name)
    family = hubs[0] if hubs else ""
    ability = CLASS_ABILITY_HUB.get(class_name, "ability")
    early = _WAND_EARLY if family == "wands" else Band(
        title="Early game -  first dungeons (level 10+)",
        intro=(
            "**Prep:** Spider Den (Lower Forest) for starting gear and XP. "
            f"Buy the T6 {weapon_label or 'weapon'}, {ability}, and armor "
            "for this class. [item:Snake Eye Ring] is the first real ring."
        ),
        blocks=(
            DungeonBlock(
                "Snake Pit",
                items=(DropLine("Snake Eye Ring"),),
            ),
            DungeonBlock(
                "Sprite World / Undead Lair",
                note="tiered gear and first UT hunting",
                items=(),
            ),
        ),
    )
    if family == "bows":
        mid = Band(
            title="Mid game -  ocean and highlands",
            blocks=(
                DungeonBlock(
                    "Ocean Trench",
                    items=(DropLine("Coral Bow"),),
                ),
                DungeonBlock(
                    "Woodland Labyrinth",
                    items=(DropLine("Leaf Bow"),),
                ),
            ),
        )
    elif family == "staves":
        mid = Band(
            title="Mid game -  cult and dragon",
            blocks=(
                DungeonBlock(
                    "Cultist Hideout / The Void",
                    items=(DropLine("Staff of Unholy Sacrifice"),),
                ),
                DungeonBlock(
                    "Lair of Draconis",
                    items=(DropLine("Water Dragon Silk Robe"),),
                ),
            ),
        )
    elif family == "swords":
        mid = Band(
            title="Mid game -  pirate and mountain",
            blocks=(
                DungeonBlock(
                    "Deadwater Docks / Ice Cave",
                    note=f"farm {weapon_label} UTs and heavy armor",
                    items=(DropLine("Pirate King's Cutlass"),),
                ),
            ),
        )
    elif family == "daggers":
        mid = Band(
            title="Mid game -  sewers and woods",
            blocks=(
                DungeonBlock(
                    "Toxic Sewers / Woodland Labyrinth",
                    note="dagger UTs and leather",
                    items=(),
                ),
            ),
        )
    elif family == "katanas":
        mid = Band(
            title="Mid game -  mountain and fungal",
            blocks=(
                DungeonBlock(
                    "Mountain Temple / Fungal Cavern",
                    items=(
                        DropLine("Tools of the Tarnished"),
                        DropLine("Fungal Breastplate"),
                    ),
                ),
            ),
        )
    elif family == "wands":
        mid = Band(
            title="Mid game -  dragon and abyss",
            blocks=(
                DungeonBlock(
                    "Lair of Draconis",
                    items=(DropLine("Water Dragon Silk Robe"),),
                ),
            ),
        )
    else:
        mid = Band(
            title="Mid game",
            intro=f"Farm {weapon_label or 'class'} UTs in the matching mid-game dungeons.",
        )

    late_items = (
        _weapon_late_items(class_name)
        + _overlay_items(class_name)
        + _armor_late_items(class_name)
        + tuple(DropLine(name) for name in TOP_RINGS)
    )
    late = Band(
        title="Late game -  Moonlight Village, Oryx Sanctuary, exaltations",
        intro=(
            f"Push {class_name} {weapon_label or 'gear'} on Moonlight Village, "
            "Oryx Sanctuary, and Shatters. These are the store overall bases."
        ),
        blocks=(
            DungeonBlock("Moonlight Village / Oryx Sanctuary / The Shatters", items=late_items),
        ),
    )
    upgrades = []
    listed = [
        line.name
        for section in (early, mid, late)
        for block in section.blocks
        for line in block.items
    ]
    for item in listed:
        nxt = ITEM_UPGRADES.get(item)
        if nxt:
            upgrades.append(
                f"[item:{item}] has a direct upgrade: [item:{nxt}]."
            )
    if family == "wands":
        upgrades.append(
            "Amulet of Dispersion upgrades into [item:Amulet of Restoration]."
        )
    return ClassProgression(
        class_name=class_name,
        early=early,
        mid=mid,
        late=late,
        improvements=tuple(dict.fromkeys(upgrades)),
    )


CLASS_GUIDES: dict[str, ClassProgression] = {
    "Sorcerer": SORCERER,
}


def progression_for(class_name: str) -> ClassProgression:
    return CLASS_GUIDES.get(class_name) or _compose_family_guide(class_name)


async def _specialist_extras(
    redis: aioredis.Redis,
    class_name: str,
    *,
    ttl_seconds: int,
) -> str:
    """Cached Umi / RealmShark names not already in the ratchet brief."""
    guide = progression_for(class_name)
    already = {
        item.name.lower()
        for band in (guide.early, guide.mid, guide.late)
        for block in band.blocks
        for item in block.items
    }
    extras: list[str] = []
    raw = await redis.get(f"{UMI_BIS_PREFIX}{class_name.lower()}")
    if raw:
        extras.append(
            "UmiEnjoyers BIS tabs for this class are warmed. Use those "
            "names as alternatives, not replacements, for the route above."
        )
    shark = await shark_name_counts(
        redis,
        (class_name,),
        "weapon",
        ttl_seconds=ttl_seconds,
    )
    fresh = [name for name in shark if name.lower() not in already]
    if fresh:
        tokens = ", ".join(f"[item:{name}]" for name in fresh[:3])
        extras.append(f"RealmShark top 5s also wear {tokens}.")
    return "\n\n".join(extras)


async def compose_progression_brief(
    redis: aioredis.Redis,
    class_name: str,
    *,
    band: Optional[str] = None,
    ttl_seconds: int,
) -> str:
    guide = progression_for(class_name)
    text = format_progression(guide, band=band)
    extras = await _specialist_extras(
        redis, class_name, ttl_seconds=ttl_seconds
    )
    if extras:
        text += "\n\n## Also from the specialists\n\n" + extras
    return text
