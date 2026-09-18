"""DPS specialist: RealmShark potential-DPS numbers are the source of truth.

Wiki shot data plus the board's ATT/DEX/enchants reconstruct the weapon
half. Wiki ability scaling (base + per-stat over a threshold) plus Stat
Mod Multiplier reconstruct the ability half. Every equipped wiki page and
on-character enchant is scanned for status grants and stat procs before
those numbers are reconstructed. Modifications scale the stored
RealmShark weapon and ability numbers by those formulas' ratios.
Chat is cache_only.

RealmShark windows are 5s / 8 ability uses, 0 DEF, full buffs. Not live
combat. Minion extra volleys sit in the ability residual.
"""
from __future__ import annotations

import re
from html import unescape
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from ..models.build import CLASS_ALIASES, PLAYER_STATS, STAT_ALIASES, ItemEnchant, Loadout
from ..models.item import ItemProfile
from ..models.player import CharacterSummary, PlayerProfile
from .player_lookup import extract_player_ign, get_or_scrape_player
from .wiki_scaling import (
    CLASS_MAXSTATS_PREFIX,
    is_item_marked_missing,
    mark_item_missing,
    on_equip_bonuses,
    read_cached_item,
)

_DPS_WORD = re.compile(
    r"\b(dps|damage\s+per\s+second|potential[- ]dps|potential damage)\b",
    re.I,
)
_STAT_NAMES = (
    r"(?:hp|mp|att|atk|dex|def|spd|vit|wis|life|mana|attack|defense|"
    r"defence|speed|dexterity|vitality|wisdom|stats?)"
)
_MAX_STAT = re.compile(
    rf"(?:how\s+much|how\s+many|what(?:'s|s| is))\s+"
    rf"(?:the\s+)?(?:max(?:imum)?|highest|most)\s+"
    rf"(?:possible\s+)?{_STAT_NAMES}"
    rf"|how\s+much\s+{_STAT_NAMES}"
    rf"|(?:max(?:imum)?(?:\s+achievable)?|highest(?:\s+possible)?)\s+{_STAT_NAMES}"
    rf"|{_STAT_NAMES}\s+(?:a\s+\w+\s+)?could\s+have"
    r"|(?:only|just)\s+numbers|numbers\s+only"
    r"|without\s+(?:a\s+)?sets?"
    r"|i don'?t want builds",
    re.I,
)
_SET_ASK = re.compile(
    r"\b(builds?|loadouts?|gear|equip|best items?|sets?|shiny divine)\b",
    re.I,
)
# "Explain the number you just gave me" in all the ways players write it.
# None of these name DPS, a class, a stat, or an IGN, which is exactly why
# they used to fall out of the DPS slot - see is_dps_follow_up.
_DPS_FOLLOW_UP = re.compile(
    r"break\s?downs?\b"
    r"|break\s+(?:it|that|this|them|those)\s+down"
    r"|show\s+(?:me\s+)?(?:the\s+|your\s+|that\s+)?"
    r"(?:math|maths|work|working|numbers?|calculation|calc)\b"
    r"|what\s+(?:do|does|are|is)\s+(?:the|that|those|these)\s+numbers?"
    r"|(?:the\s+)?numbers?\s+look\s+like"
    r"|how\s+(?:did|do)\s+you\s+"
    r"(?:get|got|calculate|calculated|work\s+(?:that\s+)?out|arrive)"
    r"|where\s+(?:did|does)\s+(?:that|this|it|those)\s+(?:come|numbers?)"
    r"|walk\s+me\s+through"
    r"|explain\s+(?:the|that|this|those|your)\b"
    r"|per\s+(?:shot|use|second)\b"
    r"|(?:is|are)\s+(?:that|those|these|it)\s+"
    r"(?:numbers?\s+)?(?:actually\s+)?(?:right|correct|accurate)"
    r"|prove\s+it\b"
    r"|source\s+for\s+(?:that|those)",
    re.I,
)
# "What if he used X instead" - a potential, not a new question. These used to
# reach the skin visualizer ("what if he swapped to a Doom Bow?" routed to the
# dye previewer) instead of rescaling the reconstruct.
_DPS_WHAT_IF = re.compile(
    r"what\s+if\b"
    r"|how\s+about\b"
    r"|instead\s+of\b"
    r"|\bif\s+(?:he|she|they|it|i|we)\s+"
    r"(?:had\s+|were\s+|was\s+)?"
    r"(?:swap|swaps|swapped|switch|switches|switched|use|uses|used|"
    r"wear|wears|wore|equip|equips|equipped|ran|run|runs)\b"
    r"|\b(?:swap|swapped|switch|switched|replace|replaced)\s+"
    r"(?:it|that|this|them|in|out|to|for|his|her|their|the)\b",
    re.I,
)
# "Is that good?" - a comparison against a board or another set still needs the
# reconstruct in context, otherwise the model compares a number it no longer has.
_DPS_COMPARE = re.compile(
    r"how\s+(?:does|do|would)\s+(?:that|those|it|this|he|she|they)\s+compare"
    r"|compares?\s+(?:to|with|against)"
    r"|compared\s+(?:to|with|against)"
    r"|\b(?:vs\.?|versus)\b"
    r"|(?:better|worse|higher|lower|more|less)\s+than\b"
    r"|how\s+(?:close|far)\s+(?:is|are|off)\b"
    r"|(?:is|are)\s+(?:that|those|it)\s+(?:any\s+)?(?:good|bad|high|low|competitive)",
    re.I,
)
# Wiki infoboxes use hyphen, en dash, em dash, or minus between min and max.
_DASH = r"[-\u2013\u2014\u2212]"
_RANGE = re.compile(rf"(\d+(?:\.\d+)?)\s*{_DASH}\s*(\d+(?:\.\d+)?)")
_NUM = re.compile(r"(\d+(?:\.\d+)?)")
# RealmEye writes four-digit damage with a thousands separator, and `\d+` stops
# at the comma: "Damage: 900-1,100" parsed as the range 900 to 1, so Venerable
# Doom Bow reconstructed at roughly half a point of damage per shot. Only a
# comma sitting between two digits is removed, so "Drops from X, Y" is untouched.
_THOUSANDS = re.compile(r"(?<=\d),(?=\d)")
# Wiki: DEF can never reduce a hit below 10% of its pre-DEF damage.
_MIN_HIT_FRACTION = 0.10
# The guild hall practice dummy, which is what a player can actually measure
# against. RealmShark's boards price a 0 DEF dummy with full party buffs.
_GUILD_DUMMY_DEF = 15.0
_ARMOR_PIERCING = re.compile(r"ignores\s+defense\s+of\s+target", re.I)
# "Summon Effect(s)" describes a separate summoned entity whose damage is not in
# the weapon's own Damage row, so its piercing says nothing about the shots we
# are pricing. Makakoyumi is the case in point: the bow's two projectiles are
# normal, only the summon pierces. Reading every row exempted 96 cached weapons
# from enemy DEF that should pay it in full.
_SUMMON_ROW = re.compile(r"summon", re.I)


def armor_piercing(stats: dict) -> bool:
    """True when the weapon's OWN shots ignore enemy defense."""
    return any(
        _ARMOR_PIERCING.search(str(value or ""))
        for key, value in (stats or {}).items()
        if not _SUMMON_ROW.search(str(key or ""))
    )


def summon_pierces(stats: dict) -> bool:
    """True when a Summon Effect(s) row says the summon's shots ignore defense."""
    return any(
        _ARMOR_PIERCING.search(str(value or ""))
        for key, value in (stats or {}).items()
        if _SUMMON_ROW.search(str(key or ""))
    )


def tag_group_piercing(groups: list[dict], stats: dict) -> None:
    """Mark which projectile groups ignore enemy DEF.

    Piercing is a property of a projectile, not of a weapon. Makakoyumi lists
    two groups in one Damage row, `800; 20-40` at `33%; 200%`: the 800 is the
    bow's own shot and pays DEF in full, while the 20-40 at 200% is the summon,
    which ignores it. Its `Effect(s)` and `Summon Effect(s)` rows are separate
    for exactly this reason. Charging both groups DEF, or exempting both,
    misprices every summon weapon.

    The wiki lists the wielder's shot first and the summon's after, so with a
    summon row present the trailing group is the summon's. With only one group
    the summon's projectile is not itemised, so nothing here pierces on its
    account.
    """
    own = armor_piercing(stats)
    summon = summon_pierces(stats) and len(groups) > 1
    for index, group in enumerate(groups):
        group["pierces"] = own or (summon and index == len(groups) - 1)


def _digits(text: str) -> str:
    return _THOUSANDS.sub("", text or "")
_ON_ITEM = re.compile(
    r"\b(?:of|for|for a|on)\s+(?:the\s+)?(.+?)\s*$",
    re.I,
)
_SWAP = re.compile(
    r"\b(?:instead of|swap|replace|what if i (?:use|equip)|if i (?:use|swap))\b",
    re.I,
)

# RealmEye Dex vs Att: 1.5 APS at 0 DEX, 8 APS at 75 DEX, times Rate of Fire.
# RealmShark's calculator does not cap DEX at 75 (Attack Wizard rows sit at
# 95 DEX and the weapon half only matches if that extra DEX still adds APS).
_BASE_APS = 1.5
_DEX_APS = 6.5
_DEX_CAP = 75.0
_DEFAULT_DEX = 75.0
_DEFAULT_ATT = 75.0
_SECONDS = 5.0
_ABILITY_USES = 8
# Wiki status effects + Haizor calculator: Damaging and Curse are +25%.
# Exposed is -20 DEF on a real enemy. RealmShark's 0 DEF dummy numbers
# match Exposed as x1.20, so the dummy reconstruct uses that.
# Vulnerable is 115% damage taken (Quiver of Thunder wiki).
_DAMAGING = 1.25
_CURSE = 1.25
_EXPOSE = 1.20
_VULNERABLE = 1.15
_BERSERK_ROF = 1.25
# Enchanting wiki I-IV. Debug.weaponEnchant wins when present.
_FLURRY_DMG, _FLURRY_ROF = 0.8, 1.35
_OVERWHELM_DMG, _OVERWHELM_ROF = 1.35, 0.8
_DAMAGE_TRADEOFF = {1: (0.05, -0.02), 2: (0.075, -0.03), 3: (0.10, -0.04), 4: (0.125, -0.05)}
_FIRERATE_TRADEOFF = {1: (0.05, -0.02), 2: (0.075, -0.03), 3: (0.10, -0.04), 4: (0.125, -0.05)}
_DAMAGE_BONUS = {1: 0.02, 2: 0.03, 3: 0.04, 4: 0.05}
_FIRERATE_BONUS = {1: 0.02, 2: 0.03, 3: 0.04, 4: 0.05}


def is_dps_query(message: str, history: Optional[list[str]] = None) -> bool:
    text = message or ""
    if _DPS_WORD.search(text) or _MAX_STAT.search(text):
        return True
    return is_dps_follow_up(text, history=history)


def is_dps_follow_up(message: str, history: Optional[list[str]] = None) -> bool:
    """A breakdown or what-if turn that only means DPS given the last turn.

    These name no class, stat, IGN, or the word DPS, so nothing in the routing
    chain recognised them. Found live Sep 17: after a correct "What's the DPS
    for Turbine's bard?", the follow-up "What do the numbers look like?" routed
    to the four gear agents, arrived with no reconstruct, and Claude concluded
    it had invented the numbers it had just been handed and apologised.

    Gated on history: "give me a breakdown" in a dungeon conversation is not a
    DPS ask, so an earlier turn has to have actually been one.
    """
    text = message or ""
    if not _is_follow_up_text(text):
        return False
    # Walk backwards through the conversation. Bare follow-ups keep the chain
    # alive, so a long string of "and the breakdown?" / "what if he used X?"
    # turns all stay on DPS. An explicit DPS ask closes the chain as a match. A
    # turn that raises its own topic ends it, so "how do I do Shatters?"
    # followed by "explain that" does not come back here.
    for prev in reversed(history or []):
        if _DPS_WORD.search(prev or "") or _MAX_STAT.search(prev or ""):
            return True
        if _is_follow_up_text(prev or ""):
            continue
        return False
    return False


def _is_follow_up_text(text: str) -> bool:
    return bool(
        _DPS_FOLLOW_UP.search(text)
        or _DPS_WHAT_IF.search(text)
        or _DPS_COMPARE.search(text)
    )


def class_in_text(message: str) -> Optional[str]:
    """The single class named outright in this text, no typo correction."""
    found: list[str] = []
    lower = (message or "").lower()
    for canon, aliases in CLASS_ALIASES.items():
        needles = (canon.lower(),) + tuple(aliases)
        if any(re.search(rf"\b{re.escape(n)}\b", lower) for n in needles):
            if canon not in found:
                found.append(canon)
    return found[0] if len(found) == 1 else None


def dps_subject_from_history(
    history: Optional[list[str]] = None,
) -> tuple[Optional[str], Optional[str]]:
    """The (player IGN, class) the conversation's most recent DPS turn was about.

    A follow-up carries neither, so without this a breakdown request cannot
    re-derive whose character the numbers described.
    """
    for prev in reversed(history or []):
        if not (_DPS_WORD.search(prev or "") or _MAX_STAT.search(prev or "")):
            continue
        ign = extract_player_ign(prev)
        class_name = class_in_text(prev)
        if ign or class_name:
            return ign, class_name
    return None, None


def is_stat_number_query(message: str, history: Optional[list[str]] = None) -> bool:
    """User wants DPS or max-stat numbers, not a recommended set.

    'What's the max defense for necromancer?' and 'how much DPS on cbow'
    are numbers. 'Best DPS necro set' still goes through gear agents with
    the DPS slot appended.
    """
    text = message or ""
    if not is_dps_query(text, history=history):
        return False
    if re.search(
        r"without\s+(?:a\s+)?sets?|(?:only|just)\s+numbers|i don'?t want builds",
        text,
        re.I,
    ):
        return True
    if _SET_ASK.search(text):
        return False
    return True


def parse_damage_range(text: str) -> Optional[tuple[float, float]]:
    if not text:
        return None
    text = _digits(text)
    match = _RANGE.search(text)
    if match:
        return float(match.group(1)), float(match.group(2))
    avg = re.search(r"average:\s*(\d+(?:\.\d+)?)", text or "", re.I)
    if avg:
        value = float(avg.group(1))
        return value, value
    num = _NUM.search(text)
    if num:
        value = float(num.group(1))
        return value, value
    return None


def parse_shots(text: str) -> float:
    if not text:
        return 1.0
    num = _NUM.search(_digits(text))
    return float(num.group(1)) if num else 1.0


