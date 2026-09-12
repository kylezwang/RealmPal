"""Whether a class can equip an item, from warmed wiki hubs.

Used to hide unequippable cards in the item-card grid. The chat text can
still mention sister-class gear (Ninja leather on a Kensei answer).
"""
from __future__ import annotations

import json

import redis.asyncio as aioredis

from ..models.build import (
    CLASS_ABILITY_HUB,
    CLASS_ARMOR_HUB,
    RINGS_HUB,
    STAT_RING_HUB,
    WEAPON_FAMILIES,
    weapon_family,
)
from .wiki_scaling import HUB_PREFIX, item_name_keys


def canonical_class(class_name: str | None) -> str | None:
    raw = (class_name or "").strip()
    if not raw:
        return None
    for name in CLASS_ARMOR_HUB:
        if name.lower() == raw.lower():
            return name
    return None


def class_equipment_hubs(class_name: str) -> frozenset[str]:
    name = canonical_class(class_name)
    if not name:
        return frozenset()
    hubs = {RINGS_HUB, *STAT_RING_HUB.values()}
    armor = CLASS_ARMOR_HUB.get(name)
    ability = CLASS_ABILITY_HUB.get(name)
    weapons, _label = weapon_family(name)
    if armor:
        hubs.add(armor)
    if ability:
        hubs.add(ability)
    hubs.update(weapons)
    return frozenset(hubs)


def all_equipment_hubs() -> frozenset[str]:
    hubs = {RINGS_HUB, *STAT_RING_HUB.values(), *CLASS_ARMOR_HUB.values(), *CLASS_ABILITY_HUB.values()}
    for _classes, weapons, _label in WEAPON_FAMILIES:
        hubs.update(weapons)
    return frozenset(hubs)


def _row_keys(row: dict) -> set[str]:
    return set(item_name_keys(row.get("name") or ""))


async def class_can_wear_item(
    redis: aioredis.Redis,
    class_name: str | None,
    item_name: str,
) -> bool:
    """True unless the item sits on another class's weapon, ability, or armor hub."""
    name = canonical_class(class_name)
    if not name or not (item_name or "").strip():
        return True
    keys = set(item_name_keys(item_name))
    if not keys:
        return True
    allowed = class_equipment_hubs(name)
    slugs = list(all_equipment_hubs())
    values = await redis.mget([f"{HUB_PREFIX}:{slug}" for slug in slugs])
    in_allowed = False
    in_other = False
    for slug, raw in zip(slugs, values):
        if not raw:
            continue
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError:
            continue
        found = False
        for row in rows if isinstance(rows, list) else []:
            if keys & _row_keys(row):
                found = True
                break
        if not found:
            continue
        if slug in allowed:
            in_allowed = True
        else:
            in_other = True
    if in_allowed:
        return True
    if in_other:
        return False
    return True
