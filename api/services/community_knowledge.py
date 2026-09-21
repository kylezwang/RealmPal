"""Player-confirmed, non-model facts that the scrapers cannot invent.

RealmShark, UmiEnjoyers, and RealmEye class-page max-stat tables all name
real items, and none of them is "the best build" on its own. This module
holds the small overlay we maintain by hand: nicknames, slot overrides,
item upgrades, and the ranking rule for those three sources.

Confirmed Sep 16, 2026 (player): RealmShark is usually the most accurate
of the three (top 5 sets plus on-character enchants). Umi is used in
synergy, not as a lone winner. Wiki Maximum Achievable Stats is a
candidate list (e.g. Bard Attack row is Concertina + Diplomatic; the
actual best is The Triangle + Vesture of Duality).
"""
from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Optional

from ..models.build import (
    CLASS_ABILITY_HUB,
    CLASS_ARMOR_HUB,
    WEAPON_FAMILIES,
    weapon_family,
)

# Source ranking for "best items for this stat / build me a set".
# General gameplay (asked stat is the class's primary): RealmShark, then
# this overlay, Umi in synergy, max-stats last.
# Unique class+stat (asked stat is not primary): max-stats first for
# ability / armor / ring, unless Umi or RealmShark already has that full
# loadout. Overlay family cores stay the general-play weapon/robe/leather
# base and must not replace a dedicated unique set.
SOURCE_RANK = ("realmshark", "player_overlay", "umi", "realmeye")

_STAT_TAB_SHORT = {
    "Attack": ("att",),
    "Defense": ("def",),
    "Dexterity": ("dex",),
    "Speed": ("spd",),
    "Vitality": ("vit",),
    "Wisdom": ("wis",),
}

# Exact wiki titles. Applied after hub ranking in top_build_items so a
# class-page max-stat row cannot beat a confirmed playstyle BIS.
# Next overlays worth writing down the same way: Dex Bard, Attack Archer,
# and any other class+stat where the wiki row is the wrong playstyle.
CLASS_STAT_SLOT_OVERRIDES: dict[tuple[str, str], dict[str, str]] = {
    ("Bard", "Attack"): {
        "ability": "The Triangle",
        "armor": "Vesture of Duality",
    },
    ("Samurai", "Dexterity"): {
        "weapon": "Tools of the Tarnished",
        "armor": "Fungal Breastplate",
    },
    ("Samurai", "Vitality"): {
        "weapon": "Tools of the Tarnished",
        "armor": "Fungal Breastplate",
    },
    ("Kensei", "Dexterity"): {
        "weapon": "Tools of the Tarnished",
        "armor": "Fungal Breastplate",
    },
    ("Kensei", "Vitality"): {
        "weapon": "Tools of the Tarnished",
        "armor": "Fungal Breastplate",
    },
}

# Family bases. Lead with these, then RealmShark / Umi / wiki synergy.
# Keyed by the first weapon hub in WEAPON_FAMILIES. Not a forced visualizer
# pick (Speed Wizard still may use Tideturner).
WEAPON_FAMILY_CORES: dict[str, tuple[str, ...]] = {
    "staves": ("Staff of Unholy Sacrifice",),
    "bows": ("Makakoyumi",),
    "daggers": ("Fractal Blades", "Phantom Sickle"),
    "swords": ("Divinity", "Damnation"),
    "wands": ("Lumiaire",),
    "katanas": ("Enforcer", "Valor", "Tools of the Tarnished"),
}

# Robe / leather bases. Heavy armor depends on the ask; no forced list.
ROBE_CORE = (
    "Vesture of Duality",
    "Diplomatic Robe",
    "Flowering Kimono",
)
LEATHER_CORE = (
    "Cackling Straitjacket",
    "Centaur's Shielding",
    "Ethereal Happi",
)

# Kept as aliases of the robe cores so older Attack-only call sites still
# read the same titles. Kimono is a base now, not only an honorable mention.
ATTACK_ROBE_CORE = ROBE_CORE[:2]
ATTACK_ROBE_HONORABLE = (ROBE_CORE[2],)