def parse_shot_groups(
    damage_text: str, shots_text: str, rof_text: str = ""
) -> list[dict]:
    """Bolt Thrower: '110-125; 80-90' with shots '1; 4' is two burst groups.

    RealmEye separates a weapon's projectile definitions with ';' in every row,
    and two different things wear that shape:

    Pattern A, one Rate of Fire and several damage groups making up a single
    volley, where `Shots` covers all of them. Aspirant's Bow is
    "110-120; 35-45" with `Shots: 3`, a main arrow plus two weaker side arrows.
    Averaging across the shots is right here. 72 of 479 cached weapons.

    Pattern B, a Rate of Fire that is itself a list, so each group is a separate
    firing mode at its own rate. Makakoyumi is "Damage: 800; 20-40" at
    "Rate of Fire: 33%; 200%". These cannot share one rate: the 800 shot fires
    at a third of the normal speed and the 20-40 shot at double. 36 of 479.

    Splitting on ';' first also rescues a group stated as a bare number with no
    range. `_RANGE.findall` skipped Makakoyumi's `800` outright, leaving a
    30-damage bow, which is how the highest-DPS bow in the game reconstructed to
    3,063.3 damage over 5s. 10 cached groups are bare like this.
    """
    damage_text = _digits(damage_text or "")
    parts = [p for p in re.split(r";", damage_text) if p.strip()]
    ranges: list[tuple[float, float]] = []
    for part in parts:
        one = parse_damage_range(part)
        if one:
            ranges.append(one)
    if not ranges:
        one = parse_damage_range(damage_text)
        if one:
            ranges = [one]
    if not ranges:
        return []

    # Shots and rates are per group when listed, otherwise shared by all.
    shot_parts = [p.strip() for p in re.split(r"[;|/]", shots_text or "1") if p.strip()]
    shots = [parse_shots(part) for part in shot_parts] or [1.0]
    if len(shots) < len(ranges):
        shots.extend([shots[-1]] * (len(ranges) - len(shots)))
    rof_parts = [p.strip() for p in re.split(r";", rof_text or "") if p.strip()]
    rates = [parse_rof(part) for part in rof_parts]
    per_group_rof = len(rates) > 1
    if not rates:
        rates = [1.0]
    if len(rates) < len(ranges):
        rates.extend([rates[-1]] * (len(ranges) - len(rates)))

    groups = []
    for i, (low, high) in enumerate(ranges):
        groups.append(
            {
                "min": low,
                "max": high,
                # RealmEye Weapon Attributes: "The highest damage number is never
                # rolled on any weapon ... the average damage of each weapon is
                # one-half less than the average of the min-max values would
                # indicate." Only for a real range; a fixed-damage shot always
                # rolls its stated value.
                "avg": ((low + high) / 2.0 - 0.5) if high > low else low,
                "shots": shots[i] if i < len(shots) else 1.0,
                "rof": rates[i] if i < len(rates) else rates[-1],
                "own_rof": per_group_rof,
            }
        )
    return groups


def parse_rof(text: str) -> float:
    """Wiki Rate of Fire: 100% → 1.0, 1.2 → 1.2x."""
    if not text:
        return 1.0
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if pct:
        return float(pct.group(1)) / 100.0
    num = _NUM.search(text)
    if not num:
        return 1.0
    value = float(num.group(1))
    return value / 100.0 if value > 3 else value


def attacks_per_second(*, dex: float, rof: float) -> float:
    return (_BASE_APS + _DEX_APS * (dex / _DEX_CAP)) * rof


def attack_multiplier(att: float) -> float:
    return 0.5 + att / 50.0


def estimate_weapon_dps(
    stats: dict,
    *,
    dex: float = _DEFAULT_DEX,
    att: float = _DEFAULT_ATT,
) -> Optional[dict]:
    damage_text = str(stats.get("Damage") or stats.get("damage") or "")
    shots_text = str(stats.get("Shots") or stats.get("shots") or "1")
    rof_text = str(
        stats.get("Rate of Fire") or stats.get("Fire Rate") or stats.get("RoF") or ""
    )
    groups = parse_shot_groups(damage_text, shots_text, rof_text)
    if not groups:
        return None
    burst = sum(g["avg"] * g["shots"] for g in groups)
    shots = sum(g["shots"] for g in groups)
    avg = burst / shots if shots else 0.0
    rof = parse_rof(rof_text)
    aps = attacks_per_second(dex=dex, rof=rof)
    att_m = attack_multiplier(att)
    # Damage per second before the ATT multiplier, with each group counted at its
    # own rate of fire. For a weapon with one rate this is exactly burst x aps,
    # so single-projectile numbers are unchanged.
    per_second = sum(
        g["avg"] * g["shots"] * attacks_per_second(dex=dex, rof=g["rof"])
        for g in groups
    )
    multi_rof = any(g["own_rof"] for g in groups)
    tag_group_piercing(groups, stats)
    for group in groups:
        group["aps"] = attacks_per_second(dex=dex, rof=group["rof"])
    return {
        "min": groups[0]["min"],
        "max": groups[-1]["max"],
        "avg": avg,
        "shots": shots,
        "burst": burst,
        "groups": groups,
        "rof": rof,
        "multi_rof": multi_rof,
        "per_second": per_second,
        "armor_piercing": all(g["pierces"] for g in groups),
        "any_piercing": any(g["pierces"] for g in groups),
        "dex": dex,
        "att": att,
        "aps": aps,
        "att_mult": att_m,
        "dps": per_second * att_m,
    }


def weapon_enchant_multipliers(
    debug: Optional[dict],
    enchants: Optional[list[ItemEnchant]] = None,
) -> tuple[float, float]:
    """Damage and RoF multipliers. RealmShark debug wins; else enchanting wiki."""
    debug = debug or {}
    weapon = debug.get("weaponEnchant") if isinstance(debug.get("weaponEnchant"), dict) else {}
    has_debug = False
    dmg_mult = 1.0
    rof_mult = 1.0
    if weapon:
        try:
            if weapon.get("weaponDamageMult") not in (None, ""):
                dmg_mult = float(weapon.get("weaponDamageMult") or 1.0)
                has_debug = True
        except (TypeError, ValueError):
            dmg_mult = 1.0
        try:
            if weapon.get("weaponRofMult") not in (None, ""):
                rof_mult = float(weapon.get("weaponRofMult") or 1.0)
                has_debug = True
        except (TypeError, ValueError):
            rof_mult = 1.0
    if has_debug:
        return dmg_mult, rof_mult
    dmg_mult = 1.0
    rof_mult = 1.0
    for enc in enchants or []:
        if classify_enchant(enc) != "weapon_shot":
            continue
        name = (enc.name or "").lower()
        rank = _enchant_rank(enc.name, enc.value)
        if "flurry of blows" in name:
            dmg_mult *= _FLURRY_DMG
            rof_mult *= _FLURRY_ROF
        elif "overwhelming strikes" in name:
            dmg_mult *= _OVERWHELM_DMG
            rof_mult *= _OVERWHELM_ROF
        elif "damage tradeoff" in name and rank:
            plus, minus = _DAMAGE_TRADEOFF[rank]
            dmg_mult *= 1.0 + plus
            rof_mult *= 1.0 + minus
        elif re.search(r"fire\s*rate\s*tradeoff|firerate\s*tradeoff", name) and rank:
            plus, minus = _FIRERATE_TRADEOFF[rank]
            rof_mult *= 1.0 + plus
            dmg_mult *= 1.0 + minus
        elif re.search(r"^damage bonus|^weapon damage bonus", name) and rank:
            dmg_mult *= 1.0 + _DAMAGE_BONUS[rank]
        elif re.search(r"fire\s*rate bonus|firerate bonus", name) and rank:
            rof_mult *= 1.0 + _FIRERATE_BONUS[rank]
    return dmg_mult, rof_mult


_SHEET_STAT_ALT = "|".join(
    sorted(
        {re.escape(token) for token in (*STAT_ALIASES, *(s.lower() for s in PLAYER_STATS))},
        key=len,
        reverse=True,
    )
)
_SHEET_STAT_RE = re.compile(rf"\b(?:{_SHEET_STAT_ALT})\b", re.I)
_SHEET_TRADEOFF_RE = re.compile(
    rf"\b(?:{_SHEET_STAT_ALT})\b(?:\s*[-/]\s*|\s+)(?:{_SHEET_STAT_ALT})\b[\s-]*tradeoff",
    re.I,
)
_WEAPON_SHOT_RE = re.compile(
    r"flurry of blows|overwhelming strikes|"
    r"damage tradeoff|fire\s*rate\s*tradeoff|firerate\s*tradeoff|"
    r"damage bonus|weapon damage bonus|fire\s*rate bonus|firerate bonus",
    re.I,
)
_PROJECTILE_SPEED_RE = re.compile(r"projectile\s*speed", re.I)


