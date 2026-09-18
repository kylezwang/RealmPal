"""Score candidate buff models against stored RealmShark weapon/ability splits.

Every cached board row carries RealmShark's own `weaponDamage` and
`abilityDamage` for a 5s / 8-use / 0 DEF window, which makes them ground truth
for the multipliers we apply. This script reconstructs both halves of every row
under several candidate models and reports the error, so questions like "does
Damaging apply to ability damage?" and "is Exposed a x1.20 or a flat -20 DEF?"
are answered by the data instead of by argument.

The damage model here is deliberately standalone (not imported from
dps_specialist) so a candidate can be measured before production changes.
It mirrors getAverageDamage in rotmg-mirror/rotmg-dps-calculator:

    base = shot_damage x (0.5 + ATT/50)          # abilities skip the ATT part
    if Damaging:  base x= 1.25                   # before DEF
    hit = max(base - def, base x 0.10)           # Exposed is def -= 20
    if Curse:     hit x= 1.25                    # after DEF
    if Vulnerable: hit x= 1.15                   # not in the calculator source

Usage (from the repo root, with the API venv):
    python api/scripts/calibrate_dps_buffs.py
"""
from __future__ import annotations

import asyncio
import statistics
import sys
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis

from api.config import Settings
from api.models.build import Loadout, StatScalingGraph
from api.services.dps_specialist import (
    _SECONDS,
    ability_uses,
    ability_enchants,
    attacks_per_second,
    attack_multiplier,
    estimate_weapon_dps,
    parse_ability_formula,
    reconstruct_ability_damage,
    reconstruct_weapon_damage,
    set_grants_berserk,
    stat_mod_multiplier,
    weapon_enchant_multipliers,
    weapon_enchants,
)
from api.services.realmshark import LOADOUT_CACHE_PREFIX
from api.services.wiki_scaling import read_cached_item


@dataclass(frozen=True)
class Model:
    name: str
    damaging_on_weapon: bool = True
    damaging_on_ability: bool = False
    curse: bool = True
    expose_flat_def: bool = False  # True: def -= 20. False: x1.20 multiplier.
    expose: bool = True
    vulnerable: bool = True
    berserk_sourced: bool = True  # False: always on (the old default)


def _hit(base: float, model: Model, *, damaging: bool) -> float:
    """One projectile's damage on the 0 DEF dummy."""
    if damaging:
        base *= 1.25
    def_eff = -20.0 if (model.expose and model.expose_flat_def) else 0.0
    hit = max(base - def_eff, base * 0.10)
    if model.expose and not model.expose_flat_def:
        hit *= 1.20
    if model.curse:
        hit *= 1.25
    if model.vulnerable:
        hit *= 1.15
    return hit


def weapon_half(
    est: dict, *, att: float, dex: float, model: Model, row: Loadout, berserk: bool
) -> float:
    dmg_mult, rof_mult = weapon_enchant_multipliers(row.debug, weapon_enchants(row))
    rof = float(est.get("rof") or 1.0) * rof_mult
    if berserk:
        rof *= 1.25
    aps = attacks_per_second(dex=dex, rof=rof)
    per_shot = _hit(
        float(est["avg"]) * attack_multiplier(att),
        model,
        damaging=model.damaging_on_weapon,
    )
    volley = per_shot * float(est.get("shots") or 1.0) * dmg_mult
    return volley * aps * _SECONDS


def ability_half(formula: dict, *, stats: dict, row: Loadout, model: Model) -> float:
    stat_name = formula["stat"]
    mod = stat_mod_multiplier(row.debug, ability_enchants(row))
    scaled = float(stats.get(stat_name) or 0) * mod
    base = float(formula["avg"]) + float(formula["per"]) * max(
        0.0, scaled - float(formula["threshold"])
    )
    per_shot = _hit(base, model, damaging=model.damaging_on_ability)
    return per_shot * float(formula["shots"] or 1.0) * ability_uses(row.debug)


MODELS = [
    Model("A current code (Berserk always on)", berserk_sourced=False),
    Model("B current code, Berserk sourced"),
    Model("C Damaging on ability too", damaging_on_ability=True),
    Model("D Exposed as flat -20 DEF", expose_flat_def=True),
    Model(
        "E Damaging on ability + Exposed flat",
        damaging_on_ability=True,
        expose_flat_def=True,
    ),
    Model(
        "F calculator exactly (no Vulnerable, Damaging both, Exposed flat)",
        damaging_on_ability=True,
        expose_flat_def=True,
        vulnerable=False,
    ),
    Model(
        "G calculator, Damaging weapon-only",
        expose_flat_def=True,
        vulnerable=False,
    ),
]