# Best rings in the game. Scrapers often omit Kage and Snake Eye unless a
# top-5 set happens to wear them. Name this list on every ring brief.
# Confirmed Sep 16, 2026 (player).
TOP_RINGS = (
    "Chrysalis of Eternity",
    "The Forgotten Crown",
    "The Twilight Gemstone",
    "Kagenohikari",
    "Snake Eye Ring",
)

# Base item -> current upgrade. Showing the base (e.g. Doom Bow on a
# RealmShark top 5) is fine; the brief must also name the upgrade.
ITEM_UPGRADES: dict[str, str] = {
    "Doom Bow": "Clockwork Repeater",
}


def overlay_slot_picks(
    class_name: str, stat: str, picks: dict[str, str]
) -> dict[str, str]:
    """Copy picks and replace slots we have a confirmed BIS for."""
    overlay = CLASS_STAT_SLOT_OVERRIDES.get((class_name, stat))
    if not overlay:
        return picks
    merged = dict(picks)
    merged.update(overlay)
    return merged


def upgrade_of(name: str) -> str | None:
    return ITEM_UPGRADES.get(name)


def upgrade_notes_for(names: list[str]) -> str:
    """One line per named item that has a later upgrade."""
    lines: list[str] = []
    seen: set[str] = set()
    for name in names:
        upgrade = ITEM_UPGRADES.get(name)
        if not upgrade or name in seen:
            continue
        seen.add(name)
        lines.append(
            f"{name} has a direct upgrade: [item:{upgrade}]. "
            f"If recommending {name}, also mention {upgrade}."
        )
    return "\n".join(lines)


def _item_tokens(names: tuple[str, ...]) -> str:
    return ", ".join(f"[item:{name}]" for name in names)


def weapon_core_note(class_name: str | None) -> str:
    """Player overlay base weapons for this class's family."""
    if not class_name:
        return ""
    hubs, label = weapon_family(class_name)
    if not hubs:
        return ""
    cores = WEAPON_FAMILY_CORES.get(hubs[0])
    if not cores:
        return ""
    return (
        f"Overall base {label}: {_item_tokens(cores)}. "
        "Lead with these. RealmShark, Umi, and wiki synergy may add more. "
        "Do not replace this base with a hub On Equip rank."
    )


def armor_core_note(
    class_name: str | None, stat: str | None = None
) -> str:
    """Player overlay base armor for this class's armor type."""
    slug = CLASS_ARMOR_HUB.get(class_name or "")
    if slug == "robes":
        extra = ""
        if stat and stat != "Attack":
            extra = (
                " Vesture of Duality is an Attack robe; do not pick it as "
                f"the {stat} armor."
            )
        return (
            f"Overall base robes: {_item_tokens(ROBE_CORE)}. "
            f"Lead with these, then Umi/RealmShark synergy.{extra}"
        )
    if slug == "leather-armors":
        return (
            f"Overall base leather: {_item_tokens(LEATHER_CORE)}. "
            "Lead with these, then Umi/RealmShark synergy."
        )
    if slug == "heavy-armors":
        combo = combo_note(class_name, stat)
        if combo:
            return combo
        return (
            "Overall: no forced heavy armor. Pick from "
            "RealmShark, then Umi, then wiki."
        )
    return ""


def combo_note(class_name: str | None, stat: str | None = None) -> str:
    """Samurai/Kensei Tools + Fungal is the standout Vit/Dex pair."""
    if class_name not in ("Samurai", "Kensei"):
        return ""
    pair = (
        "[item:Tools of the Tarnished] + [item:Fungal Breastplate] is one "
        "of the strongest vitality/dexterity weapon/armor combos in the "
        "game. Samurai and Kensei are the classes that can wear both."
    )
    if not stat or stat in ("Dexterity", "Vitality"):
        return (
            f"Overall combo for {class_name} "
            f"{stat or 'Dexterity/Vitality'}: {pair} Lead with this pair "
            "on those sets. Other heavy armor still depends on the ask."
        )
    return (
        f"Samurai and Kensei also have {pair} Name that pair on Vitality "
        "or Dexterity sets, not as the default Attack loadout."
    )


