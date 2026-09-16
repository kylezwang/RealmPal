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

from ..models.build import CLASS_ARMOR_HUB

# Source ranking for "best items for this stat / build me a set":
# 1. RealmShark DPS board, when one exists for this class+stat
# 2. This overlay (player-confirmed BIS and upgrades)
# 3. UmiEnjoyers general BIS, in synergy with the other two
# 4. RealmEye class-page Maximum Achievable Stats and hub stat ranks last
SOURCE_RANK = ("realmshark", "player_overlay", "umi", "realmeye")

# Exact wiki titles. Applied after hub ranking in top_build_items so a
# class-page max-stat row cannot beat a confirmed playstyle BIS.
# Next overlays worth writing down the same way: Dex Bard, Attack Archer,
# and any other class+stat where the wiki row is the wrong playstyle.
CLASS_STAT_SLOT_OVERRIDES: dict[tuple[str, str], dict[str, str]] = {
    ("Bard", "Attack"): {
        "ability": "The Triangle",
        "armor": "Vesture of Duality",
    },
}

# Attack-stat robe classes: the two robes players actually wear, plus the
# honorable mention Umi lists. Not a forced single pick; briefs should
# name both cores before Kimono.
ATTACK_ROBE_CORE = ("Diplomatic Robe", "Vesture of Duality")
ATTACK_ROBE_HONORABLE = ("Flowering Kimono",)

# Best rings in the game. Kagenohikari is often missing from RealmEye
# max-stats, Umi BIS, and even RealmShark (unless a top-5 set happens to
# wear it). Still name it in the same breath as Crown, Lean, and Gemstone
# on every ring brief. Confirmed Sep 16, 2026 (player).
TOP_RINGS = (
    "Kagenohikari",
    "Chrysalis of Eternity",
    "The Forgotten Crown",
    "The Twilight Gemstone",
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


def always_mention_rings_note() -> str:
    """Force Kage / Lean / Crown / Gemstone into every ring brief.

    Scrapers drop Kagenohikari unless a RealmShark top 5 happens to wear
    it. This note is the overlay that keeps it in the same tier as Lean,
    Crown, and Gemstone anyway.
    """
    tokens = ", ".join(f"[item:{name}]" for name in TOP_RINGS)
    return (
        "Always mention these rings in the same high regard, even when "
        "RealmEye, Umi, and RealmShark omit them: "
        f"{tokens}. "
        "Kagenohikari (kage) and Chrysalis of Eternity (lean / lean crown) "
        "are the best rings in the game. The Forgotten Crown and The "
        "Twilight Gemstone sit in that same tier. Do not skip Kagenohikari "
        "just because a hub table or DPS board did not list it."
    )


def slot_alternatives_note(
    class_name: str | None = None, stat: str | None = None
) -> str:
    """Weapon/ability/armor/ring alts come from Umi, not T7 hub filler."""
    lines = [
        "SLOT ALTERNATIVES. After the recommended loadout, list 2-3 "
        "alternatives for each slot that has extras: Weapon, Ability, "
        "Armor, and Ring. Those names come only from the UmiEnjoyers "
        "general-tab BIS page for this class "
        "(https://umienjoyers.com/guides/best-in-slot/"
        f"{(class_name or 'class').lower()}?tab=general). "
        "Skip a slot if that page has no extra names. Never list a T7 "
        "tiered armor or robe as an alternative. T7 rings stay allowed."
    ]
    if (
        stat == "Attack"
        and class_name
        and CLASS_ARMOR_HUB.get(class_name) == "robes"
    ):
        core = " and ".join(f"[item:{name}]" for name in ATTACK_ROBE_CORE)
        honor = ", ".join(f"[item:{name}]" for name in ATTACK_ROBE_HONORABLE)
        lines.append(
            f"Attack robe classes: name {core}. If one is the pick, the "
            f"other is the first armor alternative. {honor} is an "
            "honorable mention. Do not substitute a T7 robe."
        )
    return "\n".join(lines)


def store_ranking_brief(
    class_name: str | None = None, stat: str | None = None
) -> str:
    """Same ranking the visualizer uses, injected into Claude context.

    Follow-up / in-depth questions that miss the stored-answer path still
    need this chunk or the model will treat a wiki max-stat row as BIS.
    """
    lines = [
        "SOURCE RANKING for equipment recommendations (player-confirmed). "
        "When sources disagree, follow this order: "
        "1. RealmShark DPS board for this class+stat (top 5 sets plus "
        "on-character enchants). 2. Player overlay in this chunk. "
        "3. UmiEnjoyers BIS in synergy. 4. RealmEye class-page Maximum "
        "Achievable Stats and hub On Equip ranks last (a max-stat stack, "
        "not the best playstyle). Skip Limited Edition reskins. If Doom Bow "
        "appears in a top 5, also name Clockwork Repeater."
    ]
    overlay = CLASS_STAT_SLOT_OVERRIDES.get((class_name or "", stat or ""))
    if overlay:
        bits = ", ".join(
            f"{slot}: [item:{name}]" for slot, name in overlay.items()
        )
        lines.append(
            f"Player overlay for {class_name} {stat}: {bits}. "
            "This beats the wiki max-stat row (Attack Bard on the wiki is "
            "often Concertina + Diplomatic; the playstyle best is The "
            "Triangle + Vesture of Duality)."
        )
    lines.append(slot_alternatives_note(class_name, stat))
    return "\n".join(lines)