async def main() -> int:
    settings = Settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    rows: list[Loadout] = []
    async for key in redis.scan_iter(f"{LOADOUT_CACHE_PREFIX}*"):
        cached = await redis.get(key)
        if not cached:
            continue
        try:
            graph = StatScalingGraph.model_validate_json(cached)
        except Exception:
            continue
        for build_rows in graph.top_loadouts.values():
            rows.extend(build_rows)

    usable: list[tuple[Loadout, dict, Optional[dict], bool]] = []
    for row in rows:
        if not row.weapon_damage or not row.ability_damage:
            continue
        by_slot = {p.slot.lower(): p.item_name for p in row.equipment}
        weapon_name = by_slot.get("weapon") or row.weapon_name
        ability_name = by_slot.get("ability") or row.ability_name
        if not weapon_name or not ability_name:
            continue
        w_item = await read_cached_item(redis, weapon_name)
        a_item = await read_cached_item(redis, ability_name)
        if not w_item or not a_item:
            continue
        att = float((row.stats or {}).get("Attack") or 0)
        dex = float((row.stats or {}).get("Dexterity") or 0)
        est = estimate_weapon_dps(w_item.stats or {}, dex=dex, att=att)
        if not est:
            continue
        formula = parse_ability_formula(a_item.stats or {})
        worn = [i for i in (w_item, a_item) if i]
        for slot in ("armor", "ring"):
            name = by_slot.get(slot)
            if name:
                extra = await read_cached_item(redis, name)
                if extra:
                    worn.append(extra)
        enchant_texts = [
            (p.item_name, f"{e.name}: {e.value}")
            for p in row.equipment
            for e in (p.enchants or [])
        ]
        berserk = set_grants_berserk(worn, enchant_texts=enchant_texts)
        usable.append((row, est, formula, berserk))

    print(f"cached rows: {len(rows)}, usable with wiki data + splits: {len(usable)}")
    if not usable:
        print("Nothing to calibrate. Warm the specialist stores first.")
        await redis.aclose()
        return 1
    sourced = sum(1 for _r, _e, _f, b in usable if b)
    print(f"rows whose own set can produce Berserk: {sourced}/{len(usable)}")

    print(
        f"\n{'model':52} {'weapon err':>12} {'ability err':>12} {'total err':>11}"
    )
    print("-" * 90)

    # Baseline through the real reconstructors, so the number quoted in docs is
    # the one production actually produces. The candidate rows below use the
    # standalone model, which is the only way to try the flat-DEF Exposed
    # variant, and they differ from this row on the weapon half because the
    # standalone model does not read buffs or ability-use count out of
    # row.debug. Compare candidates to each other, not to this row.
    w_errs, a_errs, t_errs = [], [], []
    for row, est, formula, berserk_source in usable:
        att = float((row.stats or {}).get("Attack") or 0)
        dex = float((row.stats or {}).get("Dexterity") or 0)
        w = reconstruct_weapon_damage(
            est,
            att=att,
            dex=dex,
            debug=row.debug,
            enchants=weapon_enchants(row),
            berserk_source=berserk_source,
        )
        w_errs.append(w / row.weapon_damage - 1.0)
        if formula:
            a = reconstruct_ability_damage(
                formula,
                stats=row.stats or {},
                debug=row.debug,
                enchants=ability_enchants(row),
            )
            a_errs.append(a / row.ability_damage - 1.0)
            t_errs.append((w + a) / (row.weapon_damage + row.ability_damage) - 1.0)
    med = lambda xs: statistics.median(xs) * 100 if xs else float("nan")
    print(
        f"{'PRODUCTION (real reconstructors, current model)':52} "
        f"{med(w_errs):>+11.1f}% {med(a_errs):>+11.1f}% {med(t_errs):>+10.1f}%"
    )
    print("-" * 90)

    for model in MODELS:
        w_errs: list[float] = []
        a_errs: list[float] = []
        t_errs: list[float] = []
        for row, est, formula, berserk_source in usable:
            att = float((row.stats or {}).get("Attack") or 0)
            dex = float((row.stats or {}).get("Dexterity") or 0)
            berserk = berserk_source if model.berserk_sourced else True
            w = weapon_half(
                est, att=att, dex=dex, model=model, row=row, berserk=berserk
            )
            if row.weapon_damage:
                w_errs.append(w / row.weapon_damage - 1.0)
            a = None
            if formula:
                a = ability_half(
                    formula, stats=row.stats or {}, row=row, model=model
                )
                if row.ability_damage:
                    a_errs.append(a / row.ability_damage - 1.0)
            if a is not None and row.weapon_damage and row.ability_damage:
                t_errs.append(
                    (w + a) / (row.weapon_damage + row.ability_damage) - 1.0
                )
        med = lambda xs: statistics.median(xs) * 100 if xs else float("nan")
        print(
            f"{model.name:52} {med(w_errs):>+11.1f}% {med(a_errs):>+11.1f}% "
            f"{med(t_errs):>+10.1f}%"
        )
    print("\nMedian signed error vs RealmShark's own stored halves. Closest to 0 wins.")
    await redis.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