def is_unique_stat_build(
    class_name: str | None,
    stat: str | None,
    primary_stat: str | None,
) -> bool:
    """True when the asked stat is not this class's general gameplay stat.

    Needs a known primary (ability scaling majority). No stat, or an
    unknown primary, stays on the general overlay path.
    """
    if not class_name or not stat or not primary_stat:
        return False
    return stat.strip().lower() != primary_stat.strip().lower()


def umi_has_matching_stat_tab(
    umi_body: str | None,
    class_name: str | None,
    stat: str | None,
) -> bool:
    """True when Umi scraped a dedicated ?tab= for this class+stat.

    The General tab is often a generic or Attack loadout, so it does not
    count as a full unique build.
    """
    if not umi_body or not class_name or not stat:
        return False
    lower = umi_body.lower()
    names = [stat]
    names.extend(_STAT_TAB_SHORT.get(stat, ()))
    for name in names:
        slug = re.sub(r"\s+", "-", f"{name} {class_name}".strip().lower())
        if slug == "general":
            continue
        if f"?tab={slug}" in lower:
            return True
    return False


def ability_source_note(*, unique_build: bool = False) -> str:
    """Abilities come from RealmShark, else the scaling specialist."""
    if unique_build:
        return (
            "Abilities for this unique class+stat build: use the RealmShark "
            "board when one exists. If it does not, pick the ability from "
            "the RealmEye Maximum Achievable Stats row for this stat, then "
            "the ability specialist scaling infobox. Do not invent an "
            "ability overall pick except where CLASS_STAT_SLOT_OVERRIDES names "
            "one (Attack Bard: The Triangle)."
        )
    return (
        "Abilities: pick from RealmShark for this class+stat when a board "
        "exists. If RealmShark has no board, use the ability specialist "
        "wiki scaling infobox. Do not invent an ability overall pick except "
        "where CLASS_STAT_SLOT_OVERRIDES names one (Attack Bard: "
        "The Triangle)."
    )


def always_mention_rings_note() -> str:
    """Force Kage / Lean / Crown / Gem / Snake Eye into every ring brief.

    Scrapers drop Kagenohikari and Snake Eye Ring unless a RealmShark
    top 5 happens to wear them. This note keeps them in the same tier
    as Lean, Crown, and Gemstone anyway.
    """
    tokens = _item_tokens(TOP_RINGS)
    return (
        "Always mention these rings in the same high regard, even when "
        "RealmEye, Umi, and RealmShark omit them: "
        f"{tokens}. "
        "Kagenohikari (kage) and Chrysalis of Eternity (lean / lean crown) "
        "are the best rings in the game. The Forgotten Crown, The Twilight "
        "Gemstone, and Snake Eye Ring sit in that same tier. Do not skip "
        "Kagenohikari or Snake Eye Ring just because a hub table or DPS "
        "board did not list them."
    )


def slot_alternatives_note(
    class_name: str | None = None,
    stat: str | None = None,
    *,
    unique_build: bool = False,
    community_full_build: bool = False,
) -> str:
    """Weapon/ability/armor/ring alts come from Umi, not T7 hub filler."""
    lines = [
        "SLOT ALTERNATIVES. After the recommended loadout, list 2-3 "
        "alternatives for each slot that has extras: Weapon, Ability, "
        "Armor, and Ring. Those names come only from the UmiEnjoyers "
        "BIS tabs for this class "
        "(https://umienjoyers.com/guides/best-in-slot/"
        f"{(class_name or 'class').lower()}?tab=general, plus tabs like "
        "?tab=speed-wizard). Prefer the tab that matches the asked stat. "
        "Skip a slot if that page has no extra names. Never list a T7 "
        "tiered armor or robe as an alternative. T7 rings stay allowed."
    ]
    weapon = weapon_core_note(class_name)
    if weapon:
        lines.append(weapon)
    combo = combo_note(class_name, stat)
    if unique_build and not community_full_build:
        lines.append(
            "Unique class+stat build: ability, armor, and ring come from "
            "the RealmEye Maximum Achievable Stats row for this stat, not "
            "from general robe or leather cores."
        )
    elif not unique_build:
        armor = armor_core_note(class_name, stat)
        if armor:
            lines.append(armor)
    if combo and combo not in "\n".join(lines):
        lines.append(combo)
    lines.append(ability_source_note(unique_build=unique_build))
    return "\n".join(lines)


