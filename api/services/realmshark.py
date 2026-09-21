"""
RealmShark DPS tracker client and ability-scaling knowledge graph.

The tracker publishes:
  GET /api/v1/dps-builds     — which ability items scale with which 8/8 stat
  GET /api/v1/dps-leaderboard — top potential-DPS loadouts per build

We treat the builds catalog as a graph (class --stat--> ability) and keep
the top-5 loadouts on each edge so chat can cite what the best characters
are actually wearing. Redis caches the graph; Qdrant gets a text dump for
vector retrieval.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional

import httpx
import redis.asyncio as aioredis
from loguru import logger

from ..models.build import (
    CLASS_ALIASES,
    PLAYER_STATS,
    STAT_ALIASES,
    WEAPON_SHARE_GROUPS,
    weapon_family,
    AbilityScalingEdge,
    EquipmentSlot,
    ItemEnchant,
    Loadout,
    StatScalingGraph,
)
from .dungeon_guide import (
    extract_dungeon_query,
    extract_portal_source_query,
    retrieve_portal_drop_context,
)
from .biomes import extract_biome_query, retrieve_biome_context
from .rotmg_hub import (
    extract_hub_query,
    matching_hub_excerpt,
    retrieve_rotmg_hub,
)
from .enchanting import is_enchant_query, retrieve_enchanting_brief
from .dps_specialist import (
    dps_subject_from_history,
    is_dps_follow_up,
    is_dps_query,
    is_stat_number_query,
)
from .fuzzy_match import fuzzy_closed_vocab
from .item_aliases import (
    SET_SLOTS,
    is_set_visualize_query,
    is_stat_class_shiny_divine_query,
)
from .skin_visualizer import is_skin_visualize_query
from .player_lookup import extract_player_ign
from .slot_graph import run_slot_agents
from .community_knowledge import slot_alternatives_note, store_ranking_brief
from .wiki_scaling import (
    cached_class_wiki_scaling,
    infer_class_primary_stat,
    resolve_source_rank,
    retrieve_class_max_stats,
)

REALMSHARK_API = "https://tracker.realmshark.cc/api/v1"
REALMSHARK_PAGE = "https://tracker.realmshark.cc/dps-leaderboards"
GRAPH_CACHE_KEY = "dps:graph:seasonal:v2"
# v2 keeps per-slot enchants, weapon/ability damage split, and calculator debug.
LOADOUT_CACHE_PREFIX = "dps:top:v2"
TOP_N = 5

# RealmShark's dps-builds list is "items the calculator allows on this
# board," which is not always "items whose damage scales with this stat."
# Example: it puts Skull of Endless Torment on Attack Necro, but that
# skull's minion damage scales with Wisdom. Overrides win over the board.
_SCALING_OVERRIDES: dict[str, str] = {
    "skull of endless torment": "Wisdom",
}

# Seasonal / event reskins that show up on the boards | skip unless the
# user asked for a creative or LE build.
_LE_NAME = re.compile(
    r"hydroflow|legion elite|nativity|reasonable hour",
    re.IGNORECASE,
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": REALMSHARK_PAGE,
}

# RealmShark board labels -> our 8/8 stat names.
_BOARD_STAT = {
    "attack": "Attack",
    "defense": "Defense",
    "speed": "Speed",
    "dexterity": "Dexterity",
    "vitality": "Vitality",
    "wisdom": "Wisdom",
    "mana": "MP",
    "hp": "HP",
}


def _canon_class(raw: str) -> str:
    """'Bards' / 'Knights' / 'Samurai' -> graph class name."""
    name = (raw or "").strip()
    if name.endswith("es") and name[:-2] in CLASS_ALIASES:
        return name[:-2]
    if name.endswith("s") and name[:-1] in CLASS_ALIASES:
        return name[:-1]
    if name in CLASS_ALIASES:
        return name
    lower = name.lower()
    for canon, aliases in CLASS_ALIASES.items():
        if lower == canon.lower() or lower in aliases:
            return canon
    return name.rstrip("s") or name


def _canon_stat(raw: str) -> str:
    key = (raw or "").strip().lower()
    if key in STAT_ALIASES:
        return STAT_ALIASES[key]
    if key in _BOARD_STAT:
        return _BOARD_STAT[key]
    titled = (raw or "").strip().title()
    return titled if titled in PLAYER_STATS else titled


def _tag_le(name: str) -> str:
    if _LE_NAME.search(name):
        return f"{name} [Limited Edition]"
    return name


# Ability-slot nouns in CLASS_ALIASES must stay exact-only. Fuzzy "spel"
# -> spell -> Wizard would fire on unrelated messages.
_SLOT_NOUNS = frozenset(
    {
        "cloak",
        "quiver",
        "spell",
        "tome",
        "helm",
        "shield",
        "seal",
        "poison",
        "skull",
        "trap",
        "orb",
        "prism",
        "scepter",
        "star",
        "wakizashi",
        "lute",
        "mace",
        "sheath",
        "sigil",
    }
)


def _class_alias_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for canon, aliases in CLASS_ALIASES.items():
        pairs.append((canon.lower(), canon))
        for alias in aliases:
            if alias not in _SLOT_NOUNS:
                pairs.append((alias, canon))
    return pairs


def _stat_alias_pairs() -> list[tuple[str, str]]:
    return list(STAT_ALIASES.items())


_DROP_TURN = re.compile(
    r"\b(?:where\s+(?:does|do).+\bdrop|drop\s+locations?)\b",
    re.I,
)


def _parse_query_text(text: str) -> tuple[Optional[str], Optional[str], bool]:
    lower = text.lower()
    # "prism"/"lute"/... are class aliases for "best prism" builds. A drop
    # or official-new-item ask is about that item, not Trickster/Bard.
    skip_slot_class = bool(extract_hub_query(text) or _DROP_TURN.search(text or ""))
    classes: list[str] = []
    for canon, aliases in CLASS_ALIASES.items():
        needles = (canon.lower(),) + aliases
        if skip_slot_class:
            needles = tuple(n for n in needles if n not in _SLOT_NOUNS)
        if any(re.search(rf"\b{re.escape(n)}\b", lower) for n in needles):
            classes.append(canon)
    class_name = classes[0] if len(classes) == 1 else None
    if class_name is None and not classes:
        fuzzy_classes: list[str] = []
        for token in re.findall(r"[a-z]+", lower):
            canon = fuzzy_closed_vocab(token, _class_alias_pairs())
            if canon and canon not in fuzzy_classes:
                fuzzy_classes.append(canon)
        class_name = fuzzy_classes[0] if len(fuzzy_classes) == 1 else None

    stats: list[str] = []
    seen: set[str] = set()
    for alias in sorted(STAT_ALIASES, key=len, reverse=True):
        if not re.search(rf"\b{re.escape(alias)}\b", lower):
            continue
        canon = STAT_ALIASES[alias]
        if canon not in seen:
            seen.add(canon)
            stats.append(canon)
    stat = stats[0] if len(stats) == 1 else None
    if stat is None and not stats:
        fuzzy_stats: list[str] = []
        for token in re.findall(r"[a-z]+", lower):
            canon = fuzzy_closed_vocab(token, _stat_alias_pairs())
            if canon and canon not in fuzzy_stats:
                fuzzy_stats.append(canon)
        stat = fuzzy_stats[0] if len(fuzzy_stats) == 1 else None

    buildish = bool(
        class_name
        or stat
        or len(classes) > 1
        or len(stats) > 1
        or re.search(
            r"\b(build|loadout|gear|equip|dps|best items?|ability|rings?|armor|robe|weapon)\b",
            lower,
        )
    )
    return class_name, stat, buildish


def _has_own_topic(message: str, history: Optional[list[str]] = None) -> bool:
    """True when this message already names its own specialist topic
    (an enchant question, a dungeon guide, an IGN lookup, or a skin/set
    visualization) independent of any class+stat build context.

    parse_query's history inheritance below exists for thin follow-ups like
    "what other rings" that genuinely continue an earlier build conversation
    with no class/stat of their own. But a message can *also* lack its own
    class/stat while asking about something else entirely - and the weak
    slot-noun half of _parse_query_text's buildish regex (ring/armor/weapon/
    ability, as opposed to the stronger build/loadout/gear/equip/dps/best
    items) is true of nearly every item/enchant question, since those
    questions are inherently about gear. Found live Sep 14: "Shiny divine
    snake eye ring. Is it insane with the awakened enchantment?" has no
    class or stat of its own, "ring" alone made it look buildish, and it
    inherited a completely unrelated Ninja/Attack combo from several turns
    back in the same session. Every one of these detectors is already
    imported above for the specialist routing this same function feeds -
    reuse them here instead of guessing from a weaker signal.
    """
    return bool(
        is_enchant_query(message)
        or is_skin_visualize_query(message, history=history)
        or is_set_visualize_query(message)
        or extract_dungeon_query(message)
        or extract_player_ign(message)
        or extract_hub_query(message, history=history)
        or _DROP_TURN.search(message or "")
    )


def parse_query(
    message: str,
    history: Optional[list[str]] = None,
) -> tuple[Optional[str], Optional[str], bool]:
    """Pull (class, stat, is_buildish) from a chat message.

    Follow-ups like "what other rings" inherit class/stat from earlier turns.
    A message that already names its own specialist topic (enchant, skin,
    set, dungeon, player) never inherits - see _has_own_topic.
    """
    class_name, stat, buildish = _parse_query_text(message)
    if history and not _has_own_topic(message, history=history):
        for prev in reversed(history):
            if class_name and stat:
                break
            prev_class, prev_stat, prev_build = _parse_query_text(prev)
            if not class_name and prev_class:
                class_name = prev_class
            if not stat and prev_stat:
                stat = prev_stat
            buildish = buildish or prev_build
    return class_name, stat, buildish


async def fetch_builds(*, seasonal: bool = True) -> dict:
    params = {"seasonal": "1" if seasonal else "0"}
    async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as client:
        res = await client.get(f"{REALMSHARK_API}/dps-builds", params=params)
        res.raise_for_status()
        return res.json()


async def fetch_leaderboard(
    build_id: str,
    *,
    seasonal: bool = True,
    limit: int = TOP_N,
    season: Optional[str] = None,
) -> dict:
    params: dict[str, str | int] = {
        "limit": limit,
        "offset": 0,
        "seconds": 5,
        "abilityCount": 8,
        "build": build_id,
        "seasonal": 1 if seasonal else 0,
    }
    if season:
        params["season"] = season
    async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as client:
        res = await client.get(f"{REALMSHARK_API}/dps-leaderboard", params=params)
        res.raise_for_status()
        return res.json()


def graph_from_builds(payload: dict, *, seasonal: bool = True) -> StatScalingGraph:
    meta = payload.get("meta") or {}
    edges: list[AbilityScalingEdge] = []
    # Abilities RealmShark put on the wrong stat board | reattach after
    # every class+stat edge exists so we can land them on the right one.
    misplaced: list[tuple[str, str, str]] = []
    for raw in payload.get("builds") or []:
        class_name = _canon_class(raw.get("className") or "")
        stat = _canon_stat(raw.get("statLabel") or "") or "Attack"
        abilities = [n for n in (raw.get("abilityNames") or []) if n]
        if not class_name or not abilities:
            continue
        kept: list[str] = []
        for name in abilities:
            override = _SCALING_OVERRIDES.get(name.strip().lower())
            if override and override.lower() != stat.lower():
                misplaced.append((class_name, override, name))
                continue
            kept.append(name)
        if not kept:
            continue
        note = raw.get("note")
        if any(cls == class_name for cls, _, _ in misplaced):
            # Drop misplaced names from RealmShark's "only (...)" blurb so
            # the model never sees them as Attack (etc.) scalers.
            note = f"{raw.get('label') or f'{stat} {class_name}'} only ({', '.join(kept)})."
        edges.append(
            AbilityScalingEdge(
                class_name=class_name,
                stat=stat,
                ability_names=kept,
                build_id=raw.get("build") or "",
                label=raw.get("label") or f"{stat} {class_name}",
                note=raw.get("note"),
            )
        )

    for class_name, dest_stat, name in misplaced:
        target = next(
            (
                edge
                for edge in edges
                if edge.class_name == class_name and edge.stat.lower() == dest_stat.lower()
            ),
            None,
        )
        if target:
            if name not in target.ability_names:
                target.ability_names.append(name)
        else:
            edges.append(
                AbilityScalingEdge(
                    class_name=class_name,
                    stat=dest_stat,
                    ability_names=[name],
                    build_id=f"override-{dest_stat.lower()}-{class_name.lower()}",
                    label=f"{dest_stat} {class_name}",
                    note=(
                        f"{name} scales with {dest_stat}, not the RealmShark board "
                        f"that originally listed it."
                    ),
                )
            )

    return StatScalingGraph(
        season=meta.get("season"),
        seasonal=bool(meta.get("seasonal", seasonal)),
        source_url=REALMSHARK_PAGE,
        edges=edges,
    )


def _parse_enchants(raw: object) -> list[ItemEnchant]:
    out: list[ItemEnchant] = []
    if not isinstance(raw, list):
        return out
    for enc in raw:
        if not isinstance(enc, dict):
            continue
        name = (enc.get("enchantName") or enc.get("name") or "").strip()
        if not name:
            continue
        slot = enc.get("slot")
        try:
            slot_n = int(slot) if slot is not None else None
        except (TypeError, ValueError):
            slot_n = None
        out.append(
            ItemEnchant(
                slot=slot_n,
                name=name,
                value=str(enc.get("value") or ""),
            )
        )
    return out


def _float_or_none(raw: object) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def loadouts_from_rows(payload: dict) -> list[Loadout]:
    out: list[Loadout] = []
    for row in payload.get("rows") or []:
        slots = []
        for eq in row.get("equipment") or []:
            name = eq.get("itemName")
            slot = eq.get("slot")
            if name and slot:
                slots.append(
                    EquipmentSlot(
                        slot=slot,
                        item_name=name,
                        rarity=eq.get("rarity"),
                        enchants=_parse_enchants(eq.get("enchants")),
                    )
                )
        stats = {}
        raw_stats = row.get("stats") or {}
        for key, canon in (
            ("hp", "HP"),
            ("mp", "MP"),
            ("attack", "Attack"),
            ("defense", "Defense"),
            ("speed", "Speed"),
            ("dexterity", "Dexterity"),
            ("vitality", "Vitality"),
            ("wisdom", "Wisdom"),
        ):
            if key in raw_stats and raw_stats[key] is not None:
                stats[canon] = int(raw_stats[key])
        debug = row.get("debug") if isinstance(row.get("debug"), dict) else {}
        out.append(
            Loadout(
                rank=int(row.get("rank") or 0),
                player_name=row.get("playerName") or "unknown",
                dps=_float_or_none(row.get("dps")),
                ability_name=row.get("abilityName"),
                weapon_name=row.get("weaponName"),
                equipment=slots,
                stats=stats,
                total_damage=_float_or_none(row.get("totalDamage")),
                weapon_damage=_float_or_none(row.get("weaponDamage")),
                ability_damage=_float_or_none(row.get("abilityDamage")),
                debug=debug,
            )
        )
    return out


def format_graph(graph: StatScalingGraph, *, class_name: Optional[str] = None, stat: Optional[str] = None) -> str:
    """Render the adjacency list as prompt-ready text."""
    edges = graph.edges
    if class_name:
        edges = [e for e in edges if e.class_name.lower() == class_name.lower()]
    if stat:
        edges = [e for e in edges if e.stat.lower() == stat.lower()]

    season = graph.season or ("seasonal" if graph.seasonal else "non-seasonal")
    lines = [
        f"Ability stat-scaling graph (RealmShark DPS builds, {season}).",
        f"Source: {graph.source_url}",
        "The eight 8/8 stats are HP, MP, Attack, Defense, Speed, Dexterity, "
        "Vitality, and Wisdom. RealmShark boards below list abilities that "
        "appear on a DPS calculator for that class+stat. They are incomplete. "
        "Also use the RealmEye wiki scaling section when it is present. An "
        "ability scales if its wiki formula uses that stat (e.g. most Bard "
        "lutes do not scale with Attack; The Triangle does). Do not mention a "
        "same-slot ability as 'also' or 'alongside' unless Shark or wiki puts "
        "it on this same stat | if it scales with a different 8/8 stat, leave "
        "it off this build entirely.",
        "Skip items marked [Limited Edition] unless the user asked for a "
        "creative / LE / meme build.",
        "",
    ]
    if not edges:
        if class_name and stat:
            lines.append(
                f"RealmShark has no {stat} {class_name} DPS board. Check T7 then "
                f"ST/UT ability infoboxes on RealmEye. If no ability formula "
                f"uses {stat}, still build around {stat} armor, universal rings, "
                f"and weapons from a class that shares this weapon. Never say "
                f"the build does not exist."
            )
        else:
            lines.append("No matching scaling edges in the graph.")
        return "\n".join(lines)

    by_class: dict[str, list[AbilityScalingEdge]] = {}
    for edge in edges:
        by_class.setdefault(edge.class_name, []).append(edge)

    all_by_class: dict[str, set[str]] = {}
    for edge in graph.edges:
        all_by_class.setdefault(edge.class_name, set()).add(edge.stat)

    for cls in sorted(by_class):
        lines.append(f"{cls}:")
        for edge in by_class[cls]:
            names = ", ".join(_tag_le(n) for n in edge.ability_names)
            lines.append(f"  {edge.stat} -> {names}")
        if class_name and not stat:
            missing = [s for s in PLAYER_STATS if s not in all_by_class.get(cls, set())]
            if missing:
                lines.append(
                    "  (no RealmShark DPS board for: "
                    + ", ".join(missing)
                    + " — check RealmEye wiki scaling for those stats)"
                )
        lines.append("")
    return "\n".join(lines).strip()


def format_loadouts(build_label: str, loadouts: list[Loadout]) -> str:
    if not loadouts:
        return ""
    lines = [
        f"Top {len(loadouts)} RealmShark potential-DPS loadouts for {build_label} "
        "(5s window, 8 ability uses, full buffs; not live combat logs). "
        "Render this as a markdown table with columns Rank | Player | DPS | "
        "Weapon | Ability | Armor | Ring, using [item:Name] in equipment cells. "
        "Keep each player's actual ring, even if it is T6 Unbound — do not "
        "replace loadout rings with T7 Transcendent.",
        "",
        "| Rank | Player | DPS | Weapon | Ability | Armor | Ring |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in loadouts:
        by_slot = {s.slot.lower(): s.item_name for s in row.equipment}
        weapon = by_slot.get("weapon") or row.weapon_name or ""
        ability = by_slot.get("ability") or row.ability_name or ""
        armor = by_slot.get("armor") or ""
        ring = by_slot.get("ring") or ""
        dps = f"{row.dps:,.1f}" if row.dps is not None else ""
        cell = lambda n: f"[item:{n}]" if n else ""
        lines.append(
            f"| {row.rank} | {row.player_name} | {dps} | "
            f"{cell(weapon)} | {cell(ability)} | {cell(armor)} | {cell(ring)} |"
        )
    return "\n".join(lines)


def _sister_classes(class_name: str) -> list[str]:
    for group in WEAPON_SHARE_GROUPS:
        if class_name in group:
            return [name for name in group if name != class_name]
    return []


async def _sister_weapon_loadouts(
    redis: aioredis.Redis,
    graph: StatScalingGraph,
    class_name: str,
    stat: Optional[str],
    *,
    ttl_seconds: int,
    cache_only: bool = False,
) -> str:
    """Top-5 weapons from a class that shares this weapon type."""
    for sister in _sister_classes(class_name):
        edges = [
            edge
            for edge in graph.edges
            if edge.class_name == sister
            and (not stat or edge.stat.lower() == stat.lower())
        ]
        if not edges and stat:
            edges = [
                edge
                for edge in graph.edges
                if edge.class_name == sister and edge.stat == "Attack"
            ]
        if not edges:
            continue
        loadouts = await load_top_loadouts(
            redis,
            edges[0],
            season=graph.season,
            ttl_seconds=ttl_seconds,
            cache_only=cache_only,
        )
        formatted = format_loadouts(
            f"{edges[0].label} (same weapon type as {class_name})",
            loadouts,
        )
        if formatted:
            _hubs, label = weapon_family(class_name)
            return (
                f"Weapon hint from {sister} ({label} — the only weapons "
                f"{class_name} can use). Use their Weapon column for "
                f"high-damage {label}. Do not recommend a weapon from another "
                f"family. Rings on that table are universal. Ability and armor "
                f"are {sister}-only.\n\n{formatted}"
            )
    return ""


async def load_graph(
    redis: aioredis.Redis,
    ttl_seconds: int,
    *,
    cache_only: bool = False,
    force: bool = False,
) -> StatScalingGraph:
    if not force:
        cached = await redis.get(GRAPH_CACHE_KEY)
        if cached:
            return StatScalingGraph.model_validate_json(cached)
        if cache_only:
            return StatScalingGraph(season="", edges=[])

    payload = await fetch_builds(seasonal=True)
    graph = graph_from_builds(payload, seasonal=True)
    await redis.setex(GRAPH_CACHE_KEY, ttl_seconds, graph.model_dump_json())
    logger.bind(edges=len(graph.edges), season=graph.season).info(
        "Cached RealmShark ability-scaling graph"
    )
    return graph


async def load_top_loadouts(
    redis: aioredis.Redis,
    edge: AbilityScalingEdge,
    *,
    season: Optional[str],
    ttl_seconds: int,
    cache_only: bool = False,
    force: bool = False,
) -> list[Loadout]:
    cache_key = f"{LOADOUT_CACHE_PREFIX}:{edge.build_id}"
    if not force:
        cached = await redis.get(cache_key)
        if cached:
            graph_slice = StatScalingGraph.model_validate_json(cached)
            return graph_slice.top_loadouts.get(edge.build_id, [])
        if cache_only:
            return []

    try:
        payload = await fetch_leaderboard(
            edge.build_id, seasonal=True, limit=TOP_N, season=season
        )
    except Exception as e:
        logger.bind(build=edge.build_id, error=str(e)).warning(
            "Could not fetch RealmShark DPS leaderboard"
        )
        return []

    loadouts = loadouts_from_rows(payload)
    stub = StatScalingGraph(top_loadouts={edge.build_id: loadouts})
    await redis.setex(cache_key, ttl_seconds, stub.model_dump_json())
    return loadouts


def _loadout_slot_name(row: Loadout, slot: str) -> str:
    by_slot = {s.slot.lower(): s.item_name for s in row.equipment}
    if slot == "weapon":
        return (by_slot.get("weapon") or row.weapon_name or "").strip()
    if slot == "ability":
        return (by_slot.get("ability") or row.ability_name or "").strip()
    return (by_slot.get(slot) or "").strip()


def picks_from_loadouts(loadouts: list[Loadout]) -> dict[str, str]:
    """Majority item per slot across a RealmShark top-N board.

    Limited Edition names are skipped so a seasonal reskin cannot become
    the set-visualizer pick. An empty slot stays empty for the hub
    ranking to fill.
    """
    counts = {slot: Counter() for slot in ("weapon", "ability", "armor", "ring")}
    for row in loadouts:
        for slot in counts:
            name = _loadout_slot_name(row, slot)
            if not name or _LE_NAME.search(name):
                continue
            counts[slot][name] += 1
    return {
        slot: counter.most_common(1)[0][0]
        for slot, counter in counts.items()
        if counter
    }


async def shark_name_counts(
    redis: aioredis.Redis,
    classes: tuple[str, ...],
    slot: str,
    *,
    stat: Optional[str] = None,
    ttl_seconds: int,
) -> dict[str, int]:
    """How often each item appears on cached RealmShark top 5s.

    Cache only. A guest 'best bows' ask must not fan out live leaderboard
    scrapes. Missing boards just omit those names.
    """
    if not classes or slot not in {"weapon", "ability", "armor", "ring"}:
        return {}
    try:
        graph = await load_graph(redis, ttl_seconds, cache_only=True)
    except Exception as e:
        logger.bind(error=str(e)).warning("RealmShark graph unavailable for slot list")
        return {}
    wanted = {name.lower() for name in classes}
    want_stat = (stat or "").lower()
    counts: Counter[str] = Counter()
    for edge in graph.edges:
        if edge.class_name.lower() not in wanted:
            continue
        if want_stat and edge.stat.lower() != want_stat:
            continue
        loadouts = await load_top_loadouts(
            redis,
            edge,
            season=graph.season,
            ttl_seconds=ttl_seconds,
            cache_only=True,
        )
        for row in loadouts:
            name = _loadout_slot_name(row, slot)
            if not name or _LE_NAME.search(name):
                continue
            counts[name] += 1
    return dict(counts)


async def shark_slot_picks(
    redis: aioredis.Redis,
    class_name: str,
    stat: str,
    *,
    ttl_seconds: int,
    cache_only: bool = True,
) -> dict[str, str]:
    """Best-effort four-slot pick from the class+stat RealmShark board."""
    try:
        graph = await load_graph(redis, ttl_seconds, cache_only=True)
    except Exception as e:
        logger.bind(error=str(e)).warning("RealmShark graph unavailable for slot picks")
        return {}
    edges = [
        edge
        for edge in graph.edges
        if edge.class_name.lower() == class_name.lower()
        and edge.stat.lower() == stat.lower()
    ]
    if not edges:
        return {}
    loadouts = await load_top_loadouts(
        redis,
        edges[0],
        season=graph.season,
        ttl_seconds=ttl_seconds,
        cache_only=cache_only,
    )
    return picks_from_loadouts(loadouts)


async def retrieve_build_knowledge(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int,
    player_ttl_seconds: int = 120,
    history: Optional[list[str]] = None,
) -> str:
    """
    Structured graph slice for build/item questions. Empty string when the
    message isn't about gear or a class/stat, so we don't spend tokens.
    """
    class_name, stat, buildish = parse_query(message, history=history)
    player_ign = extract_player_ign(message, history=history)
    dungeon_name = extract_dungeon_query(message, history=history)
    portal_ask = extract_portal_source_query(message)
    if portal_ask:
        dungeon_name = dungeon_name or portal_ask
    biome_ask = extract_biome_query(message)
    hub_ask = extract_hub_query(message, history=history)
    # A breakdown or what-if turn continues the previous DPS answer. It has to
    # be resolved before the set/skin/player branches below, because those
    # match on loose wording a follow-up shares ("what if he swapped to a Doom
    # Bow?" matched the skin visualizer and never reached the DPS slot).
    dps_follow_up = is_dps_follow_up(message, history=history)
    if dps_follow_up:
        prior_ign, prior_class = dps_subject_from_history(history)
        player_ign = player_ign or prior_ign
        class_name = class_name or prior_class
    set_visualize = not dps_follow_up and (
        is_set_visualize_query(message)
        or is_stat_class_shiny_divine_query(message, class_name, stat)
    )
    skin_visualize = not dps_follow_up and is_skin_visualize_query(
        message, history=history
    )
    # "What enchants on QOT" has no class/stat/build keyword, so it isn't
    # buildish on its own | without this it would fall through the gate
    # below with no context and Claude would have to invent roll numbers.
    # Use (class_name and stat), not the raw buildish flag: buildish also
    # flips True on a bare slot noun (ring/armor/weapon/ability) with no
    # class or stat at all, and almost every enchant question names one of
    # those nouns. Found live Sep 14: "...insane with the awakened
    # enchantment?" (about a ring) had buildish=True from "ring" alone (plus
    # Ninja/Attack pulled in from history), so this skipped the enchant
    # brief entirely and fell through to the generic DPS-graph context for
    # an unrelated class/stat. Only a real class+stat pair (an actual
    # combined build+enchant ask) should still skip the enchant-only path.
    enchant_only = (
        is_enchant_query(message)
        and not (class_name and stat)
        and not dps_follow_up
    )
    numbers_only = is_stat_number_query(message, history=history)
    if (
        not buildish
        and not player_ign
        and not dungeon_name
        and not set_visualize
        and not skin_visualize
        and not enchant_only
        and not numbers_only
        and not biome_ask
        and not hub_ask
    ):
        return ""

    this_class, _this_stat, _this_build = parse_query(message)
    player_lookup_turn = bool(extract_player_ign(message)) or (
        bool(player_ign) and not this_class
    )
    # Inherited IGN from a prior lookup must not steal a new-item / patch
    # turn. Only a this-turn player ask skips Hub.
    if hub_ask and not extract_player_ign(message):
        try:
            hub_ctx = await retrieve_rotmg_hub(
                redis,
                message,
                ttl_seconds=ttl_seconds,
                cache_only=True,
                history=history,
            )
            if (hub_ctx or "").strip():
                return hub_ctx
        except Exception as e:
            logger.bind(error=str(e)).warning("RotMG Hub specialist unavailable")
        # New-item asks fall through to RealmEye when Hub has nothing.

    if biome_ask and biome_ask.survey:
        try:
            return await retrieve_biome_context(
                redis,
                message,
                ttl_seconds=ttl_seconds,
                cache_only=False,
            )
        except Exception as e:
            logger.bind(error=str(e)).warning("Biome specialist unavailable")
            return ""

    if set_visualize:
        try:
            return await run_slot_agents(
                redis,
                message,
                ttl_seconds=ttl_seconds,
                player_ttl_seconds=player_ttl_seconds,
                user_history=history,
                class_name=class_name,
                stat=stat,
                player_ign=player_ign,
                dungeon_name=dungeon_name,
            )
        except Exception as e:
            logger.bind(error=str(e)).warning("Set visualizer specialist unavailable")
            return ""

    if skin_visualize:
        try:
            return await run_slot_agents(
                redis,
                message,
                ttl_seconds=ttl_seconds,
                player_ttl_seconds=player_ttl_seconds,
                user_history=history,
                class_name=class_name,
                stat=stat,
                player_ign=player_ign,
                dungeon_name=dungeon_name,
            )
        except Exception as e:
            logger.bind(error=str(e)).warning("Skin visualizer specialist unavailable")
            return ""

    if (
        player_lookup_turn
        and not numbers_only
        and not is_dps_query(message, history=history)
    ):
        try:
            return await run_slot_agents(
                redis,
                message,
                ttl_seconds=ttl_seconds,
                player_ttl_seconds=player_ttl_seconds,
                user_history=history,
                class_name=None,
                stat=None,
                player_ign=player_ign or extract_player_ign(message),
                dungeon_name=dungeon_name if not extract_player_ign(message) else None,
            )
        except Exception as e:
            logger.bind(error=str(e), player=player_ign).warning(
                "Player lookup specialist unavailable"
            )
            return ""

    if portal_ask and not buildish:
        try:
            portal_ctx = await retrieve_portal_drop_context(
                redis,
                portal_ask,
                ttl_seconds=ttl_seconds,
                cache_only=True,
            )
            if portal_ctx:
                return portal_ctx
        except Exception as e:
            logger.bind(error=str(e), dungeon=portal_ask).warning(
                "Portal-drop context unavailable"
            )

    if dungeon_name and not buildish:
        try:
            text = await run_slot_agents(
                redis,
                message,
                ttl_seconds=ttl_seconds,
                player_ttl_seconds=player_ttl_seconds,
                user_history=history,
                class_name=class_name,
                stat=stat,
                player_ign=None,
                dungeon_name=dungeon_name,
            )
            extra = await matching_hub_excerpt(redis, [dungeon_name])
            if extra and extra not in text:
                text = f"{text}\n\n{extra}" if text else extra
            return text
        except Exception as e:
            logger.bind(
                error=str(e), player=player_ign, dungeon=dungeon_name
            ).warning("Lookup specialist unavailable")
            return ""

    if enchant_only:
        try:
            return await retrieve_enchanting_brief(
                redis,
                message,
                ttl_seconds=ttl_seconds,
                class_name=class_name,
                stat=stat,
                cache_only=True,
            )
        except Exception as e:
            logger.bind(error=str(e)).warning("Enchantment specialist unavailable")
            return ""

    if numbers_only:
        try:
            return await run_slot_agents(
                redis,
                message,
                ttl_seconds=ttl_seconds,
                player_ttl_seconds=player_ttl_seconds,
                user_history=history,
                class_name=class_name,
                stat=stat,
                player_ign=player_ign,
                dungeon_name=dungeon_name,
            )
        except Exception as e:
            logger.bind(error=str(e)).warning("DPS specialist unavailable")
            return ""

    effective_stat = stat
    inferred_note = ""
    cached_wiki = (
        await cached_class_wiki_scaling(redis, class_name) if class_name else None
    )
    if class_name and not effective_stat and cached_wiki:
        guessed = infer_class_primary_stat(cached_wiki)
        if guessed:
            effective_stat = guessed
            inferred_note = (
                f"No stat was named; {class_name}'s abilities mostly "
                f"scale with {guessed}, so the loadout and enchants below "
                f"target {guessed}."
            )

    # In-depth Claude turn: slot specialists (weapon/ability/armor/ring/
    # enchantment) plus only the extras that answer the question. Do not
    # dump the full Umi page, every wiki hub, or four Shark boards.
    try:
        slots_text = await run_slot_agents(
            redis,
            message,
            ttl_seconds=ttl_seconds,
            player_ttl_seconds=player_ttl_seconds,
            user_history=history,
            class_name=class_name,
            stat=effective_stat,
            player_ign=player_ign,
            dungeon_name=dungeon_name,
        )
    except Exception as e:
        logger.bind(error=str(e)).warning("Slot specialists unavailable")
        slots_text = ""

    rank = await resolve_source_rank(
        redis,
        class_name,
        effective_stat,
        ttl_seconds=ttl_seconds,
        cache_only=True,
    )
    extras = await _in_depth_build_extras(
        redis,
        class_name,
        effective_stat,
        ttl_seconds=ttl_seconds,
        rank=rank,
    )
    ranking = store_ranking_brief(
        class_name,
        effective_stat,
        primary_stat=rank.get("primary_stat"),
        community_full_build=bool(rank.get("community_full_build")),
        community_source=rank.get("community_source") or "",
    )
    if ranking and slots_text and ranking in slots_text:
        ranking = ""
    hub_names: list[str] = []
    if class_name:
        hub_names.append(class_name)
    if stat:
        hub_names.append(stat)
    try:
        from .wiki_scaling import top_build_items

        if class_name and stat:
            picks = await top_build_items(
                redis,
                class_name,
                stat,
                ttl_seconds=ttl_seconds,
                cache_only=True,
            )
            hub_names.extend(v for v in picks.values() if v)
    except Exception:
        pass
    hub_extra = await matching_hub_excerpt(redis, hub_names)
    parts = [p for p in (inferred_note, ranking, slots_text, *extras, hub_extra) if p]
    return "\n\n".join(parts)


async def _in_depth_build_extras(
    redis: aioredis.Redis,
    class_name: Optional[str],
    stat: Optional[str],
    *,
    ttl_seconds: int,
    rank: Optional[dict] = None,
) -> list[str]:
    """Set-visualizer four-slot picks plus one RealmShark top-5 table."""
    rank = rank or {}
    unique = bool(rank.get("unique_build"))
    community = bool(rank.get("community_full_build"))
    bits: list[str] = []
    max_stats = ""
    if unique and class_name:
        try:
            max_stats = await retrieve_class_max_stats(
                redis,
                class_name,
                ttl_seconds=ttl_seconds,
                stat=stat,
                cache_only=True,
                unique_build=True,
                community_full_build=community,
            )
        except Exception as e:
            logger.bind(error=str(e)).warning("Class max-stats unavailable")
            max_stats = ""
        if max_stats and not community:
            bits.append(max_stats)
    if class_name and stat:
        try:
            from .wiki_scaling import top_build_items

            picks = await top_build_items(
                redis,
                class_name,
                stat,
                ttl_seconds=ttl_seconds,
                cache_only=True,
            )
        except Exception as e:
            logger.bind(error=str(e)).warning("Set visualizer picks unavailable")
            picks = {}
        tokens = " ".join(
            f"[item:{picks[slot]}]" for slot in SET_SLOTS if picks.get(slot)
        )
        missing = [slot for slot in SET_SLOTS if not picks.get(slot)]
        if tokens:
            pick_note = (
                "SET VISUALIZER PICKS in weapon, ability, armor, ring order. "
                "Already ranked RealmShark majority, then overall picks. "
            )
            if unique and not community:
                pick_note += (
                    "This unique build has no RealmShark/Umi full set. "
                    "Ability, armor, and ring should follow the Maximum "
                    "Achievable Stats row above, not these tokens, unless a "
                    "token is the overall family weapon. "
                )
            if missing:
                pick_note += (
                    "Missing slots ("
                    + ", ".join(missing)
                    + "): leave them empty. Never copy a weapon into the "
                    "ability slot or fill a gap from another slot. "
                )
            bits.append(
                pick_note
                + "If the answer is a recommended loadout, copy these tokens: "
                + tokens
            )
    if class_name:
        try:
            from .wiki_scaling import retrieve_umi_bis

            umi = await retrieve_umi_bis(
                redis,
                class_name,
                ttl_seconds=ttl_seconds,
                cache_only=True,
                stat=stat,
            )
        except Exception as e:
            logger.bind(error=str(e), class_name=class_name).warning(
                "Umi BIS alternatives unavailable"
            )
            umi = ""
        umi = umi or rank.get("umi_text") or ""
        alt_note = slot_alternatives_note(
            class_name,
            stat,
            unique_build=unique,
            community_full_build=community,
        )
        bits.append(f"{alt_note}\n{umi}" if umi else alt_note)
    try:
        graph = await load_graph(redis, ttl_seconds, cache_only=True)
    except Exception as e:
        logger.bind(error=str(e)).warning("RealmShark graph unavailable")
        if unique and community and max_stats:
            bits.append(max_stats)
        return bits
    if not class_name:
        if unique and community and max_stats:
            bits.append(max_stats)
        return bits
    matched = [
        edge
        for edge in graph.edges
        if edge.class_name.lower() == class_name.lower()
        and (not stat or edge.stat.lower() == stat.lower())
    ]
    if matched:
        loadouts = await load_top_loadouts(
            redis,
            matched[0],
            season=graph.season,
            ttl_seconds=ttl_seconds,
            cache_only=True,
        )
        formatted = format_loadouts(matched[0].label, loadouts)
        if formatted:
            bits.append(formatted)
        if unique and community and max_stats:
            bits.append(max_stats)
        return bits
    if stat:
        sister = await _sister_weapon_loadouts(
            redis,
            graph,
            class_name,
            stat,
            ttl_seconds=ttl_seconds,
            cache_only=True,
        )
        if sister:
            bits.append(sister)
    if unique and community and max_stats:
        bits.append(max_stats)
    return bits