def sheet_stats_named(text: str) -> list[str]:
    """Canonical 8/8 stats mentioned in an enchant name or tooltip line."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _SHEET_STAT_RE.finditer(text or ""):
        canon = STAT_ALIASES.get(match.group(0).lower())
        if canon and canon not in seen:
            seen.add(canon)
            found.append(canon)
    return found


def classify_enchant(enc: ItemEnchant) -> str:
    """Which reconstruct channel an on-character enchant actually enters.

    weapon_shot: named fire-rate / weapon-damage rolls (Flurry, Damage
    Tradeoff, Fire Rate Tradeoff, ...). These multiply shots.
    sheet_stat: any 8/8-stat bonus or tradeoff. Already inside the RealmEye
    sheet for a player reconstruct. APS still reads Dexterity only; Attack
    is the (0.5+ATT/50) line; Speed/Vitality/etc. matter when the ability
    formula or a working-stat proc uses them, not as fire rate.
    projectile_travel: projectile speed. Not damage, not APS.
    """
    blob = f"{enc.name or ''} {enc.value or ''}"
    if _WEAPON_SHOT_RE.search(blob):
        return "weapon_shot"
    if _STAT_MOD_NAME.search(blob):
        return "ability_scale"
    if (
        _MP_COST_NAME.search(blob)
        or _FLAT_REGEN_NAME.search(blob)
        or _PCT_REGEN_NAME.search(blob)
    ):
        return "ability_sustain"
    if _PROJECTILE_SPEED_RE.search(blob):
        return "projectile_travel"
    if _SHEET_TRADEOFF_RE.search(blob) or (
        sheet_stats_named(blob)
        and re.search(r"\b(tradeoff|bonus|relative)\b", blob, re.I)
        and not re.search(r"\b(?:weapon\s+)?damage\b|\bfire\s*rate\b", blob, re.I)
    ):
        return "sheet_stat"
    return "other"


def format_enchant_channel(
    enc: ItemEnchant, *, ability_stat: Optional[str] = None
) -> str:
    kind = classify_enchant(enc)
    stats = sheet_stats_named(f"{enc.name} {enc.value or ''}")
    if kind == "weapon_shot":
        dmg, rof = weapon_enchant_multipliers({}, [enc])
        return (
            f"{enc.name} (weapon-shot: damage ×{dmg:.2f}, fire rate ×{rof:.2f})"
        )
    if kind == "sheet_stat":
        named = "/".join(stats) if stats else "8/8"
        feeds: list[str] = []
        if ability_stat and ability_stat in stats:
            feeds.append(
                f"this ability scales with {ability_stat}, so that sheet "
                "value is in the ability half"
            )
        if "Dexterity" in stats:
            feeds.append(
                "sheet Dexterity is what APS reads; this is not a fire-rate "
                "enchant"
            )
        if "Attack" in stats:
            feeds.append(
                "sheet Attack is the (0.5+ATT/50) line; this is not a "
                "weapon-damage enchant"
            )
        if feeds:
            via = " " + "; ".join(feeds) + "."
        else:
            via = (
                " Already in the RealmEye sheet. APS is (1.5 + 6.5×DEX/75) × "
                "item fire rate and does not read this stat. The ability half "
                "only reads it when its wiki formula uses it."
            )
        return f"{enc.name} (sheet {named}.{via})"
    if kind == "projectile_travel":
        return (
            f"{enc.name} (projectile travel speed only; not damage, not fire rate)"
        )
    if kind == "ability_scale":
        return f"{enc.name} (multiplies the ability scaling stat, not APS)"
    if kind == "ability_sustain":
        return f"{enc.name} (mana / MP cost; not dummy damage in this window)"
    return enc.name


def _debug_mults(
    debug: dict,
    *,
    enchants: Optional[list[ItemEnchant]] = None,
    kind: str = "weapon",
    berserk_source: bool = False,
) -> tuple[float, float, float, bool, float, float]:
    dmg_mult, rof_mult = weapon_enchant_multipliers(debug, enchants)
    buffs = debug.get("buffs") if isinstance(debug.get("buffs"), dict) else {}
    dmg_buff = 1.0
    # Damaging applies to ability damage as well as weapon damage. The RealmEye
    # status-effects page says "weapons", but the official calculator multiplies
    # any projectile's base damage by 1.25 (getAverageDamage in
    # rotmg-mirror/rotmg-dps-calculator), and RealmShark's own stored halves
    # agree: across the 133 cached board rows that carry both a weaponDamage and
    # an abilityDamage, restricting Damaging to the weapon left the ability half
    # a median 26.7% under RealmShark, and applying it to both brought that to
    # 8.4%. Berserk is the only one of the five that stays weapon-only, because
    # it buys attack speed rather than damage. Re-measure with
    # api/scripts/calibrate_dps_buffs.py before changing any of this.
    # Split around DEF. The official calculator applies Damaging to the base
    # before subtracting DEF and Curse to the result after, which only matters
    # once enemy DEF is non-zero, but it matters a lot then: on a 15 DEF guild
    # hall dummy the two orders differ on every shot.
    pre_def = 1.0
    if buffs.get("damaging", True):
        pre_def *= _DAMAGING
    post_def = 1.0
    if buffs.get("curse", True):
        post_def *= _CURSE
    if buffs.get("expose", True):
        post_def *= _EXPOSE
    if buffs.get("vulnerable", True):
        post_def *= _VULNERABLE
    dmg_buff = pre_def * post_def
    # Berserk is not a party assumption the way Damaging/Curse/Exposed/
    # Vulnerable are. RealmShark's potential DPS only carries it when the
    # character's own set or enchants can produce it (rank 1 Attack Bard has
    # `OnHit Berserk II` on Ritual Robe, which would be pointless in the
    # calculation if everyone got Berserk for free). Defaulting it on inflated
    # every player-set reconstruct by the full x1.25 APS: Turbine's Bard came
    # out at 23,455.1 against RealmShark's own 21,381.1 for the same character,
    # +9.7%, and the model then credited the buff to Vesture of Duality, which
    # grants nothing of the kind. Sourced from the worn set, the same character
    # reconstructs to 21,082.5, -1.4%.
    berserk = bool(buffs.get("berserk", berserk_source)) if kind == "weapon" else False
    return dmg_mult, rof_mult, dmg_buff, berserk, pre_def, post_def


# A grant gated on being nearly dead, or sitting behind a cooldown far longer
# than the window being priced, is a survival panic button and not a DPS buff.
# Amulet of Restoration's only Berserk is "Last Stand: On shooting below 20% HP
# gain Healing, Berserk and Armored for 4 seconds" on a 1800 second cooldown, and
# counting it gave Turbine's Huntress a permanent x1.25 attack speed.
_LOW_HEALTH_GATE = re.compile(
    r"(?:below|under|less\s+than|at\s+or\s+below)\s*\d+\s*%\s*(?:hp|health|life)"
    r"|\blast\s+stand\b|\bwhen\s+(?:near\s+)?death\b",
    re.I,
)
_COOLDOWN = re.compile(r"cooldown[:\s]*(\d+(?:\.\d+)?)\s*(seconds?|s\b|minutes?)?", re.I)
# Generous: a proc that comes back within a minute can plausibly be up for the
# 5s window being priced. 1800s cannot.
_MAX_SUSTAINABLE_COOLDOWN = 60.0


def grant_is_sustainable(text: str) -> bool:
    """Could this grant realistically be up during the 5s window?"""
    blob = text or ""
    if _LOW_HEALTH_GATE.search(blob):
        return False
    match = _COOLDOWN.search(blob)
    if match:
        seconds = float(match.group(1))
        if (match.group(2) or "").lower().startswith("min"):
            seconds *= 60.0
        if seconds > _MAX_SUSTAINABLE_COOLDOWN:
            return False
    return True


def set_grants_berserk(
    items: Optional[list[ItemProfile]] = None,
    *,
    enchant_texts: Optional[list[tuple[str, str]]] = None,
) -> bool:
    """Can anything this character wears realistically produce Berserk?

    Chance and On Hit rolls count here even though they are not 100% dummy
    uptime, because the number being reconstructed is a potential ceiling and
    RealmShark's own rows behave the same way. A grant that requires the player
    to be under 20% HP, or that is on a cooldown far longer than the window, does
    not count: that is not a ceiling, it is a different situation entirely.
    """
    for item in items or []:
        evidence = parse_status_grants(item).get("berserk")
        if evidence is not None and grant_is_sustainable(evidence):
            return True
    return any(
        re.search(r"\bberserk\b", text or "", re.I) and grant_is_sustainable(text)
        for _name, text in enchant_texts or []
    )


def reconstruct_weapon_damage(
    estimate: dict,
    *,
    att: float,
    dex: float,
    debug: Optional[dict] = None,
    enchants: Optional[list[ItemEnchant]] = None,
    seconds: float = _SECONDS,
    steps: Optional[dict] = None,
    berserk_source: bool = False,
    enemy_def: float = 0.0,
) -> float:
    """Reverse-engineered weapon half of a RealmShark 5s window.

    burst (avg x shots, including extra arc groups) x
    ((1.5 + 6.5 x DEX/75) x item Rate of Fire x enchant RoF x Berserk) x
    ATT multiplier x enchant damage x Damaging x Curse x Exposed x Vulnerable.

    The stored RealmShark weaponDamage wins when they disagree. Use the
    ratio of two reconstructions to scale that stored number after a swap.

    Pass steps to collect the intermediate factors. The brief prints them so a
    "how did you get that?" follow-up can be answered from context instead of
    the model re-deriving (or disowning) its own number.
    """
    dmg_mult, rof_mult, dmg_buff, berserk, pre_def, post_def = _debug_mults(
        debug or {},
        enchants=enchants,
        kind="weapon",
        berserk_source=berserk_source,
    )
    rof = float(estimate.get("rof") or 1.0) * rof_mult
    if berserk:
        rof *= _BERSERK_ROF
    aps = attacks_per_second(dex=dex, rof=rof)
    att_m = attack_multiplier(att)
    burst = float(estimate.get("burst") or (float(estimate["avg"]) * float(estimate["shots"])))
    # A weapon whose Rate of Fire row is a list fires each projectile group at
    # its own rate, so one blended APS cannot represent it. Sum the groups
    # instead. Identical to burst x aps when there is a single rate.
    groups = estimate.get("groups") or []
    # DEF is subtracted from every projectile, so it hits a multi-shot weapon
    # harder than a single-shot one and cannot be applied to the total. Armor
    # piercing ignores it outright. The floor is 10% of the pre-DEF hit.
    piercing = bool(estimate.get("armor_piercing"))
    shield = max(0.0, float(enemy_def or 0.0))

    def _hit(avg: float, pierces: bool = False) -> float:
        base = avg * att_m * dmg_mult * pre_def
        if pierces:
            return base * post_def
        return max(base - shield, base * _MIN_HIT_FRACTION) * post_def

    if estimate.get("multi_rof") and groups:
        rate_scale = rof_mult * (_BERSERK_ROF if berserk else 1.0)
        per_second = sum(
            _hit(g["avg"], g.get("pierces", piercing))
            * g["shots"]
            * attacks_per_second(dex=dex, rof=float(g["rof"]) * rate_scale)
            for g in groups
        )
    elif groups:
        per_second = (
            sum(_hit(g["avg"], g.get("pierces", piercing)) * g["shots"] for g in groups)
            * aps
        )
    else:
        per_second = _hit(float(estimate["avg"]), piercing) * float(estimate["shots"]) * aps
    total = per_second * seconds
    if steps is not None:
        steps.update(
            {
                "avg": float(estimate.get("avg") or 0.0),
                "shots": float(estimate.get("shots") or 1.0),
                "burst": burst,
                "base_rof": float(estimate.get("rof") or 1.0),
                "enchant_rof_mult": rof_mult,
                "rof": rof,
                "aps": aps,
                # per_second is the finished rate: ATT multiplier, weapon
                # enchants, buffs and enemy DEF are already inside it, because
                # DEF has to be subtracted per projectile and cannot be applied
                # to a total afterwards. total is per_second x seconds, nothing
                # more.
                "per_second": per_second,
                "enemy_def": shield,
                "armor_piercing": piercing,
                "any_piercing": bool(estimate.get("any_piercing")),
                "multi_rof": bool(estimate.get("multi_rof")),
                "groups": [
                    {
                        "avg": g["avg"],
                        "shots": g["shots"],
                        "hit": _hit(g["avg"], g.get("pierces", piercing)),
                        "pierces": bool(g.get("pierces", piercing)),
                        "rof": float(g["rof"])
                        * rof_mult
                        * (_BERSERK_ROF if berserk else 1.0),
                    }
                    for g in groups
                ]
                if estimate.get("multi_rof")
                else [],
                "att": att,
                "dex": dex,
                "att_mult": att_m,
                "enchant_dmg_mult": dmg_mult,
                "buff_mult": dmg_buff,
                "berserk": berserk,
                "seconds": seconds,
                "total": total,
            }
        )
    return total


def scale_shark_weapon(
    shark_weapon: float,
    old_reconstruct: float,
    new_reconstruct: float,
) -> Optional[float]:
    if old_reconstruct <= 0 or shark_weapon is None:
        return None
    return shark_weapon * (new_reconstruct / old_reconstruct)


_STAT_WORD: dict[str, str] = {
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
_ABILITY_FORMULA = re.compile(
    r"(?P<lo>\d+(?:\.\d+)?)"
    rf"(?:\s*{_DASH}\s*(?P<hi>\d+(?:\.\d+)?))?"
    r"\s*\(\s*\+?\s*(?P<per>\d+(?:\.\d+)?)\s*"
    r"(?:for every|per)\s+"
    # "+1 per 8 WIS over 75" is +1 per *each 8* WIS, not +1 per point.
    r"(?:(?P<div>\d+(?:\.\d+)?)\s+)?"
    r"(?P<stat>hp|mp|att|atk|dex|def|spd|vit|wis|life|mana|"
    r"attack|defense|defence|speed|dexterity|vitality|wisdom|health)"
    r"\s+(?:over|above)\s+(?P<thr>\d+)\s*\)",
    re.I,
)
_DAMAGE_KEY = re.compile(r"\bdamage\b", re.I)
# "Total Damage" is shots x damage, so using it would double-count Shots.
_TOTAL_DAMAGE_KEY = re.compile(r"total\s+damage", re.I)
_MP_COST = re.compile(r"(\d+(?:\.\d+)?)\s*mp\b", re.I)
_ENCHANT_RANK = re.compile(r"\b(IV|III|II|I)\b", re.I)
_PROC_TRIGGER = re.compile(
    r"on\s+(abilit(?:y|ies)(?:\s+use)?|hit|shoot|use)",
    re.I,
)
_PROC_DELTA = re.compile(
    r"([+-]\d+)\s*(hp|mp|att|atk|dex|def|spd|vit|wis|"
    r"attack|defense|defence|speed|dexterity|vitality|wisdom|life|mana)\b",
    re.I,
)
_STAT_BOOST = re.compile(
    r"\b(att(?:ack)?|dex(?:terity)?|def(?:en[cs]e)?|spd|speed)\s+"
    r"boost\s*[:\(]?\s*\+?\s*(\d+)",
    re.I,
)
_STATUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("berserk", re.compile(r"\bberserk\b", re.I)),
    ("damaging", re.compile(r"\bdamaging\b", re.I)),
    # "cursed robe" / "cursed by the gods" is flavor. The status is the noun
    # Curse, and only an inflict-on-enemy line counts (see _ENEMY_CONTEXT).
    ("curse", re.compile(r"\bcurse\b", re.I)),
    ("expose", re.compile(r"\bexpos(?:e|ed)\b", re.I)),
    ("vulnerable", re.compile(r"\bvulnerable\b|receive 115%\s*damage", re.I)),
    ("healing", re.compile(r"\bheal(?:s|ing|ed)?\b", re.I)),
    ("slow", re.compile(r"\bslow(?:ed)?\b", re.I)),
    ("armor_broken", re.compile(r"\barmor\s*break", re.I)),
)
# Wiki status effects. Dummy Exposed stays x1.20 to match RealmShark.
STATUS_EFFECTS: dict[str, dict] = {
    "berserk": {
        "side": "player",
        "mult": _BERSERK_ROF,
        "applies": "weapon APS",
        "note": "Berserk +25% attack speed, not DEX.",
    },
    "damaging": {
        "side": "player",
        "mult": _DAMAGING,
        "applies": "weapon damage",
        "note": "Damaging +25% weapon damage, not ATT.",
    },
    "curse": {
        "side": "enemy",
        "mult": _CURSE,
        "applies": "weapon and ability after DEF",
        "note": "Curse +25% damage taken after DEF.",
    },
    "expose": {
        "side": "enemy",
        "mult": _EXPOSE,
        "applies": "dummy",
        "note": "Exposed is -20 DEF on a real enemy. Dummy uses x1.20.",
    },
    "vulnerable": {
        "side": "enemy",
        "mult": _VULNERABLE,
        "applies": "weapon and ability",
        "note": "Vulnerable 115% damage taken.",
    },
    "healing": {
        "side": "player",
        "mult": None,
        "applies": None,
        "note": "Healing does not change dummy DPS.",
    },
    "slow": {
        "side": "enemy",
        "mult": None,
        "applies": None,
        "note": "Slow does not change dummy DPS.",
    },
    "armor_broken": {
        "side": "enemy",
        "mult": None,
        "applies": "DEF 0",
        "note": "Armor Broken sets DEF to 0 before Exposed.",
    },
}
_CHANCE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*chance", re.I)
_STAT_MOD_NAME = re.compile(r"stat\s*mod\s*multiplier", re.I)
_MP_COST_NAME = re.compile(r"mp\s*cost\s*reduction", re.I)
_FLAT_REGEN_NAME = re.compile(r"flat\s+mana\s+regen", re.I)
_PCT_REGEN_NAME = re.compile(r"percentage\s+mana\s+regen", re.I)
_STAT_MOD_PCT = {1: 0.06, 2: 0.09, 3: 0.12, 4: 0.15}
_MP_COST_PCT = {1: 0.04, 2: 0.06, 3: 0.08, 4: 0.10}
_FLAT_REGEN = {1: 2.0, 2: 3.0, 3: 4.0, 4: 5.0}
_PCT_REGEN = {1: 0.0075, 2: 0.01, 3: 0.0125, 4: 0.015}


def _canon_formula_stat(raw: str) -> Optional[str]:
    return _STAT_WORD.get((raw or "").strip().lower())


def _enchant_rank(name: str, value: str = "") -> Optional[int]:
    match = _ENCHANT_RANK.search(name or "")
    if match:
        return {"i": 1, "ii": 2, "iii": 3, "iv": 4}[match.group(1).lower()]
    pct = re.search(r"\+(\d+(?:\.\d+)?)\s*%", value or "")
    if not pct:
        return None
    n = float(pct.group(1))
    for rank, share in ((4, 15.0), (3, 12.0), (2, 9.0), (1, 6.0)):
        if abs(n - share) < 0.6 or abs(n - share * 100) < 0.6:
            return rank
    if n <= 0.2:
        for rank, share in _STAT_MOD_PCT.items():
            if abs(n - share) < 0.005:
                return rank
    return None


def _damage_formula_match(stats: dict) -> Optional[re.Match]:
    """The ability's own Damage row, never a stat-boost line that looks like one.

    An Effect(s) blob carries boosts with the identical shape - The Triangle's
    "ATT Boost: +5 (+1 per 8 WIS over 75)" - and RealmEye orders Effect(s)
    before Damage, so searching the whole stats blob reported that item as a
    5-damage Wisdom ability instead of 300-450 scaling with Attack.
    """
    for key, val in stats.items():
        if not _DAMAGE_KEY.search(str(key)) or _TOTAL_DAMAGE_KEY.search(str(key)):
            continue
        match = _ABILITY_FORMULA.search(_digits(str(val)))
        if match:
            return match
    # Some abilities state their damage inside Effect(s) with no Damage row.
    # Only trust such a line when the line itself says "damage".
    for key, val in stats.items():
        if re.search(r"on equip", str(key), re.I) or _TOTAL_DAMAGE_KEY.search(str(key)):
            continue
        for line in str(val).splitlines():
            if not _DAMAGE_KEY.search(line):
                continue
            match = _ABILITY_FORMULA.search(line)
            if match:
                return match
    return None


def _ability_mp_cost(stats: dict) -> Optional[float]:
    for key, val in stats.items():
        if re.search(r"mp\s*cost", str(key), re.I):
            num = _NUM.search(str(val))
            if num:
                return float(num.group(1))
    blob = " ".join(
        f"{k} {v}"
        for k, v in stats.items()
        if not re.search(r"on equip", str(k), re.I)
    )
    cost = _MP_COST.search(blob)
    return float(cost.group(1)) if cost else None


def _flat_damage_row(stats: dict) -> Optional[tuple[float, float, str]]:
    """An ability Damage row that states a range and no stat scaling.

    Not every ability scales. Noble Mandolin (Rehearsal) is a flat
    "Damage: 320-400 (average: 360)", and requiring the "(+N per STAT over T)"
    clause returned None for it, which dropped the ability half entirely and
    labelled the set weapon-only DPS. 58 of 1444 cached items are flat like
    this (audit: api/scripts/audit_item_parsing.py).
    """
    for key, val in stats.items():
        if not _DAMAGE_KEY.search(str(key)) or _TOTAL_DAMAGE_KEY.search(str(key)):
            continue
        rng = parse_damage_range(str(val))
        # "Damage: 0" is a real infobox row on several traps; the actual hit
        # lives on a named row (Sticky Bomb Damage). A zero pair is not a
        # formula, so keep looking rather than returning a 0-damage ability.
        if rng and not (rng[0] == 0 and rng[1] == 0):
            return rng[0], rng[1], str(val)
    return None


def parse_ability_formula(stats: dict) -> Optional[dict]:
    """Wiki ability Damage row: '565 (+2 for every ATT above 55)'."""
    if not stats:
        return None
    match = _damage_formula_match(stats)
    if not match:
        flat = _flat_damage_row(stats)
        if not flat:
            return None
        lo, hi, evidence = flat
        # per=0 makes the scaling stat irrelevant to the arithmetic, but the key
        # has to exist because callers index it to read the sheet.
        return {
            "min": lo,
            "max": hi,
            "avg": (lo + hi) / 2.0,
            "per": 0.0,
            "stat": "Attack",
            "threshold": 0.0,
            "scales": False,
            "shots": parse_shots(
                str(stats.get("Shots") or stats.get("shots") or "1")
            ),
            "mp_cost": _ability_mp_cost(stats),
            "evidence": evidence,
        }
    lo = float(match.group("lo"))
    hi = float(match.group("hi") or lo)
    stat = _canon_formula_stat(match.group("stat"))
    if not stat:
        return None
    per_step = float(match.group("div") or 1) or 1.0
    mp = _ability_mp_cost(stats)
    return {
        "min": lo,
        "max": hi,
        "avg": (lo + hi) / 2.0,
        "per": float(match.group("per")) / per_step,
        "stat": stat,
        "threshold": float(match.group("thr")),
        "scales": True,
        "shots": parse_shots(str(stats.get("Shots") or stats.get("shots") or "1")),
        "mp_cost": mp,
        "evidence": match.group(0),
    }


def ability_enchants(row: Loadout) -> list[ItemEnchant]:
    for piece in row.equipment:
        if piece.slot.lower() == "ability":
            return list(piece.enchants or [])
    return []


def weapon_enchants(row: Loadout) -> list[ItemEnchant]:
    for piece in row.equipment:
        if piece.slot.lower() == "weapon":
            return list(piece.enchants or [])
    return []


def stat_mod_multiplier(debug: Optional[dict], enchants: Optional[list[ItemEnchant]] = None) -> float:
    """RealmShark debug wins when it is not 1. Else parse Stat Mod I-IV."""
    debug = debug or {}
    for key in ("effectiveAbilityStatModMult", "abilityStatModMult"):
        try:
            value = float(debug.get(key) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value and abs(value - 1.0) > 0.001:
            return value
    for enc in enchants or []:
        if not _STAT_MOD_NAME.search(enc.name or ""):
            continue
        rank = _enchant_rank(enc.name, enc.value)
        if rank:
            return 1.0 + _STAT_MOD_PCT[rank]
        pct = re.search(r"\+(\d+(?:\.\d+)?)\s*%", enc.value or "")
        if pct:
            n = float(pct.group(1))
            return 1.0 + (n / 100.0 if n > 1 else n)
    return 1.0


def parse_mana_enchants(enchants: list[ItemEnchant]) -> dict[str, float]:
    out = {"flat": 0.0, "percent": 0.0, "mp_cost_reduction": 0.0, "stat_mod": 1.0}
    for enc in enchants:
        rank = _enchant_rank(enc.name, enc.value)
        if _STAT_MOD_NAME.search(enc.name or "") and rank:
            out["stat_mod"] = 1.0 + _STAT_MOD_PCT[rank]
        elif _MP_COST_NAME.search(enc.name or "") and rank:
            out["mp_cost_reduction"] = _MP_COST_PCT[rank]
        elif _FLAT_REGEN_NAME.search(enc.name or "") and rank:
            out["flat"] = _FLAT_REGEN[rank]
        elif _PCT_REGEN_NAME.search(enc.name or "") and rank:
            out["percent"] = _PCT_REGEN[rank]
    return out


def ability_uses(debug: Optional[dict]) -> float:
    debug = debug or {}
    for key in ("effectiveAbilityCount", "abilityCount"):
        try:
            value = float(debug.get(key) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return float(_ABILITY_USES)


def reconstruct_ability_damage(
    formula: dict,
    *,
    stats: dict[str, float],
    debug: Optional[dict] = None,
    enchants: Optional[list[ItemEnchant]] = None,
    seconds: float = _SECONDS,
    steps: Optional[dict] = None,
) -> Optional[float]:
    """One 5s window of ability hits.

    per-use = (avg + per × max(0, stat × StatMod - threshold)) × shots
    then × ability uses × Damaging × Curse × Exposed × Vulnerable.

    Berserk is the only weapon-only multiplier (attack speed). Minion extra
    volleys sit in the RealmShark residual. Scale the stored abilityDamage
    by new/old reconstruct after a swap.
    """
    if not formula:
        return None
    stat_name = formula["stat"]
    raw_stat = float(stats.get(stat_name) or 0)
    mod = stat_mod_multiplier(debug, enchants)
    scaled = raw_stat * mod
    per_shot = float(formula["avg"]) + float(formula["per"]) * max(
        0.0, scaled - float(formula["threshold"])
    )
    per_use = per_shot * float(formula["shots"] or 1.0)
    _dmg_mult, _rof_mult, dmg_buff, _berserk, _pre, _post = _debug_mults(
        debug or {}, enchants=enchants, kind="ability"
    )
    uses = ability_uses(debug)
    total = per_use * uses * dmg_buff
    if steps is not None:
        steps.update(
            {
                "stat_name": stat_name,
                "raw_stat": raw_stat,
                "stat_mod": mod,
                "scaled_stat": scaled,
                "base_avg": float(formula["avg"]),
                "per": float(formula["per"]),
                "threshold": float(formula["threshold"]),
                "per_shot": per_shot,
                "shots": float(formula["shots"] or 1.0),
                "per_use": per_use,
                "uses": uses,
                "buff_mult": dmg_buff,
                "seconds": seconds,
                "total": total,
            }
        )
    return total


# "Cannot be Cursed" / "Immune to Curse" is a resistance the wearer has, not a
# debuff they put on an enemy. Counting it would hand out free damage.
_NEGATED_STATUS = re.compile(
    r"\b(?:cannot|can't|immune|immunity|resist(?:s|ant)?|prevents?|removes?|cures?)\b",
    re.I,
)
# Flavor ("This cursed robe", "cursed by the gods") is not a dummy debuff.
# The status noun is "Curse"; "cursed" as an adjective must not match. Same
# for Exposed / Vulnerable: only an inflict-on-enemy line counts, otherwise a
# Huntress trap's Curse leaks into the next class in the same conversation
# because the model copies "except Curse from your own procs" from the
# previous dummy paragraph.
_ENEMY_CONTEXT = re.compile(
    r"\b(?:inflict(?:s|ed)?|applies?|on enemies|to enem(?:y|ies)|"
    r"to (?:the )?target|on (?:the )?target)\b",
    re.I,
)
_DEBUFF_WORD = {
    "curse": re.compile(r"\bcurse\b", re.I),
    "expose": re.compile(r"\bexposed?\b", re.I),
    "vulnerable": re.compile(r"\bvulnerable\b", re.I),
    "damaging": re.compile(r"\bdamaging\b", re.I),
}
_ENEMY_DEBUFFS = frozenset({"curse", "expose", "vulnerable"})


def set_inflicted_debuff_sources(
    items: list[ItemProfile], *, enchant_texts: Optional[list[tuple[str, str]]] = None
) -> dict[str, list[str]]:
    """Which worn pieces inflict each dummy debuff, from THIS set's wiki only.

    A player alone on the practice dummy has no party, so the only debuffs
    running are the ones their own gear inflicts. Trap of the Vile Spirit
    inflicts Curse and nothing else. Vesture of Duality's flavor ("This cursed
    robe") does not. Hardcoding Curse, or matching the adjective "cursed", is
    what let a Huntress trap's Curse leak into a Bard reply in the same chat.
    """
    sources: dict[str, list[str]] = {name: [] for name in _DEBUFF_WORD}

    def _consider(source: str, line: str) -> None:
        if not grant_is_sustainable(line) or _NEGATED_STATUS.search(line):
            return
        for name, pattern in _DEBUFF_WORD.items():
            if not pattern.search(line):
                continue
            if name in _ENEMY_DEBUFFS and not _ENEMY_CONTEXT.search(line):
                continue
            if source not in sources[name]:
                sources[name].append(source)

    for item in items or []:
        for key, value in (item.stats or {}).items():
            if _SUMMON_ROW.search(str(key or "")):
                continue
            for line in str(value or "").splitlines():
                _consider(item.name, line)
    for name, text in enchant_texts or []:
        for line in (text or "").splitlines():
            _consider(f"{name} enchant", line)
    return sources


def set_inflicted_debuffs(
    items: list[ItemProfile], *, enchant_texts: Optional[list[tuple[str, str]]] = None
) -> dict[str, bool]:
    return {
        name: bool(names)
        for name, names in set_inflicted_debuff_sources(
            items, enchant_texts=enchant_texts
        ).items()
    }


def format_practice_dummy(
    estimate: Optional[dict],
    ability_formula: Optional[dict],
    *,
    att: float,
    dex: float,
    stats: dict,
    worn_items: Optional[list[ItemProfile]] = None,
    enchant_texts: Optional[list[tuple[str, str]]] = None,
    weapon_enchants: Optional[list[ItemEnchant]] = None,
    ability_enchants: Optional[list[ItemEnchant]] = None,
    ceiling: float,
) -> str:
    """The same set priced against the guild hall dummy.

    The headline number is a ceiling: 0 DEF and party Damaging, Curse, Exposed
    and Vulnerable all up. A player testing alone on the practice dummy has
    none of that and 15 DEF to chew through, so the ceiling reads as absurd
    next to what they measure. Giving both makes the number checkable: a
    Huntress reconstructing to 124,183.6 at the ceiling comes to 71,990.5 here,
    against roughly 80,000 actually measured.
    """
    inflicted_sources = set_inflicted_debuff_sources(
        worn_items or [], enchant_texts=enchant_texts
    )
    inflicted = {name: bool(names) for name, names in inflicted_sources.items()}
    solo = {
        "buffs": {
            "damaging": inflicted.get("damaging", False),
            "curse": inflicted.get("curse", False),
            "expose": inflicted.get("expose", False),
            "vulnerable": inflicted.get("vulnerable", False),
            # Berserk still has to be sourced from the set, same rule as the
            # ceiling. A solo player gets no party Berserk.
            "berserk": False,
        }
    }
    named = [
        f"{flag.capitalize()} from "
        + ", ".join(
            f"[item:{n}]" if " enchant" not in n else n for n in names
        )
        for flag, names in inflicted_sources.items()
        if names
    ]
    if named:
        self_buffs = "; ".join(named)
        isolation = (
            "Those are the only dummy debuffs for THIS character and THIS worn "
            "set. Do not add Curse, Exposed, Vulnerable, or Damaging from an "
            "earlier turn about a different class or character."
        )
    else:
        self_buffs = "none of Curse, Exposed, Vulnerable, or Damaging"
        isolation = (
            "THIS set's wiki pages do not inflict any of those. A previous "
            "turn's dummy (for example a Huntress trap that inflicts Curse) "
            "does not apply here. Never write 'except Curse from your own "
            "procs' unless an item named above inflicts Curse."
        )
    weapon = (
        reconstruct_weapon_damage(
            estimate,
            att=att,
            dex=dex,
            debug=solo,
            enchants=weapon_enchants,
            enemy_def=_GUILD_DUMMY_DEF,
        )
        if estimate
        else 0.0
    )
    ability = (
        reconstruct_ability_damage(
            ability_formula, stats=stats, debug=solo, enchants=ability_enchants
        )
        if ability_formula
        else 0.0
    )
    total = (weapon or 0.0) + (ability or 0.0)
    return (
        f"SAME SET ON THE GUILD HALL PRACTICE DUMMY ({_GUILD_DUMMY_DEF:.0f} DEF, "
        "solo, no party buffs and no Berserk; the only debuffs counted are the "
        f"ones this set inflicts by itself: {self_buffs}). {isolation} Weapon "
        f"**{_fmt_n(weapon)}** + ability **{_fmt_n(ability)}** = "
        f"**{_fmt_n(total)}** damage over {_SECONDS:.0f}s "
        f"(**{_fmt_n(total / _SECONDS)}** per second). This is the figure a "
        "player testing alone can actually reproduce; the "
        f"{_fmt_n(ceiling)} above is a fully buffed 0 DEF ceiling. If the user "
        "reports what they measured on a dummy, compare it against THIS "
        "number, not the ceiling, and never tell them their own measurement is "
        "wrong because it is lower than the ceiling."
    )


def _def_note(w: dict) -> str:
    """Say which target the number is against, so it can be checked or not."""
    shield = float(w.get("enemy_def") or 0.0)
    if w.get("armor_piercing"):
        return "every shot ignores enemy DEF (armor piercing)"
    if shield <= 0:
        return "against a 0 DEF target"
    if w.get("any_piercing"):
        return (
            f"minus {shield:.0f} enemy DEF on the shots that pay it (the "
            "armor-piercing ones ignore it), floor 10% of the hit"
        )
    return f"minus {shield:.0f} enemy DEF per projectile (floor 10% of the hit)"


def format_dps_derivation(
    *,
    weapon_item: Optional[ItemProfile],
    ability_item: Optional[ItemProfile],
    weapon_steps: dict,
    ability_steps: dict,
    total: float,
    dps: float,
    label: str,
) -> str:
    """Every factor that produced the reconstruct, as arithmetic.

    Without this the brief carried only the finished number, so "what do the
    numbers look like?" had nothing to show and the model treated its own
    correct answer as unsupported. Each line is a multiplication the model can
    read straight out rather than recompute.
    """
    lines = [
        "HOW THIS RECONSTRUCT WAS BUILT - if the user asks for a breakdown, "
        "the math, per-shot numbers, or where a figure came from, walk through "
        "these steps and cite them as the specialist's own arithmetic. Every "
        "factor here is given; none of it is invented, and none of it is the "
        "model's guess.",
        # The halves are 5s totals, not rates. Presenting "weapon 59,315.7" next
        # to the word DPS made the model label a 5-second damage total as
        # "59,315.7 DPS", which is 5x the real rate.
        "UNITS: the weapon and ability halves below are total damage dealt "
        "across the whole 5-second window, NOT damage per second. Only the final "
        "figure, after dividing by 5, is a DPS number. Never label a half as DPS.",
        "APS formula: (1.5 + 6.5 × DEX/75) × item Rate of Fire × fire-rate "
        "weapon-shot enchants × Berserk if this set grants it. Among the eight "
        "8/8 stats, APS reads Dexterity only. Attack is the separate "
        "(0.5 + ATT/50) line. The other six stats enter only when the ability "
        "wiki formula or a working-stat proc uses them, through the sheet, not "
        "as a fire-rate multiplier. Never use DEX × Rate of Fire / 8.",
        "Enchant channels live in HOW EACH WORN PIECE. Copy those. A sheet-stat "
        "tradeoff is not a fire-rate enchant. Projectile speed is not damage.",
    ]
    if weapon_steps:
        w = weapon_steps
        named = f" [item:{weapon_item.name}]" if weapon_item else ""
        # Name where the rate of fire came from, or the model invents a source.
        if w.get("berserk"):
            rof_note = (
                f"item rate of fire {w.get('base_rof', 1.0):.2f} x 1.25 Berserk, "
                "granted by this set"
            )
        else:
            rof_note = (
                f"item rate of fire {w.get('base_rof', 1.0):.2f}, no Berserk "
                "(nothing in this set grants it)"
            )
        if w.get("multi_rof") and w.get("groups"):
            # This weapon fires each projectile group at its own rate, so there
            # is no single "damage per volley x attacks/sec" to quote. Printing
            # the blended pair anyway produced a breakdown whose arithmetic did
            # not reach the stated total.
            zerk = " x 1.25 Berserk" if w.get("berserk") else ""
            per_group = "; ".join(
                f"{g['avg']:.1f} base -> {g['hit']:.1f} per hit x "
                f"{g['shots']:.0f} shot(s) at rate of fire {g['rof']:.2f} "
                f"({attacks_per_second(dex=w['dex'], rof=g['rof']):.2f}/sec) = "
                f"{g['hit'] * g['shots'] * attacks_per_second(dex=w['dex'], rof=g['rof']):.1f}/sec"
                for g in w["groups"]
            )
            lines.append(
                f"- Weapon half{named}: this weapon fires "
                f"{len(w['groups'])} projectile groups at different rates of "
                f"fire, so each is counted separately. Each hit is "
                f"base x {w['att_mult']:.3f} attack multiplier (ATT "
                f"{w['att']:.0f}) x {w['enchant_dmg_mult']:.3f} weapon enchants "
                f"x {w['buff_mult']:.3f} party buffs, {_def_note(w)} "
                f"(DEX {w['dex']:.0f}{zerk}): {per_group}. Sum = "
                f"{w['per_second']:.1f} damage per second; x "
                f"{w['seconds']:.0f}s window = {_fmt_n(w['total'])} total "
                f"damage, NOT per second"
            )
        else:
            lines.append(
                f"- Weapon half{named}: avg shot {w['avg']:.1f} x "
                f"{w['shots']:.0f} shot(s) = {w['burst']:.1f} damage per volley; "
                f"x {w['aps']:.2f} attacks/sec from (1.5 + 6.5 × DEX "
                f"{w['dex']:.0f}/75) × {rof_note}"
                + (
                    f" × fire-rate enchant {float(w.get('enchant_rof_mult') or 1):.3f}"
                    if abs(float(w.get("enchant_rof_mult") or 1) - 1) > 0.001
                    else ""
                )
                + "; "
                f"x {w['att_mult']:.3f} attack multiplier (ATT {w['att']:.0f}); "
                f"x {w['enchant_dmg_mult']:.3f} weapon-shot enchants; "
                f"x {w['buff_mult']:.3f} party buffs (Damaging, Curse, Exposed, "
                f"Vulnerable); {_def_note(w)}; over the {w['seconds']:.0f}s "
                f"window = {_fmt_n(w['total'])} total damage, NOT per second"
            )
    if ability_steps:
        a = ability_steps
        named = f" [item:{ability_item.name}]" if ability_item else ""
        over = (
            f" over the {a['threshold']:.0f} threshold"
            if a.get("threshold")
            else ""
        )
        lines.append(
            f"- Ability half{named}: {a['stat_name']} {a['raw_stat']:.0f} x "
            f"{a['stat_mod']:.3f} stat mod = {a['scaled_stat']:.1f} effective; "
            f"per shot {a['base_avg']:.1f} + {a['per']:.1f} per point{over} "
            f"= {a['per_shot']:.1f}; x {a['shots']:.0f} shot(s) = "
            f"{a['per_use']:.1f} per use; x {a['uses']:.0f} uses in the "
            f"window; x {a['buff_mult']:.3f} party buffs "
            f"(Damaging, Curse, Exposed, Vulnerable; no Berserk, it buys attack "
            f"speed and does not touch ability damage) = "
            f"{_fmt_n(a['total'])} total damage, NOT per second"
        )
    weapon_n = weapon_steps.get("total") or 0.0
    ability_n = ability_steps.get("total") or 0.0
    seconds = weapon_steps.get("seconds") or ability_steps.get("seconds") or _SECONDS
    lines.append(
        f"- Total: {_fmt_n(weapon_n)} weapon damage + {_fmt_n(ability_n)} ability "
        f"damage = {_fmt_n(total)} damage over {seconds:.0f}s. Divide by "
        f"{seconds:.0f} for the rate: {_fmt_n(dps)} {label}. This last figure is "
        "the only one that is per second."
    )
    return "\n".join(lines)


def ideal_ability_enchants(formula: Optional[dict]) -> str:
    if formula and float(formula.get("per") or 0) > 0:
        return (
            "Ideal ability enchants when this scales: Stat Mod Multiplier "
            "(I-IV is +6/9/12/15% of the scaling stat, so 100 WIS is treated "
            "as 115 at IV) plus Flat or Percentage Mana Regeneration. "
            "Stat Mod Multiplier and MP Cost Reduction cannot roll together."
        )
    return (
        "This ability has no wiki stat-mod formula. Skip Stat Mod Multiplier. "
        "Flat or Percentage Mana Regeneration is still the default ability roll."
    )


def parse_gear_procs(item: ItemProfile) -> list[dict]:
    """On Ability / On Hit / On Shoot stat boosts, plus Effect(s) ATT Boost."""
    found: list[dict] = []
    already: set[str] = set()
    for key, val in (item.stats or {}).items():
        text = f"{key}: {val}"
        trigger_m = _PROC_TRIGGER.search(text)
        if not trigger_m:
            continue
        word = trigger_m.group(1).lower()
        if word.startswith("abilit") or word == "use":
            trigger = "ability"
        elif "hit" in word:
            trigger = "hit"
        else:
            trigger = "shoot"
        bonuses: dict[str, int] = {}
        for delta in _PROC_DELTA.finditer(text):
            stat = _canon_formula_stat(delta.group(2))
            if not stat:
                continue
            bonuses[stat] = bonuses.get(stat, 0) + int(delta.group(1))
        if bonuses:
            found.append({"trigger": trigger, "bonuses": bonuses, "text": text.strip()})
            if trigger == "ability":
                already.update(bonuses)
    boosts: dict[str, int] = {}
    for key, val in (item.stats or {}).items():
        for match in _STAT_BOOST.finditer(f"{key}: {val}"):
            stat = _canon_formula_stat(match.group(1))
            if not stat or stat in already:
                continue
            boosts[stat] = boosts.get(stat, 0) + int(match.group(2))
    if boosts:
        found.append(
            {
                "trigger": "ability",
                "bonuses": boosts,
                "text": "Effect(s) stat boost",
            }
        )
    return found


def parse_status_grants(item: ItemProfile) -> dict[str, str]:
    """Which dummy-relevant status effects this item inflicts or grants."""
    found: dict[str, str] = {}
    for key, value in (item.stats or {}).items():
        for line in str(value or "").splitlines():
            if _NEGATED_STATUS.search(line):
                continue
            for flag, pat in _STATUS_PATTERNS:
                if not pat.search(line):
                    continue
                if flag in _ENEMY_DEBUFFS and not _ENEMY_CONTEXT.search(line):
                    continue
                if flag in found:
                    continue
                found[flag] = re.sub(r"\s+", " ", line).strip()
    return found


def proc_is_dummy_uptime(proc: dict) -> bool:
    """8 ability uses / constant shooting in the 5s dummy. Chance and On Hit are not."""
    return grant_is_dummy_uptime(proc.get("text") or "") and proc.get("trigger") in {
        "ability",
        "shoot",
    }


def grant_is_dummy_uptime(text: str) -> bool:
    """Chance rolls and On Hit are not guaranteed in the 5s dummy window."""
    chance = _CHANCE.search(text or "")
    if chance and float(chance.group(1)) < 99:
        return False
    if re.search(r"\bon\s+hit\b", text or "", re.I):
        return False
    return True


def inspect_worn_set(
    items: list[ItemProfile],
    *,
    enchant_texts: Optional[list[tuple[str, str]]] = None,
) -> dict:
    """Root: walk every equipped piece's wiki (and on-character enchants).

    Returns status grants, stat procs, and combat shoot deltas. No item
    names are special-cased. On Equip stays out of shoot deltas because
    RealmShark sheet stats already include it.
    """
    grants: dict[str, list[dict]] = {}
    procs: list[dict] = []
    shoot_deltas: dict[str, int] = {}
    ability_deltas: dict[str, int] = {}
    on_equip: list[dict] = []

    def _add_grants(source: str, blob_item: ItemProfile) -> None:
        for flag, evidence in parse_status_grants(blob_item).items():
            rows = grants.setdefault(flag, [])
            if any(row["source"] == source for row in rows):
                continue
            rows.append(
                {
                    "source": source,
                    "evidence": evidence,
                    "dummy_uptime": grant_is_dummy_uptime(evidence),
                }
            )

    def _add_proc(item_name: str, proc: dict) -> None:
        row = {
            **proc,
            "item": item_name,
            "dummy_uptime": proc_is_dummy_uptime(proc),
        }
        procs.append(row)
        if not row["dummy_uptime"]:
            return
        target = ability_deltas if proc["trigger"] == "ability" else shoot_deltas
        if proc["trigger"] not in {"ability", "shoot"}:
            return
        for stat, value in proc["bonuses"].items():
            target[stat] = target.get(stat, 0) + value

    for item in items:
        if not item:
            continue
        _add_grants(item.name, item)
        bonuses = on_equip_bonuses(item)
        if bonuses:
            on_equip.append({"item": item.name, "bonuses": bonuses})
        for proc in parse_gear_procs(item):
            _add_proc(item.name, proc)
    for item_name, text in enchant_texts or []:
        blob = ItemProfile(name=item_name, stats={"Enchant": text})
        _add_grants(f"{item_name} enchant", blob)
        for proc in parse_gear_procs(blob):
            _add_proc(item_name, proc)
    return {
        "grants": grants,
        "procs": procs,
        "shoot_deltas": shoot_deltas,
        "ability_deltas": ability_deltas,
        "on_equip": on_equip,
    }


def collect_status_grants(items: list[ItemProfile]) -> dict[str, list[str]]:
    catalog = inspect_worn_set(items)
    return {
        flag: [row["source"] for row in rows]
        for flag, rows in catalog["grants"].items()
    }


def format_set_effects(
    items: list[ItemProfile],
    *,
    enchant_texts: Optional[list[tuple[str, str]]] = None,
) -> str:
    catalog = inspect_worn_set(items, enchant_texts=enchant_texts)
    lines = [
        "SET EFFECTS from the worn pieces (wiki infobox + on-character enchants). "
        "RealmShark potential DPS already assumes party Damaging, Curse, Exposed, "
        "and Vulnerable. Do not multiply those again on a board number. "
        "A swap that removes this set's only source of a self-buff should drop it.",
        # Berserk was previously listed as a party assumption. It is not: it has
        # to come from the character's own gear or enchants, and saying otherwise
        # is what led the model to credit Berserk to Vesture of Duality.
        "Berserk is NOT a party assumption. It applies only when this set or its "
        "enchants can produce it, and it is listed under the grants below when it "
        "can. If Berserk is not listed there, this character does not have it. "
        "Never attribute Berserk (or any buff) to an item whose wiki text below "
        "does not say it.",
        "Multipliers: Damaging x1.25 on BOTH weapon and ability damage, Curse "
        "x1.25 after DEF on both, Vulnerable x1.15 on both, Exposed dummy x1.20 "
        "on both (wiki -20 DEF). Berserk x1.25 is attack speed, so it lifts the "
        "weapon half only and never the ability half, and only when granted.",
    ]
    grants = catalog["grants"]
    order = (
        "berserk",
        "damaging",
        "curse",
        "expose",
        "vulnerable",
        "armor_broken",
        "healing",
        "slow",
    )
    if not grants and not catalog["procs"] and not catalog["on_equip"]:
        lines.append("- No status grants, On Equip bonuses, or stat procs on these wiki pages.")
        return "\n".join(lines)
    for row in catalog["on_equip"]:
        bits = ", ".join(
            f"{stat} {value:+d}" for stat, value in row["bonuses"].items()
        )
        lines.append(
            f"- [item:{row['item']}] On Equip: {bits} "
            "(already in RealmShark sheet stats)"
        )
    for flag in order:
        rows = grants.get(flag)
        if not rows:
            continue
        meta = STATUS_EFFECTS[flag]
        items_s = ", ".join(
            (
                (
                    f"[item:{row['source']}]"
                    if " enchant" not in row["source"]
                    else row["source"]
                )
                + ("" if row["dummy_uptime"] else " (not 100% dummy)")
            )
            for row in rows
        )
        extra = ""
        if meta["mult"] is None:
            extra = " No dummy DPS."
        elif flag == "expose":
            extra = f" Dummy x{meta['mult']:.2f}."
        else:
            extra = f" x{meta['mult']:.2f} on {meta['applies']}."
        lines.append(f"- {flag}: {items_s}.{extra} {meta['note']}")
    for proc in catalog["procs"]:
        if not proc.get("bonuses"):
            continue
        bits = ", ".join(f"{stat} {value:+d}" for stat, value in proc["bonuses"].items())
        uptime = (
            "100% dummy uptime"
            if proc["dummy_uptime"]
            else "not 100% dummy (chance or On Hit)"
        )
        lines.append(
            f"- [item:{proc['item']}] On {proc['trigger']}: {bits} ({uptime})"
        )
    missing_enemy = [
        flag
        for flag in ("curse", "expose", "vulnerable", "damaging")
        if flag not in grants
    ]
    if missing_enemy:
        lines.append(
            "- This set does not inflict or grant "
            + ", ".join(flag.capitalize() for flag in missing_enemy)
            + ". Those names in an earlier turn about a different class or "
            "character do not apply here."
        )
    return "\n".join(lines)


def enchant_texts_from_loadout(row: Loadout) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for piece in row.equipment:
        for enc in piece.enchants or []:
            out.append((piece.item_name, f"{enc.name}: {enc.value}"))
    return out


def proc_uptime_bonuses(item: ItemProfile, triggers: tuple[str, ...] = ("ability",)) -> dict[str, int]:
    """On Ability (and optional On Shoot) procs for the 5s dummy window."""
    total: dict[str, int] = {}
    for proc in parse_gear_procs(item):
        if proc["trigger"] not in triggers:
            continue
        for stat, value in proc["bonuses"].items():
            total[stat] = total.get(stat, 0) + value
    return total


def combat_shoot_deltas(item: ItemProfile) -> dict[str, int]:
    """On Shoot combat modifiers that are not on the character sheet."""
    return proc_uptime_bonuses(item, triggers=("shoot",))


def combat_stat_sheet(
    sheet: dict[str, float] | None, catalog: dict
) -> dict[str, float]:
    """The in-combat stat sheet: character sheet plus dummy-uptime procs.

    A character sheet reports On Equip totals only, whether it came from
    RealmEye or from a RealmShark row's `stats`, so an `On Ability Use: ATT
    Boost (+15 ATT)` or an On Shoot modifier is absent from it even though the
    5s / 8-use dummy holds both up for the whole window.

    Both entry points have to apply the same buckets to the same stats. They
    did not: the player-set reconstruct added `ability_deltas` and
    `shoot_deltas` across every stat, while the board-row rescale added only
    `shoot_deltas` and only for Attack and Dexterity, then handed the ability
    reconstructor the untouched row stats. Identical gear therefore produced two
    different numbers depending on whether the question named a player or a
    class, and a Wisdom proc moved a player's ability half but not a board
    row's. Route every stat sheet through here.
    """
    out = {k: float(v) for k, v in (sheet or {}).items()}
    for bucket in ("ability_deltas", "shoot_deltas"):
        for stat_name, delta in (catalog.get(bucket) or {}).items():
            out[stat_name] = out.get(stat_name, 0.0) + float(delta)
    return out


def format_working_stats(
    sheet: dict[str, float] | None, catalog: dict, working: dict[str, float]
) -> str:
    """Show which item contributed each proc, so both Triangle and Vesture are named.

    Found live: the Bard reconstruct used ATT 96 (sheet 76 + Triangle +5 +
    Vesture +15) but the reply did not make both sources obvious, so a reader
    could not tell whether Vesture's On Ability boost had been counted. Listing
    the arithmetic per stat, with the item, is the only way to make that check
    without opening the wiki.
    """
    lines = [
        "WORKING COMBAT STATS for THIS character and THIS worn set. Sheet "
        "values already include On Equip. Each proc below is from this set's "
        "wiki page at 100% dummy uptime. A proc from a previous turn's "
        "character does not apply. When working Attack or Dexterity differs "
        "from the sheet, name every item that moved it.",
    ]
    for stat in PLAYER_STATS:
        sheet_v = float((sheet or {}).get(stat) or 0.0)
        work_v = float((working or {}).get(stat) or sheet_v)
        parts = [f"sheet {sheet_v:.0f}"]
        for proc in catalog.get("procs") or []:
            if not proc.get("dummy_uptime"):
                continue
            delta = (proc.get("bonuses") or {}).get(stat)
            if not delta:
                continue
            parts.append(
                f"[item:{proc['item']}] On {proc['trigger']} {int(delta):+d}"
            )
        if len(parts) == 1 and work_v == sheet_v:
            lines.append(f"- {stat}: {sheet_v:.0f}")
            continue
        lines.append(f"- {stat}: {' + '.join(parts)} = {work_v:.0f}")
    return "\n".join(lines)


def format_slot_contributions(
    slots: list[tuple[str, str, list[ItemEnchant]]],
    worn: dict[str, ItemProfile],
    catalog: dict,
    *,
    ability_stat: Optional[str] = None,
) -> str:
    """Every worn slot, including armor and ring, for a breakdown to copy."""
    by_slot = {slot: (name, enchants) for slot, name, enchants in slots}
    lines = [
        "HOW EACH WORN PIECE ENTERS THIS RECONSTRUCT. A breakdown must name "
        "weapon, ability, armor, and ring. An empty slot still gets a line. "
        "Armor and ring have no shots of their own: they enter through On "
        "Equip, dummy-uptime procs, status grants, and on-character enchants.",
    ]
    for slot in _EQUIP_SLOT_ORDER:
        item = worn.get(slot)
        name, enchants = by_slot.get(slot, ("", []))
        if not item and not name:
            lines.append(f"- {slot}: not scraped. Do not invent this slot.")
            continue
        label = item.name if item else name
        bits: list[str] = [f"[item:{label}]"]
        if slot == "weapon":
            bits.append("supplies the shot / rate-of-fire half")
        elif slot == "ability":
            bits.append("supplies the ability-use half")
        else:
            bits.append("no shot of its own")
        if item:
            bonuses = on_equip_bonuses(item)
            if bonuses:
                bits.append(
                    "On Equip "
                    + ", ".join(f"{stat} {value:+d}" for stat, value in bonuses.items())
                )
            for proc in catalog.get("procs") or []:
                if proc.get("item") != item.name:
                    continue
                delta = ", ".join(
                    f"{stat} {value:+d}"
                    for stat, value in (proc.get("bonuses") or {}).items()
                )
                uptime = "100% dummy" if proc.get("dummy_uptime") else "not 100% dummy"
                bits.append(f"On {proc.get('trigger')}: {delta} ({uptime})")
            for flag, rows in (catalog.get("grants") or {}).items():
                for row in rows:
                    source = row.get("source") or ""
                    if item.name not in source:
                        continue
                    bits.append(f"status {flag} from this piece")
        if enchants:
            bits.append(
                "enchants: "
                + "; ".join(
                    format_enchant_channel(enc, ability_stat=ability_stat)
                    for enc in enchants
                )
            )
        else:
            bits.append("no on-character enchant listed")
        lines.append(f"- {slot}: " + ". ".join(bits) + ".")
    return "\n".join(lines)


def gear_stat_contribution(item: ItemProfile) -> dict[str, int]:
    """On Equip plus dummy-uptime procs (ability use and constant shooting)."""
    out = dict(on_equip_bonuses(item))
    for proc in parse_gear_procs(item):
        if not proc_is_dummy_uptime(proc):
            continue
        for stat, value in proc["bonuses"].items():
            out[stat] = out.get(stat, 0) + value
    return out


def extract_dps_item(message: str) -> Optional[str]:
    from .item_aliases import community_canonical, extract_mentioned_items

    mentioned = extract_mentioned_items(message)
    if mentioned:
        return mentioned[0]
    text = (message or "").strip()
    match = _ON_ITEM.search(text)
    candidate = (match.group(1) if match else "").strip(" ?.!")
    if candidate:
        canonical = community_canonical(candidate)
        if canonical:
            return canonical
        if 1 <= len(candidate.split()) <= 6:
            return candidate
    for token in re.findall(r"\b[A-Za-z][A-Za-z']+\b", text):
        canonical = community_canonical(token)
        if canonical:
            return canonical
    return None


def _wiki_stat_lines(item: ItemProfile) -> list[str]:
    keys = (
        "Damage",
        "Shots",
        "Rate of Fire",
        "Fire Rate",
        "MP Cost",
        "Projectile Speed",
        "Range",
        "Impact",
        "Effect(s)",
        "Reactive Proc(s)",
        "Reactive Proc",
        "On Equip",
    )
    lines = []
    stats = item.stats or {}
    for key in keys:
        value = stats.get(key)
        if value:
            lines.append(f"- {key}: {value}")
    return lines


def format_wiki_estimate(item: ItemProfile, estimate: Optional[dict]) -> str:
    lines = [
        f"WIKI ITEM DATA - [item:{item.name}]",
        f"Source: {item.wiki_url or 'RealmEye item page'}",
    ]
    lines.extend(_wiki_stat_lines(item))
    formula = parse_ability_formula(item.stats or {})
    if formula:
        lines.extend(
            [
                "",
                "Wiki ability scaling (Stat Mod Multiplier applies to the stat, not the base):",
                f"- {formula['evidence']}",
                f"- per use: (avg {formula['avg']:.1f} + {formula['per']:.1f} × "
                f"max(0, {formula['stat']} × StatMod - {formula['threshold']:.0f})) "
                f"× {formula['shots']:.0f} shot(s)",
            ]
        )
        if formula.get("mp_cost"):
            lines.append(f"- MP Cost: {formula['mp_cost']:.0f}")
        lines.append(ideal_ability_enchants(formula))
    procs = parse_gear_procs(item)
    if procs:
        lines.append("Stat procs from this wiki page:")
        for proc in procs:
            bits = ", ".join(f"{stat} {value:+d}" for stat, value in proc["bonuses"].items())
            uptime = (
                "100% dummy"
                if proc_is_dummy_uptime(proc)
                else "not 100% dummy"
            )
            lines.append(f"- On {proc['trigger']}: {bits} ({uptime})")
    grants = parse_status_grants(item)
    if grants:
        lines.append("Status grants from this wiki page:")
        for flag, evidence in grants.items():
            meta = STATUS_EFFECTS[flag]
            extra = (
                " No dummy DPS."
                if meta["mult"] is None
                else f" x{meta['mult']:.2f}."
            )
            lines.append(f"- {flag}:{extra} {meta['note']}")
    if estimate and not formula:
        lines.extend(
            [
                "",
                "Unbuffed 8/8 wiki weapon DPS (no RealmShark buffs, 0 DEF):",
                "- Formula: avg damage × shots × (1.5 + 6.5 × DEX/75) × "
                "Rate of Fire × (0.5 + ATT/50)",
                f"- DEX {estimate['dex']:.0f}, ATT {estimate['att']:.0f}: "
                f"avg {estimate['avg']:.1f} × {estimate['shots']:.0f} shot(s) × "
                f"{estimate['aps']:.2f} APS × {estimate['att_mult']:.2f} ATT "
                f"= **{estimate['dps']:.1f}**",
                "This is an input to the RealmShark reconstruction, not the "
                "potential-DPS number. When a board row exists, copy that row.",
            ]
        )
    elif not estimate and not formula:
        lines.append(
            "No Damage row on the stored wiki profile. Do not invent a DPS number."
        )
    return "\n".join(lines)


def _fmt_n(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "?"
    return f"{value:,.{digits}f}"


def _slot_map(row: Loadout) -> dict[str, str]:
    return {s.slot.lower(): s.item_name for s in row.equipment}


def _format_enchants(enchants: list[ItemEnchant], debug: dict, slot: str) -> list[str]:
    lines = []
    weapon = debug.get("weaponEnchant") if slot == "weapon" else None
    for enc in enchants:
        extra = ""
        if (
            weapon
            and slot == "weapon"
            and weapon.get("id")
            and str(weapon.get("id")).lower().replace("_", " ")
            in enc.name.lower()
        ):
            extra = (
                f" (calculator: damage ×{float(weapon.get('weaponDamageMult') or 1):.2f}, "
                f"fire rate ×{float(weapon.get('weaponRofMult') or 1):.2f})"
            )
        elif (
            weapon
            and slot == "weapon"
            and "flurry" in enc.name.lower()
        ):
            extra = (
                f" (calculator: damage ×{float(weapon.get('weaponDamageMult') or 1):.2f}, "
                f"fire rate ×{float(weapon.get('weaponRofMult') or 1):.2f})"
            )
        detail = f": {enc.value}" if enc.value else ""
        lines.append(f"    - {enc.name}{detail}{extra}")
    return lines


def format_shark_truth(
    label: str,
    loadouts: list[Loadout],
    *,
    asked_stat: Optional[str] = None,
    season: Optional[str] = None,
) -> str:
    if not loadouts:
        return ""
    lines = [
        f"REALMSHARK SOURCE OF TRUTH - {label}",
        f"{_SECONDS:.0f}s window, {_ABILITY_USES} ability uses, 0 DEF, full buffs"
        + (f", season {season}" if season else "")
        + ". Copy these numbers. Do not invent a different DPS. "
        "Do not recommend a set unless the user asked for gear. "
        "On-character enchants are already inside the stats and DPS.",
        "Source: https://tracker.realmshark.cc/dps-leaderboards",
        "",
    ]
    asked = STAT_ALIASES.get((asked_stat or "").lower(), asked_stat) if asked_stat else None
    best_asked: Optional[tuple[int, str]] = None
    for row in loadouts:
        by_slot = _slot_map(row)
        weapon = by_slot.get("weapon") or row.weapon_name or ""
        ability = by_slot.get("ability") or row.ability_name or ""
        dps = _fmt_n(row.dps)
        lines.append(f"Rank {row.rank} {row.player_name} - **{dps} potential DPS**")
        if row.total_damage is not None or row.weapon_damage is not None:
            lines.append(
                f"- Split: weapon {_fmt_n(row.weapon_damage)} + ability "
                f"{_fmt_n(row.ability_damage)} = {_fmt_n(row.total_damage)} "
                f"total / {_SECONDS:.0f}s"
            )
        if row.stats:
            order = (
                "Attack",
                "Dexterity",
                "Defense",
                "Speed",
                "Vitality",
                "Wisdom",
                "HP",
                "MP",
            )
            bits = [f"{key} {row.stats[key]}" for key in order if key in row.stats]
            lines.append("- Stats with on-character enchants: " + ", ".join(bits))
            if asked and asked in row.stats:
                value = row.stats[asked]
                if best_asked is None or value > best_asked[0]:
                    best_asked = (value, row.player_name)
        for piece in row.equipment:
            slot = piece.slot.lower()
            rare = f" {piece.rarity}" if piece.rarity else ""
            lines.append(f"- {piece.slot} [item:{piece.item_name}]{rare}")
            lines.extend(_format_enchants(piece.enchants, row.debug, slot))
            if slot == "weapon" and not piece.enchants and weapon:
                pass
        if not row.equipment:
            cell = lambda n: f"[item:{n}]" if n else "?"
            lines.append(
                f"- Gear: {cell(weapon)} / {cell(ability)} / "
                f"{cell(by_slot.get('armor', ''))} / {cell(by_slot.get('ring', ''))}"
            )
        lines.append("")
    if best_asked and asked:
        lines.append(
            f"Highest {asked} on this board (enchants included): "
            f"**{best_asked[0]}** ({best_asked[1]})."
        )
        lines.append("")
    return "\n".join(lines).rstrip()


def format_reconstruction(
    estimate: Optional[dict],
    row: Loadout,
    reconstructed: Optional[float],
    *,
    ability_formula: Optional[dict] = None,
    ability_reconstructed: Optional[float] = None,
) -> str:
    dmg_mult, rof_mult, dmg_buff, berserk, _pre, _post = _debug_mults(
        row.debug, enchants=weapon_enchants(row), kind="weapon"
    )
    _a_dmg, _a_rof, ability_buff, _berserk, _a_pre, _a_post = _debug_mults(
        row.debug, enchants=ability_enchants(row), kind="ability"
    )
    att = float((row.stats or {}).get("Attack") or (estimate or {}).get("att") or _DEFAULT_ATT)
    dex = float((row.stats or {}).get("Dexterity") or (estimate or {}).get("dex") or _DEFAULT_DEX)
    lines: list[str] = []
    if estimate and reconstructed is not None:
        shark = row.weapon_damage
        lines.extend(
            [
                "Reverse-engineered weapon half (RealmShark number still wins):",
                "- avg damage × shots × APS ((1.5 + 6.5 × DEX/75) × item Rate of "
                "Fire × enchant fire-rate × "
                f"{'Berserk ' + str(_BERSERK_ROF) if berserk else 'no Berserk'}) × "
                "(0.5 + ATT/50) × enchant damage × Damaging × Curse × Exposed "
                "(dummy ×1.20) × Vulnerable (115%) "
                f"× {_SECONDS:.0f}s",
                f"- This row: avg {estimate['avg']:.1f} × {estimate['shots']:.0f} shots, "
                f"ATT {att:.0f}, DEX {dex:.0f}, enchant damage ×{dmg_mult:.2f}, "
                f"enchant fire rate ×{rof_mult:.2f}, buff damage ×{dmg_buff:.3f}",
                f"- Reconstructed weapon damage: **{_fmt_n(reconstructed)}** vs "
                f"RealmShark weapon {_fmt_n(shark)}",
            ]
        )
        if shark and reconstructed:
            ratio = shark / reconstructed
            lines.append(
                f"- Residual (rounding) ≈ ×{ratio:.3f}. "
                "Scale the RealmShark weapon number by new_reconstruct / this reconstruct."
            )
    if ability_formula and ability_reconstructed is not None:
        mod = stat_mod_multiplier(row.debug, ability_enchants(row))
        stat_name = ability_formula["stat"]
        raw_stat = float((row.stats or {}).get(stat_name) or 0)
        uses = ability_uses(row.debug)
        mana = parse_mana_enchants(ability_enchants(row))
        lines.extend(
            [
                "Reverse-engineered ability half (RealmShark number still wins):",
                f"- per use: (avg {ability_formula['avg']:.1f} + {ability_formula['per']:.1f} "
                f"× max(0, {stat_name} × StatMod - {ability_formula['threshold']:.0f})) "
                f"× {ability_formula['shots']:.0f} shots × {uses:.0f} uses × "
                f"Damaging × Curse × Exposed × Vulnerable ×{ability_buff:.3f} "
                "(Berserk is weapon-only)",
                f"- This row: {stat_name} {raw_stat:.0f}, Stat Mod ×{mod:.2f} "
                f"(effective {raw_stat * mod:.1f}), "
                f"reconstructed ability **{_fmt_n(ability_reconstructed)}** vs "
                f"RealmShark ability {_fmt_n(row.ability_damage)}",
            ]
        )
        if mana["flat"] or mana["percent"] or mana["mp_cost_reduction"]:
            lines.append(
                f"- Ability mana enchants on this row: flat {mana['flat']:.0f}/s, "
                f"percent {mana['percent'] * 100:.2f}% max MP/s, "
                f"MP cost -{mana['mp_cost_reduction'] * 100:.0f}%. "
                "RealmShark still uses the board's ability-use count unless debug "
                "effectiveAbilityCount differs."
            )
        lines.append(ideal_ability_enchants(ability_formula))
        if row.ability_damage and ability_reconstructed:
            ratio = row.ability_damage / ability_reconstructed
            lines.append(
                f"- Residual (minion extra volleys and rounding) ≈ ×{ratio:.3f}. "
                "Scale the RealmShark ability number by new_reconstruct / this reconstruct."
            )
    return "\n".join(lines)


def _asked_stat(stat: Optional[str]) -> Optional[str]:
    if not stat:
        return None
    return STAT_ALIASES.get(stat.lower(), stat if stat in PLAYER_STATS else None)


async def _cached_item(redis: aioredis.Redis, name: str) -> Optional[ItemProfile]:
    return await read_cached_item(redis, name)


def _highest_stat(loadouts: list[Loadout], stat: str) -> Optional[tuple[int, str, Optional[float]]]:
    best: Optional[tuple[int, str, Optional[float]]] = None
    for row in loadouts:
        value = (row.stats or {}).get(stat)
        if value is None:
            continue
        if best is None or value > best[0]:
            best = (value, row.player_name, row.dps)
    return best


def _wiki_total(payload: Optional[dict], stat: Optional[str]) -> Optional[int]:
    if not payload or not stat:
        return None
    want = stat.lower()
    for row in payload.get("rows") or []:
        if str(row.get("stat") or "").lower() != want:
            continue
        total = row.get("total")
        if total is None:
            continue
        try:
            return int(total)
        except (TypeError, ValueError):
            return None
    return None


async def _max_stats_payload(
    redis: aioredis.Redis, class_name: str
) -> Optional[dict]:
    import json

    raw = await redis.get(f"{CLASS_MAXSTATS_PREFIX}:{class_name.lower()}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


_CHAR_STAT_ATTR = {
    "HP": "hp",
    "MP": "mp",
    "Attack": "attack",
    "Defense": "defense",
    "Speed": "speed",
    "Dexterity": "dexterity",
    "Vitality": "vitality",
    "Wisdom": "wisdom",
}
_EQUIP_SLOT_ORDER = ("weapon", "ability", "armor", "ring")
_SKIP_TOOLTIP_PREFIX = re.compile(
    r"^(divine|untiered|rare|legendary|shiny|ut\b|st\b|t\d+|set\b)",
    re.I,
)
_KNOWN_ENCHANT = re.compile(
    r"\b("
    r"flurry of blows|overwhelming strikes|damage tradeoff|"
    r"fire\s*rate tradeoff|firerate tradeoff|damage bonus|"
    r"weapon damage bonus|fire\s*rate bonus|firerate bonus|"
    r"stat mod(?:ifier| multiplier)?|percentage mana regen|"
    r"flat mana regen|mp cost reduction"
    r")\s+(IV|III|II|I)\b",
    re.I,
)
_GENERIC_ENCHANT = re.compile(
    r"\b([A-Z][A-Za-z]+(?:[\s/-]+[A-Z][A-Za-z]+){0,4})\s+(IV|III|II|I)\b",
)
_UNIQUE_ENCHANT = re.compile(
    r"\b(on[\s-]?hit\s+[A-Za-z]+(?:\s+[A-Za-z]+)?|on[\s-]?shoot\s+[A-Za-z]+)\b",
    re.I,
)
_WEAPON_ENCHANT_HINT = re.compile(
    r"flurry|overwhelming|tradeoff|damage bonus|fire\s*rate|on[\s-]?hit|on[\s-]?shoot",
    re.I,
)
_ABILITY_ENCHANT_HINT = re.compile(
    r"stat mod|mana regen|mp cost",
    re.I,
)


def pick_player_character(
    profile: PlayerProfile,
    class_name: Optional[str],
) -> Optional[CharacterSummary]:
    chars = list(profile.characters or [])
    if not chars:
        return None
    if class_name:
        want = class_name.lower()
        aliases = {want, *(a.lower() for a in CLASS_ALIASES.get(class_name, ()))}
        matched = [
            char
            for char in chars
            if (char.class_name or "").lower() in aliases
            or (char.class_name or "").lower() == want
        ]
        if not matched:
            return None
        chars = matched
    return max(chars, key=lambda char: char.fame or 0)


def character_sheet_stats(char: CharacterSummary) -> dict[str, float]:
    stats = char.stats
    if not stats:
        return {}
    out: dict[str, float] = {}
    for label, attr in _CHAR_STAT_ATTR.items():
        value = getattr(stats, attr, None)
        if value is not None:
            out[label] = float(value)
    return out


def _normalize_tooltip(tooltip: str) -> str:
    """Bootstrap titles often use <br> and data-original-title HTML."""
    text = unescape(tooltip or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?(?:div|p|span)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def enchants_from_tooltip(tooltip: str) -> list[ItemEnchant]:
    """Parse on-character enchants from a RealmEye item tooltip or user text.

    Live titles are often one flattened line ('Divine Warmonger UT Flurry of
    Blows IV') or HTML ('...UT<br>Flurry of Blows IV'), so a whole-line
    ^...$ match misses the enchant even when the card hover shows it.
    """
    found: list[ItemEnchant] = []
    seen: set[str] = set()
    text = _normalize_tooltip(tooltip)
    for i, line in enumerate(text.splitlines()):
        raw = " ".join(line.split())
        if not raw:
            continue
        if (
            i == 0
            and _SKIP_TOOLTIP_PREFIX.search(raw)
            and not _KNOWN_ENCHANT.search(raw)
            and not _GENERIC_ENCHANT.search(raw)
            and not _UNIQUE_ENCHANT.search(raw)
        ):
            continue
        for match in (*_KNOWN_ENCHANT.finditer(raw), *_GENERIC_ENCHANT.finditer(raw)):
            name = f"{match.group(1).strip(' :-')} {match.group(2).upper()}"
            if re.search(r"\b(tier|ut|st|fame|rank|divine|untiered)\b", name, re.I):
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(ItemEnchant(name=name, value=match.group(0).strip()))
        for match in _UNIQUE_ENCHANT.finditer(raw):
            name = re.sub(r"[\s-]+", " ", match.group(1)).strip()
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(ItemEnchant(name=name, value=name))
    return found


def merge_named_enchants(
    slots: list[tuple[str, str, list[ItemEnchant]]],
    message: str,
) -> list[tuple[str, str, list[ItemEnchant]]]:
    """Fold user-named enchants onto the matching worn slot."""
    incoming = enchants_from_tooltip(message)
    if not incoming:
        return slots
    lowered = (message or "").lower()
    used: set[str] = set()
    out: list[tuple[str, str, list[ItemEnchant]]] = []
    for slot, name, existing in slots:
        have = {enc.name.lower() for enc in existing}
        extra: list[ItemEnchant] = []
        for enc in incoming:
            key = enc.name.lower()
            if key in have:
                used.add(key)
                continue
            if name.lower() in lowered and key not in used:
                extra.append(enc)
                used.add(key)
        out.append((slot, name, list(existing) + extra))
    remainder = [enc for enc in incoming if enc.name.lower() not in used]
    if not remainder:
        return out
    patched: list[tuple[str, str, list[ItemEnchant]]] = []
    for slot, name, enchants in out:
        add = []
        for enc in remainder:
            if slot == "weapon" and _WEAPON_ENCHANT_HINT.search(enc.name):
                add.append(enc)
            elif slot == "ability" and _ABILITY_ENCHANT_HINT.search(enc.name):
                add.append(enc)
        patched.append((slot, name, enchants + add))
    return patched


def character_slot_pieces(char: CharacterSummary) -> list[tuple[str, str, list[ItemEnchant]]]:
    from .enchanting import infer_gear_slot

    pieces: list[tuple[str, str, list[ItemEnchant]]] = []
    used: set[str] = set()
    for i, item in enumerate(char.equipment or []):
        name = (item.name or "").strip()
        if not name or name.lower() == "unknown item":
            continue
        slot = infer_gear_slot(name)
        if not slot and i < len(_EQUIP_SLOT_ORDER):
            slot = _EQUIP_SLOT_ORDER[i]
        if not slot or slot in used:
            continue
        used.add(slot)
        pieces.append((slot, name, enchants_from_tooltip(item.tooltip or "")))
    return pieces


# A worn piece with no RealmEye wiki page yet, negative-cached so the next
# turn skips the Playwright timeout. Mirrors Settings.missing_item_ttl_seconds.
_MISSING_WORN_ITEM_TTL = 3600


def _item_match_key(name: str) -> str:
    """Compare item names ignoring apostrophe style, spacing, and case."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


async def worn_item_profiles(
    redis: aioredis.Redis,
    slots: list[tuple[str, str, list[ItemEnchant]]],
    *,
    ttl_seconds: int,
) -> dict[str, ItemProfile]:
    """Wiki pages for the worn set, scraping only the pieces not stored yet.

    The rest of the chat path is cache-only, but this one already paid a live
    RealmEye profile scrape, and a single un-warmed piece used to drop the
    whole reconstruct to "not enough stored wiki shot/ability data" - which is
    how a named player's DPS came back invented instead of measured. Capped at
    the equipped slots, and a piece with no wiki page is remembered so the
    next turn fails fast instead of re-paying the scrape.
    """
    from .wiki_scaling import _profiles_for_names

    by_key: dict[str, ItemProfile] = {}
    missing: list[str] = []
    for _slot, name, _enchants in slots:
        cached = await read_cached_item(redis, name)
        if cached:
            by_key[_item_match_key(name)] = cached
        elif not await is_item_marked_missing(redis, name):
            missing.append(name)
    if not missing:
        return by_key
    try:
        scraped = await _profiles_for_names(
            redis, missing[: len(_EQUIP_SLOT_ORDER)], ttl_seconds
        )
    except Exception as e:
        logger.bind(items=missing, error=str(e)).warning(
            "DPS specialist could not scrape worn gear wiki pages"
        )
        return by_key
    found = {_item_match_key(item.name): item for item in scraped}
    for name in missing:
        item = found.get(_item_match_key(name))
        if item:
            by_key[_item_match_key(name)] = item
        else:
            await mark_item_missing(redis, name, _MISSING_WORN_ITEM_TTL)
    return by_key


async def format_player_set_dps(
    redis: aioredis.Redis,
    message: str,
    *,
    player_ign: str,
    class_name: Optional[str],
    player_ttl_seconds: int,
    ttl_seconds: int,
) -> list[str]:
    """Scrape the IGN, pick the named class, reconstruct dummy DPS from worn wiki."""
    try:
        profile = await get_or_scrape_player(
            redis,
            player_ign,
            ttl_seconds=player_ttl_seconds,
        )
    except Exception as e:
        logger.bind(username=player_ign, error=str(e)).warning(
            "DPS specialist could not scrape player profile"
        )
        return [
            f"PLAYER SET DPS - could not load RealmEye /player/{player_ign}. "
            "Do not invent this character's gear or stats."
        ]
    char = pick_player_character(profile, class_name)
    if not char:
        label = class_name or "character"
        return [
            f"PLAYER SET DPS - scraped [player:{profile.username}] but found no "
            f"{label} on the characters list. Do not invent that character."
        ]
    sheet = character_sheet_stats(char)
    slots = merge_named_enchants(character_slot_pieces(char), message)
    worn: dict[str, ItemProfile] = {}
    enchant_texts: list[tuple[str, str]] = []
    parts = [
        f"PLAYER SET DPS - {profile.username}'s {char.class_name} from the "
        "scraped RealmEye profile. Copy this reconstruct. It is this "
        "character's worn set on the 5s / 8-use / 0 DEF dummy with party "
        "buffs, not a RealmShark board row.",
        "The UI shows only this class's character row (same hover tooltips as "
        "a player lookup). Do not copy Fame, Guild, exaltations, pet, last "
        "seen, or other classes. Do not open with the account name. Copy the "
        "reconstruct numbers. A breakdown must walk weapon, ability, armor, "
        "and ring from HOW EACH WORN PIECE. Name an enchant only when that "
        "channel changed a multiplier or a working stat; a sheet-stat "
        "tradeoff is already in the RealmEye totals.",
        f"Source: https://www.realmeye.com/player/{profile.username}",
    ]
    if char.stats_maxed:
        parts.append(f"Maxed: {char.stats_maxed}.")
    worn_names = []
    profiles = await worn_item_profiles(redis, slots, ttl_seconds=ttl_seconds)
    for slot, name, enchants in slots:
        worn_names.append(f"{slot} [item:{name}]")
        cached = profiles.get(_item_match_key(name))
        if cached:
            worn[slot] = cached
        else:
            parts.append(
                f"No stored wiki profile for [item:{name}] ({slot}). "
                "Do not invent Damage / Shots / Rate of Fire for it."
            )
        for enc in enchants:
            enchant_texts.append((name, f"{enc.name}: {enc.value}"))
    parts.append("Worn: " + (", ".join(worn_names) if worn_names else "no equipment scraped."))
    if sheet:
        parts.append(
            "RealmEye sheet stats (On Equip already included): "
            + ", ".join(f"{k} {v:.0f}" for k, v in sheet.items() if v)
        )
    worn_items = [worn[s] for s in _EQUIP_SLOT_ORDER if s in worn]
    catalog = inspect_worn_set(worn_items, enchant_texts=enchant_texts)
    parts.append(format_set_effects(worn_items, enchant_texts=enchant_texts))
    stats = combat_stat_sheet(sheet, catalog)
    parts.append(format_working_stats(sheet, catalog, stats))
    att = float(stats.get("Attack") or _DEFAULT_ATT)
    dex = float(stats.get("Dexterity") or _DEFAULT_DEX)
    weapon_item = worn.get("weapon")
    ability_item = worn.get("ability")
    ability_formula = (
        parse_ability_formula(ability_item.stats or {}) if ability_item else None
    )
    ability_stat = ability_formula["stat"] if ability_formula else None
    enchant_lines: list[str] = []
    for slot, name, enchants in slots:
        if enchants:
            enchant_lines.append(
                f"- {slot} [item:{name}]: "
                + "; ".join(
                    format_enchant_channel(enc, ability_stat=ability_stat)
                    for enc in enchants
                )
            )
        else:
            enchant_lines.append(
                f"- {slot} [item:{name}]: none listed on the tooltip"
            )
    parts.append(
        "ON-CHARACTER ENCHANTS (same tooltip text the card hover shows; "
        "apply each on its channel, even though the reply must not reprint "
        "them as a list):\n" + "\n".join(enchant_lines)
    )
    parts.append(
        format_slot_contributions(
            slots, worn, catalog, ability_stat=ability_stat
        )
    )
    weapon_enc = [
        enc for slot, _name, enchants in slots if slot == "weapon" for enc in enchants
    ]
    ability_enc = [
        enc for slot, _name, enchants in slots if slot == "ability" for enc in enchants
    ]
    estimate = None
    reconstructed = None
    weapon_steps: dict = {}
    ability_steps: dict = {}
    # Berserk has to come from this character's own gear or enchants, not from
    # a blanket party assumption. See _debug_mults.
    berserk_source = set_grants_berserk(worn_items, enchant_texts=enchant_texts)
    if weapon_item:
        estimate = estimate_weapon_dps(weapon_item.stats or {}, dex=dex, att=att)
        if estimate:
            reconstructed = reconstruct_weapon_damage(
                estimate,
                att=att,
                dex=dex,
                debug={},
                enchants=weapon_enc,
                steps=weapon_steps,
                berserk_source=berserk_source,
            )
    ability_recon = None
    if ability_formula:
        ability_recon = reconstruct_ability_damage(
            ability_formula,
            stats=stats,
            debug={},
            enchants=ability_enc,
            steps=ability_steps,
        )
    if reconstructed is None and ability_recon is None:
        parts.append(
            "Not enough stored wiki shot/ability data to reconstruct this set. "
            "Do not invent a DPS number."
        )
        return parts
    weapon_n = reconstructed or 0.0
    ability_n = ability_recon or 0.0
    total = weapon_n + ability_n
    dps = total / _SECONDS
    # A summon/tick ability (Genesis Spell) has no Damage row to reconstruct.
    # Adding up only one half and still calling it "potential DPS" reads as a
    # complete ceiling, so name what is missing instead.
    missing_half = "ability" if ability_recon is None else (
        "weapon" if reconstructed is None else ""
    )
    label = "potential DPS"
    if missing_half:
        label = f"{'weapon' if missing_half == 'ability' else 'ability'}-only DPS"
    parts.append(
        f"Wiki reconstruct for {profile.username}'s {char.class_name}: "
        f"weapon **{_fmt_n(reconstructed)}** damage over {_SECONDS:.0f}s, "
        f"ability **{_fmt_n(ability_recon)}** damage over {_SECONDS:.0f}s, "
        f"{label} **{_fmt_n(dps)}** per second "
        f"(ATT {att:.0f}, DEX {dex:.0f}"
        + (
            f", {ability_formula['stat']} "
            f"{stats.get(ability_formula['stat'], 0):.0f}"
            # ATT and DEX are already printed above; only a third scaling
            # stat (WIS on most abilities) is worth repeating.
            if ability_formula
            and ability_formula["stat"] not in {"Attack", "Dexterity"}
            else ""
        )
        + "). This is not a RealmShark leaderboard row."
    )
    parts.append(
        format_dps_derivation(
            weapon_item=weapon_item,
            ability_item=ability_item,
            weapon_steps=weapon_steps,
            ability_steps=ability_steps,
            total=total,
            dps=dps,
            label=label,
        )
    )
    parts.append(
        format_practice_dummy(
            estimate,
            ability_formula,
            att=att,
            dex=dex,
            stats=stats,
            worn_items=worn_items,
            enchant_texts=enchant_texts,
            weapon_enchants=weapon_enc,
            ability_enchants=ability_enc,
            ceiling=total,
        )
    )
    if missing_half:
        missing_item = worn.get(missing_half)
        named = f" ([item:{missing_item.name}])" if missing_item else ""
        parts.append(
            f"The {missing_half} half{named} has no reconstructable damage on "
            "its wiki page, so the number above is a floor for this set, not "
            f"the ceiling. Say the {missing_half} damage is not included. Do "
            "not invent it and do not call this the full potential DPS."
        )
    return parts


def _replacement_items(
    message: str, loadout: Loadout, mentioned: list[str]
) -> list[str]:
    if not mentioned:
        return []
    worn = {s.item_name.lower() for s in loadout.equipment}
    if loadout.weapon_name:
        worn.add(loadout.weapon_name.lower())
    if loadout.ability_name:
        worn.add(loadout.ability_name.lower())
    extras = [name for name in mentioned if name.lower() not in worn]
    if extras:
        return extras
    if _SWAP.search(message or ""):
        return mentioned
    return []


async def retrieve_dps_brief(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int,
    class_name: Optional[str] = None,
    stat: Optional[str] = None,
    player_ign: Optional[str] = None,
    player_ttl_seconds: int = 120,
    cache_only: bool = True,
) -> str:
    from .item_aliases import community_canonical, extract_mentioned_items, resolve_item_query
    from .realmshark import load_graph, load_top_loadouts

    asked = _asked_stat(stat)
    ign = player_ign or extract_player_ign(message)
    parts = [
        "DPS AGENT - RealmShark potential-DPS boards are the source of truth "
        "for class ceilings (5s / 8 ability uses, 0 DEF, full buffs, on-character "
        "enchants already applied). A named player's class uses that character's "
        "scraped RealmEye gear and stats first. Copy those numbers. Wiki weapon "
        "shot data and wiki ability scaling (plus Stat Mod Multiplier on the "
        "scaling stat) reconstruct each half so a swap can scale the stored "
        "RealmShark weapon and ability numbers. Identify the worn weapon, "
        "ability, armor, and ring first, then read each wiki page and "
        "on-character enchant for status grants and stat procs. "
        "Do not invent DPS. Do not recommend a set unless the user asked for gear. "
        "Do not add extra enchant rolls on top of a RealmShark DPS that already "
        "includes them."
    ]
    if ign:
        parts.extend(
            await format_player_set_dps(
                redis,
                message,
                player_ign=ign,
                class_name=class_name,
                player_ttl_seconds=player_ttl_seconds,
                ttl_seconds=ttl_seconds,
            )
        )
    mentioned = extract_mentioned_items(message)
    item_name = None if ign else (mentioned[0] if mentioned else extract_dps_item(message))
    names = mentioned or ([item_name] if item_name else [])
    wiki_by_name: dict[str, tuple[ItemProfile, Optional[dict]]] = {}
    for raw in names:
        resolved = community_canonical(raw) or await resolve_item_query(
            redis,
            raw,
            ttl_seconds=ttl_seconds,
            class_name=class_name,
            allow_scrape=False,
        )
        lookup = resolved or raw
        item = await _cached_item(redis, lookup)
        if item:
            estimate = estimate_weapon_dps(item.stats or {})
            wiki_by_name[item.name] = (item, estimate)
            parts.append(format_wiki_estimate(item, estimate))
        else:
            parts.append(
                f"No stored wiki profile for {lookup}. "
                "Do not invent Damage / Shots / Rate of Fire."
            )
    if len(names) > 1:
        parts.append(
            "Compare wiki estimates only as formula inputs. The winner is the "
            "RealmShark row when one exists, not a third invented item."
        )

    try:
        graph = await load_graph(redis, ttl_seconds, cache_only=True)
    except Exception as e:
        logger.bind(error=str(e)).warning("DPS specialist could not load RealmShark graph")
        return "\n\n".join(parts)

    class_edges = [
        e
        for e in graph.edges
        if not class_name or e.class_name.lower() == class_name.lower()
    ]
    matched = [
        e
        for e in class_edges
        if not asked or e.stat.lower() == asked.lower()
    ]
    if not matched and class_edges and asked:
        parts.append(
            f"RealmShark has no {asked} {class_name or ''} DPS board. "
            "Numbers below are from this class's other potential-DPS boards. "
            "Those stats include on-character enchants. They are not a "
            "theoretical tank stack."
        )
        matched = class_edges
    if not matched:
        if any(p.startswith("PLAYER SET DPS") for p in parts):
            parts.append(
                "No RealmShark potential-DPS board for this class to compare. "
                "Copy the player-set reconstruct above. Do not invent a board number."
            )
        elif class_name or asked:
            parts.append(
                "No RealmShark potential-DPS board for this class/stat. "
                "Use the wiki estimate only. Do not invent a board number."
            )
        return "\n\n".join(p for p in parts if p)

    all_loadouts: list[Loadout] = []
    for edge in matched[:4]:
        loadouts = await load_top_loadouts(
            redis,
            edge,
            season=graph.season,
            ttl_seconds=ttl_seconds,
            cache_only=True,
        )
        if not loadouts:
            continue
        all_loadouts.extend(loadouts)
        parts.append(
            format_shark_truth(
                edge.label,
                loadouts,
                asked_stat=asked,
                season=graph.season,
            )
        )
        top = loadouts[0]
        by_slot = _slot_map(top)
        weapon = by_slot.get("weapon") or top.weapon_name
        ability_name = by_slot.get("ability") or top.ability_name
        worn: dict[str, ItemProfile] = {}
        for slot_name, piece_name in (
            ("weapon", weapon),
            ("ability", ability_name),
            ("armor", by_slot.get("armor")),
            ("ring", by_slot.get("ring")),
        ):
            if not piece_name:
                continue
            cached = await _cached_item(redis, piece_name)
            if cached:
                worn[slot_name] = cached
                if slot_name in {"ability", "armor", "ring"}:
                    parts.append(format_wiki_estimate(cached, None))
        worn_items = [worn[s] for s in ("weapon", "ability", "armor", "ring") if s in worn]
        enchant_texts = enchant_texts_from_loadout(top)
        catalog = inspect_worn_set(worn_items, enchant_texts=enchant_texts)
        parts.append(format_set_effects(worn_items, enchant_texts=enchant_texts))
        stats = combat_stat_sheet(top.stats or {}, catalog)
        att = float(stats.get("Attack") or _DEFAULT_ATT)
        dex = float(stats.get("Dexterity") or _DEFAULT_DEX)
        weapon_item = worn.get("weapon")
        reconstructed = None
        if weapon_item:
            estimate = estimate_weapon_dps(weapon_item.stats or {}, dex=dex, att=att)
            if estimate:
                reconstructed = reconstruct_weapon_damage(
                    estimate,
                    att=att,
                    dex=dex,
                    debug=top.debug,
                    enchants=weapon_enchants(top),
                )
        ability_item = worn.get("ability")
        ability_formula = (
            parse_ability_formula(ability_item.stats or {}) if ability_item else None
        )
        ability_recon = None
        if ability_formula:
            ability_recon = reconstruct_ability_damage(
                ability_formula,
                stats=stats,
                debug=top.debug,
                enchants=ability_enchants(top),
            )
        if reconstructed is not None or ability_recon is not None:
            parts.append(
                format_reconstruction(
                    estimate,
                    top,
                    reconstructed,
                    ability_formula=ability_formula,
                    ability_reconstructed=ability_recon,
                )
            )
        if _SWAP.search(message or "") or re.search(
            r"\binstead(?:\s+of)?\b", message or "", re.I
        ):
            from .enchanting import infer_gear_slot

            replacements = _replacement_items(message, top, list(wiki_by_name))
            for new_name in replacements:
                new_item, new_est = wiki_by_name[new_name]
                slot = infer_gear_slot(new_item.name) or infer_gear_slot(
                    " ".join((new_item.stats or {}).keys())
                )
                if not slot and parse_ability_formula(new_item.stats or {}):
                    slot = "ability"
                if not slot and estimate_weapon_dps(new_item.stats or {}):
                    slot = "weapon"
                if not slot:
                    slot = "armor"
                new_stats = {k: float(v) for k, v in (top.stats or {}).items()}
                old_piece = worn.get(slot)
                old_contrib = gear_stat_contribution(old_piece) if old_piece else {}
                new_contrib = gear_stat_contribution(new_item)
                for stat_name in PLAYER_STATS:
                    delta = new_contrib.get(stat_name, 0) - old_contrib.get(stat_name, 0)
                    if delta:
                        new_stats[stat_name] = new_stats.get(stat_name, 0) + delta
                if slot == "weapon":
                    old_shoot = combat_shoot_deltas(old_piece) if old_piece else {}
                    new_shoot = combat_shoot_deltas(new_item)
                    for stat_name in ("Attack", "Dexterity"):
                        delta = new_shoot.get(stat_name, 0) - old_shoot.get(stat_name, 0)
                        if delta:
                            new_stats[stat_name] = new_stats.get(stat_name, 0) + delta
                new_att = new_stats.get("Attack", att)
                new_dex = new_stats.get("Dexterity", dex)
                use_est = estimate
                if slot == "weapon":
                    use_est = new_est or estimate_weapon_dps(
                        new_item.stats or {}, dex=new_dex, att=new_att
                    )
                new_weapon_recon = None
                weapon_debug = top.debug
                weapon_enc = weapon_enchants(top)
                if slot == "weapon":
                    weapon_debug = {**(top.debug or {}), "weaponEnchant": {}}
                    weapon_enc = []
                if use_est:
                    new_weapon_recon = reconstruct_weapon_damage(
                        use_est,
                        att=new_att,
                        dex=new_dex,
                        debug=weapon_debug,
                        enchants=weapon_enc,
                    )
                scaled_weapon = scale_shark_weapon(
                    top.weapon_damage or 0.0,
                    reconstructed or 0.0,
                    new_weapon_recon or 0.0,
                )
                new_ability_formula = ability_formula
                new_ability_ench = ability_enchants(top)
                if slot == "ability":
                    new_ability_formula = parse_ability_formula(new_item.stats or {})
                    new_ability_ench = []
                new_ability_recon = None
                if new_ability_formula:
                    new_ability_recon = reconstruct_ability_damage(
                        new_ability_formula,
                        stats=new_stats,
                        debug=top.debug if slot != "ability" else {},
                        enchants=new_ability_ench,
                    )
                scaled_ability = scale_shark_weapon(
                    top.ability_damage or 0.0,
                    ability_recon or 0.0,
                    new_ability_recon or 0.0,
                )
                if slot != "ability" and (scaled_ability is None or not ability_recon):
                    scaled_ability = top.ability_damage
                if slot != "weapon" and (scaled_weapon is None or not reconstructed):
                    scaled_weapon = top.weapon_damage
                if scaled_weapon is None and scaled_ability is None:
                    continue
                weapon_n = scaled_weapon if scaled_weapon is not None else 0.0
                ability_n = scaled_ability if scaled_ability is not None else 0.0
                new_dps = (weapon_n + ability_n) / _SECONDS
                proc_note = ""
                swap_catalog = inspect_worn_set([new_item])
                bits = []
                for proc in swap_catalog["procs"]:
                    if not proc.get("bonuses"):
                        continue
                    joined = ", ".join(
                        f"{stat} {value:+d}" for stat, value in proc["bonuses"].items()
                    )
                    bits.append(f"On {proc['trigger']} {joined}")
                for flag, names in swap_catalog["grants"].items():
                    bits.append(flag)
                if bits:
                    proc_note = " Set effects on the new piece: " + "; ".join(bits)
                parts.append(
                    f"Modification vs Rank {top.rank} {top.player_name}: "
                    f"swap {slot} for [item:{new_item.name}]. Scaled RealmShark "
                    f"weapon {_fmt_n(top.weapon_damage)} → **{_fmt_n(scaled_weapon)}**, "
                    f"ability {_fmt_n(top.ability_damage)} → **{_fmt_n(scaled_ability)}** "
                    f"(ATT {new_att:.0f}, DEX {new_dex:.0f}"
                    + (
                        f", {new_ability_formula['stat']} "
                        f"{new_stats.get(new_ability_formula['stat'], 0):.0f}"
                        if new_ability_formula
                        else ""
                    )
                    + f"). Estimated potential DPS **{_fmt_n(new_dps)}**. "
                    "This is a scaled RealmShark number, not a new board row."
                    + proc_note
                )

    if asked and all_loadouts:
        best = _highest_stat(all_loadouts, asked)
        wiki_payload = (
            await _max_stats_payload(redis, class_name) if class_name else None
        )
        wiki_total = _wiki_total(wiki_payload, asked)
        lines = []
        if best:
            lines.append(
                f"Highest {asked} on stored RealmShark {class_name or 'class'} "
                f"DPS sets (enchants included): **{best[0]}** "
                f"({best[1]}, {_fmt_n(best[2])} potential DPS)."
            )
        if wiki_total is not None:
            lines.append(
                f"RealmEye Maximum Achievable Stats wiki total for "
                f"{class_name} {asked}: **{wiki_total}**. That stack is 8/8 "
                "gear without these on-character enchants. Do not add wiki "
                "total on top of a RealmShark stat that already includes them."
            )
        if lines:
            parts.append("\n".join(lines))
    return "\n\n".join(p for p in parts if p)