def store_ranking_brief(
    class_name: str | None = None,
    stat: str | None = None,
    *,
    primary_stat: str | None = None,
    community_full_build: bool = False,
    community_source: str = "",
) -> str:
    """Same ranking the visualizer uses, injected into Claude context.

    Follow-up / in-depth questions that miss the stored-answer path still
    need this chunk or the model will treat a wiki max-stat row as BIS
    on a general build, or ignore it on a unique build that has no
    community loadout.
    """
    unique = is_unique_stat_build(class_name, stat, primary_stat)
    if unique and community_full_build:
        source = community_source or "RealmShark or Umi"
        lines = [
            "SOURCE RANKING for this unique "
            f"{stat} {class_name} build. A full loadout already exists on "
            f"{source} (RealmShark top 5 or a matching Umi tab, not "
            "General). Use that set. Overall family cores are "
            "general gameplay only and must not replace it. RealmEye "
            "Maximum Achievable Stats is a fallback after that community "
            "set. Skip Limited Edition reskins. If Doom Bow appears in a "
            "top 5, also name Clockwork Repeater."
        ]
    elif unique:
        lines = [
            "SOURCE RANKING for this unique "
            f"{stat} {class_name} build. RealmShark and Umi do not have a "
            f"full {stat} {class_name} loadout. Priority: RealmEye "
            "class-page Maximum Achievable Stats for ability, armor, and "
            f"ring (stack the highest {stat}). Weapon may still use the "
            "overall family base. Hub On Equip ranks last. Skip "
            "Limited Edition reskins. If Doom Bow appears in a top 5, "
            "also name Clockwork Repeater."
        ]
    else:
        lines = [
            "SOURCE RANKING for equipment recommendations (player-confirmed). "
            "This is a general gameplay build. When sources disagree, "
            "follow this order: "
            "1. RealmShark DPS board for this class+stat (top 5 sets plus "
            "on-character enchants). 2. Overall picks in this chunk. "
            "3. UmiEnjoyers BIS in synergy. 4. RealmEye class-page Maximum "
            "Achievable Stats and hub On Equip ranks last (a max-stat stack, "
            "not the best playstyle). Official RotMG Hub patch notes are "
            "patch truth for new season items and events, not BIS ranking. "
            "Skip Limited Edition reskins. If Doom Bow "
            "appears in a top 5, also name Clockwork Repeater."
        ]
    overlay = CLASS_STAT_SLOT_OVERRIDES.get((class_name or "", stat or ""))
    if overlay:
        bits = ", ".join(
            f"{slot}: [item:{name}]" for slot, name in overlay.items()
        )
        lines.append(
            f"Overall pick for {class_name} {stat}: {bits}. "
            "This beats the wiki max-stat row (Attack Bard on the wiki is "
            "often Concertina + Diplomatic; the playstyle best is The "
            "Triangle + Vesture of Duality). Never say overlay to the "
            "user; call this an overall pick."
        )
    lines.append(
        slot_alternatives_note(
            class_name,
            stat,
            unique_build=unique,
            community_full_build=community_full_build,
        )
    )
    if unique and not community_full_build:
        lines.append(
            f"Ring for this unique {stat} build: pick the {stat} ring "
            "from the Maximum Achievable Stats row, not the general "
            "Kage / Lean / Crown list, unless that row names them."
        )
    else:
        lines.append(always_mention_rings_note())
    return "\n".join(lines)


@dataclass(frozen=True)
class SlotListSpec:
    """Which classes, hubs, and cores feed a 'best X in the game' list."""

    slug: str
    label: str
    hubs: tuple[str, ...]
    classes: tuple[str, ...]
    cores: tuple[str, ...]
    shark_slot: str


