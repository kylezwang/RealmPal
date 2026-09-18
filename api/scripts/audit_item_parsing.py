"""Audit how completely we understand each cached item's stats and procs.

Every DPS number is built on a stat sheet, and that sheet is only as good as
our parsing of each worn piece's wiki infobox. A proc line we fail to read is
not a visible error: the reconstruct simply comes out low and confident. This
script walks every cached item profile and reports the lines where the wiki text
plainly states something we did not extract.

It checks five things per item:
  procs    - text names a trigger (On Ability Use / On Hit / On Shoot / ...) but
             parse_gear_procs found nothing
  equip    - text has an On Equip line but on_equip_bonuses found no stats, or
             the text names a stat the parse missed
  status   - text names a status effect (Berserk, Damaging, Curse, ...) but
             parse_status_grants found nothing
  weapon   - item has Damage and Shots but estimate_weapon_dps returned nothing
  ability  - item has an MP Cost and a Damage row but parse_ability_formula
             returned nothing

Usage (from the repo root, with the API venv):
    python api/scripts/audit_item_parsing.py            # summary + top gaps
    python api/scripts/audit_item_parsing.py --all       # every gap
    python api/scripts/audit_item_parsing.py --item "Vesture of Duality"
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter

import redis.asyncio as aioredis

from api.config import Settings
from api.models.item import ItemProfile
from api.services.dps_specialist import (
    estimate_weapon_dps,
    on_equip_bonuses,
    parse_ability_formula,
    parse_gear_procs,
    parse_status_grants,
)
from api.services.wiki_scaling import ITEM_CACHE_PREFIX

# Wiki trigger vocabulary. A proc line always names when it fires.
_TRIGGER = re.compile(
    r"\bon\s+(?:ability\s+use|use|hit|shoot|equip\s+use|damage|death|"
    r"low\s+health|full\s+health|kill)\b",
    re.I,
)
_STATUS = re.compile(
    r"\b(berserk|damaging|curse[d]?|exposed|vulnerable|armor\s*brok(?:en|e)|"
    r"weak(?:ened)?|dazed|inspired|energized|healing|invulnerable)\b",
    re.I,
)
# "+15 ATT", "-6 DEF", "+110 MP". The stat abbreviations RealmEye uses. The `%`
# is deliberately NOT allowed: "+10% WIS equal to ATT" is a share of another
# stat, not a flat +10 Wisdom, and on_equip_bonuses is right to skip it. Letting
# `%` through made the audit report 21 items as having missed bonuses that we
# correctly declined to read, which is worse than silence because it invites
# someone to "fix" the parse by adding a bonus the item does not grant. Derived
# bonuses are tracked separately (see the percent-of-stat item in BACKLOG.md).
_STAT_TOKEN = re.compile(
    r"([+-]\s*\d+)\s*(ATT|DEF|SPD|DEX|VIT|WIS|HP|MP|LIFE|MANA)\b", re.I
)
_STAT_NAMES = {
    "ATT": "Attack",
    "DEF": "Defense",
    "SPD": "Speed",
    "DEX": "Dexterity",
    "VIT": "Vitality",
    "WIS": "Wisdom",
    "HP": "HP",
    "LIFE": "HP",
    "MP": "MP",
    "MANA": "MP",
}
# Rows that describe the item's own shot, not a worn effect.
_SKIP_ROWS = {"damage", "total damage", "shots", "rate of fire", "projectile speed"}


def _proc_text(item: ItemProfile) -> str:
    """Only the rows that can carry a worn effect."""
    return " | ".join(
        f"{k}: {v}"
        for k, v in (item.stats or {}).items()
        if k.strip().lower() not in _SKIP_ROWS
    )


def audit(item: ItemProfile) -> list[tuple[str, str]]:
    stats = item.stats or {}
    lowered = {k.strip().lower(): (v or "") for k, v in stats.items()}
    blob = _proc_text(item)
    gaps: list[tuple[str, str]] = []

    proc_rows = " | ".join(
        f"{k}: {v}"
        for k, v in stats.items()
        if _TRIGGER.search(f"{k} {v}") and k.strip().lower() not in _SKIP_ROWS
    )
    if proc_rows and not parse_gear_procs(item):
        gaps.append(("procs", proc_rows))

    equip = lowered.get("on equip", "")
    if equip:
        parsed = on_equip_bonuses(item)
        if not parsed:
            gaps.append(("equip", f"On Equip: {equip}"))
        else:
            missed = [
                f"{sign}{_STAT_NAMES[abbr.upper()]}"
                for sign, abbr in _STAT_TOKEN.findall(equip)
                if _STAT_NAMES[abbr.upper()] not in parsed
            ]
            if missed:
                gaps.append(
                    ("equip", f"On Equip: {equip}  [missed {', '.join(missed)}]")
                )

    status_rows = " | ".join(
        f"{k}: {v}"
        for k, v in stats.items()
        if _STATUS.search(str(v)) and k.strip().lower() not in _SKIP_ROWS
    )
    if status_rows and not parse_status_grants(item):
        gaps.append(("status", status_rows))

    if lowered.get("damage") and lowered.get("shots") and not lowered.get("mp cost"):
        est = estimate_weapon_dps(stats, dex=50, att=50)
        if not est:
            gaps.append(
                ("weapon", f"Damage: {lowered['damage']} | Shots: {lowered['shots']}")
            )
        else:
            # Returning *a* number is not the same as reading the row. Makakoyumi
            # parsed cleanly to a 30-damage bow because the bare `800` group was
            # skipped, and the audit called it fine. Compare the largest damage
            # figure stated anywhere in the row against the largest group we
            # actually parsed: a big gap means we dropped a projectile.
            # "total: N" is shots x damage by definition and "average: N" is
            # derived, so neither is evidence of a dropped projectile.
            row = re.sub(
                r"(?:total|average)\s*:\s*[\d,]+(?:\.\d+)?",
                "",
                lowered["damage"],
                flags=re.I,
            )
            stated = [
                float(n.replace(",", ""))
                for n in re.findall(r"\d[\d,]*(?:\.\d+)?", row)
            ]
            parsed_max = max((g["max"] for g in est["groups"]), default=0.0)
            if stated and parsed_max and max(stated) > parsed_max * 2:
                gaps.append(
                    (
                        "weapon",
                        f"Damage: {lowered['damage']}  [row states up to "
                        f"{max(stated):.0f}, largest group parsed "
                        f"{parsed_max:.0f}]",
                    )
                )
            # A Rate of Fire list must produce per-group rates, or the groups get
            # collapsed onto one blended rate that fits none of them.
            if ";" in lowered.get("rate of fire", "") and not est.get("multi_rof"):
                gaps.append(
                    (
                        "weapon",
                        f"Rate of Fire: {lowered['rate of fire']} | "
                        f"Damage: {lowered['damage']}  [rates not applied "
                        f"per projectile]",
                    )
                )

    if lowered.get("mp cost") and lowered.get("damage"):
        if not parse_ability_formula(stats):
            gaps.append(("ability", f"Damage: {lowered['damage']}"))

    return gaps


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="list every gap")
    ap.add_argument("--item", help="audit one item by name and dump its rows")
    ap.add_argument("--kind", help="only this gap kind (procs/equip/status/...)")
    args = ap.parse_args()

    settings = Settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    items: list[ItemProfile] = []
    async for key in redis.scan_iter(f"{ITEM_CACHE_PREFIX}*"):
        raw = await redis.get(key)
        if not raw:
            continue
        try:
            items.append(ItemProfile.model_validate_json(raw))
        except Exception:
            continue

    if args.item:
        wanted = args.item.strip().lower()
        for item in items:
            if item.name.strip().lower() == wanted:
                print(f"=== {item.name} ===")
                for k, v in (item.stats or {}).items():
                    print(f"  {k}: {v}")
                print("\nparse_gear_procs:")
                for proc in parse_gear_procs(item):
                    print(f"  {proc}")
                print(f"\non_equip_bonuses: {on_equip_bonuses(item)}")
                print(f"parse_status_grants: {parse_status_grants(item)}")
                print(f"parse_ability_formula: {parse_ability_formula(item.stats or {})}")
                print(f"\ngaps: {audit(item) or 'none'}")
                await redis.aclose()
                return 0
        print(f"{args.item!r} is not in the cache.")
        await redis.aclose()
        return 1

    counts: Counter[str] = Counter()
    found: list[tuple[str, str, str]] = []
    for item in items:
        for kind, evidence in audit(item):
            if args.kind and kind != args.kind:
                continue
            counts[kind] += 1
            found.append((kind, item.name, evidence))

    print(f"cached items audited: {len(items)}")
    if not items:
        print("Nothing cached. Warm the item store first.")
        await redis.aclose()
        return 1
    print(f"items with at least one gap: {len({n for _k, n, _e in found})}\n")
    for kind in ("procs", "equip", "status", "weapon", "ability"):
        n = counts.get(kind, 0)
        pct = n / len(items) * 100
        print(f"  {kind:8} {n:4} ({pct:4.1f}% of cached items)")

    limit = len(found) if args.all else 25
    print(f"\nshowing {min(limit, len(found))} of {len(found)} gaps:")
    for kind, name, evidence in found[:limit]:
        print(f"\n[{kind}] {name}")
        print(f"    {evidence[:300]}")
    await redis.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