def spec_for_slot(slug: str) -> Optional[SlotListSpec]:
    """Map a stored-answer slot slug to Umi/RealmShark collection inputs."""
    key = (slug or "").strip().lower()
    if key == "equipment":
        return SlotListSpec(
            slug="equipment",
            label="equipment",
            hubs=(),
            classes=tuple(CLASS_ARMOR_HUB),
            cores=(),
            shark_slot="",
        )
    if key == "rings":
        return SlotListSpec(
            slug="rings",
            label="rings",
            hubs=("rings",),
            classes=tuple(CLASS_ARMOR_HUB),
            cores=TOP_RINGS,
            shark_slot="ring",
        )
    armor_hubs = {
        "armors": ("robes", "leather-armors", "heavy-armors"),
        "robes": ("robes",),
        "leather-armors": ("leather-armors",),
        "heavy-armors": ("heavy-armors",),
    }
    if key in armor_hubs:
        hubs = armor_hubs[key]
        classes = tuple(
            name
            for name, hub in CLASS_ARMOR_HUB.items()
            if hub in hubs
        )
        cores: tuple[str, ...] = ()
        if "robes" in hubs:
            cores += ROBE_CORE
        if "leather-armors" in hubs:
            cores += LEATHER_CORE
        if "heavy-armors" in hubs:
            cores += ("Fungal Breastplate",)
        return SlotListSpec(
            slug=key,
            label="armor" if key == "armors" else key.replace("-", " "),
            hubs=hubs,
            classes=classes,
            cores=cores,
            shark_slot="armor",
        )
    for classes, hubs, label in WEAPON_FAMILIES:
        if key in hubs:
            return SlotListSpec(
                slug=key,
                label=label,
                hubs=hubs,
                classes=classes,
                cores=WEAPON_FAMILY_CORES.get(hubs[0], ()),
                shark_slot="weapon",
            )
    for class_name, hub in CLASS_ABILITY_HUB.items():
        if hub == key:
            cores = tuple(
                overlay["ability"]
                for (cls, _stat), overlay in CLASS_STAT_SLOT_OVERRIDES.items()
                if cls == class_name and overlay.get("ability")
            )
            return SlotListSpec(
                slug=key,
                label=key.replace("-", " "),
                hubs=(hub,),
                classes=(class_name,),
                cores=cores,
                shark_slot="ability",
            )
    return None


def apply_item_upgrades(names: list[str]) -> list[str]:
    """Put the later item first when a listed name has a known upgrade."""
    out: list[str] = []
    for name in names:
        upgrade = ITEM_UPGRADES.get(name)
        if upgrade and upgrade not in out:
            out.append(upgrade)
        if name not in out:
            out.append(name)
    return out


def rank_community_slot_names(
    *,
    cores: tuple[str, ...] = (),
    shark_counts: dict[str, int] | None = None,
    umi_names: list[str] | None = None,
    limit: int = 6,
) -> list[str]:
    """Cores, then RealmShark frequency, then Umi order. Never hub table order.

    Found live Sep 16: 'Best bows in the game' took the first six RealmEye
    hub rows (Shortbow, Reinforced Bow, ...) because that page is T0-first.
    """
    shark_counts = shark_counts or {}
    umi_names = umi_names or []
    ranked: list[str] = []

    def _add(name: str) -> None:
        clean = (name or "").strip()
        if clean and clean not in ranked:
            ranked.append(clean)

    for name in cores:
        _add(name)
    for name, _count in sorted(
        shark_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        _add(name)
    for name in umi_names:
        _add(name)
    return apply_item_upgrades(ranked)[:limit]


def names_mentioned_in_umi(
    text: str,
    catalog: list[str],
    *,
    stat: str | None = None,
) -> list[str]:
    """Catalog titles that appear in Umi BIS prose, matching-stat tab first."""
    body = text or ""
    if stat:
        shorts = (stat.lower(),) + _STAT_TAB_SHORT.get(stat, ())
        sections = re.split(r"(?m)^## Umi tab:\s*", body)
        preferred: list[str] = []
        for section in sections[1:]:
            title, _, rest = section.partition("\n")
            hay = title.lower()
            if any(token in hay for token in shorts):
                preferred.append(rest)
        if preferred:
            body = "\n".join(preferred)
    found: list[str] = []
    lower = body.lower()
    for name in sorted({n for n in catalog if n}, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name.lower())}\b", lower):
            found.append(name)
    return found
