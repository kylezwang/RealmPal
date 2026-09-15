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

import asyncio
import re
from typing import Optional

import httpx
import redis.asyncio as aioredis
from loguru import logger

from ..models.build import (
    CLASS_ALIASES,
    CLASS_ARMOR_HUB,
    PLAYER_STATS,
    STAT_ALIASES,
    WEAPON_SHARE_GROUPS,
    weapon_family,
    AbilityScalingEdge,
    EquipmentSlot,
    Loadout,
    StatScalingGraph,
)
from .dungeon_guide import extract_dungeon_query
from .enchanting import is_enchant_query, retrieve_enchanting_brief
from .item_aliases import is_set_visualize_query, is_stat_class_shiny_divine_query
from .skin_visualizer import is_skin_visualize_query
from .player_lookup import extract_player_ign
from .slot_graph import run_slot_agents
from .wiki_scaling import (
    HUB_PREFIX,
    cached_class_wiki_scaling,
    format_wiki_scaling,
    infer_class_primary_stat,
    retrieve_armor_brief,
    retrieve_umi_bis,
)

REALMSHARK_API = "https://tracker.realmshark.cc/api/v1"
REALMSHARK_PAGE = "https://tracker.realmshark.cc/dps-leaderboards"
GRAPH_CACHE_KEY = "dps:graph:seasonal:v2"
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


def _parse_query_text(text: str) -> tuple[Optional[str], Optional[str], bool]:
    lower = text.lower()
    classes: list[str] = []
    for canon, aliases in CLASS_ALIASES.items():
        needles = (canon.lower(),) + aliases
        if any(re.search(rf"\b{re.escape(n)}\b", lower) for n in needles):
            classes.append(canon)
    class_name = classes[0] if len(classes) == 1 else None

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


def _has_own_topic(message: str) -> bool:
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
        or is_skin_visualize_query(message)
        or is_set_visualize_query(message)
        or extract_dungeon_query(message)
        or extract_player_ign(message)
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
    if history and not _has_own_topic(message):
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


def loadouts_from_rows(payload: dict) -> list[Loadout]:
    out: list[Loadout] = []
    for row in payload.get("rows") or []:
        slots = []
        for eq in row.get("equipment") or []:
            name = eq.get("itemName")
            slot = eq.get("slot")
            if name and slot:
                slots.append(
                    EquipmentSlot(slot=slot, item_name=name, rarity=eq.get("rarity"))
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
        out.append(
            Loadout(
                rank=int(row.get("rank") or 0),
                player_name=row.get("playerName") or "unknown",
                dps=row.get("dps"),
                ability_name=row.get("abilityName"),
                weapon_name=row.get("weaponName"),
                equipment=slots,
                stats=stats,
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
    cache_key = f"dps:top:{edge.build_id}"
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
    set_visualize = is_set_visualize_query(message) or is_stat_class_shiny_divine_query(
        message, class_name, stat
    )
    skin_visualize = is_skin_visualize_query(message)
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
    enchant_only = is_enchant_query(message) and not (class_name and stat)
    if (
        not buildish
        and not player_ign
        and not dungeon_name
        and not set_visualize
        and not skin_visualize
        and not enchant_only
    ):
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

    this_class, _this_stat, _this_build = parse_query(message)
    player_lookup_turn = bool(extract_player_ign(message)) or (
        bool(player_ign) and not this_class
    )
    if player_lookup_turn:
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

    if dungeon_name and not buildish:
        try:
            return await run_slot_agents(
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

    parts: list[str] = []
    has_board = False
    try:
        graph = await load_graph(redis, ttl_seconds, cache_only=True)
        parts.append(format_graph(graph, class_name=class_name, stat=stat))
        matched = graph.edges
        if class_name:
            matched = [e for e in matched if e.class_name.lower() == class_name.lower()]
        if stat:
            matched = [e for e in matched if e.stat.lower() == stat.lower()]
        has_board = bool(matched)
        if class_name:
            _hubs, wep_label = weapon_family(class_name)
            if wep_label:
                parts.append(
                    f"{class_name} can only use {wep_label}. Never recommend "
                    f"a weapon from another family (no wand on Mystic, no "
                    f"staff on Priest, no bow on Wizard)."
                )
            for edge in matched[:4]:
                loadouts = await load_top_loadouts(
                    redis,
                    edge,
                    season=graph.season,
                    ttl_seconds=ttl_seconds,
                    cache_only=True,
                )
                formatted = format_loadouts(edge.label, loadouts)
                if formatted:
                    parts.append(formatted)
            if not matched:
                sister = await _sister_weapon_loadouts(
                    redis,
                    graph,
                    class_name,
                    stat,
                    ttl_seconds=ttl_seconds,
                    cache_only=True,
                )
                if sister:
                    parts.append(sister)
    except Exception as e:
        logger.bind(error=str(e)).warning("RealmShark builds catalog unavailable")

    # Specialists read the stored wiki corpus. Chat must not launch a
    # RealmEye crawl — that is refresh_wiki.py (once a week).
    cached_wiki = (
        await cached_class_wiki_scaling(redis, class_name) if class_name else None
    )
    if cached_wiki:
        text = format_wiki_scaling(cached_wiki, stat=stat)
        if text:
            parts.append("ABILITY AGENT — stored wiki scaling.\n" + text)
        armor_slug = CLASS_ARMOR_HUB.get(class_name or "")
        if class_name and stat and armor_slug and await redis.get(
            f"{HUB_PREFIX}:{armor_slug}"
        ):
            armor = await retrieve_armor_brief(
                redis,
                class_name,
                stat,
                ttl_seconds=ttl_seconds,
                limit=5,
                brief=False,
                cache_only=True,
            )
            if armor:
                parts.append(armor)
        umi_key = f"umi:bis:v1:{(class_name or '').lower()}"
        if class_name and await redis.get(umi_key):
            umi = await retrieve_umi_bis(
                redis, class_name, ttl_seconds=ttl_seconds, cache_only=True
            )
            if umi:
                parts.append(umi)
    elif class_name:
        logger.bind(class_name=class_name).info(
            "No stored wiki scaling yet; answering from DPS boards"
        )

    # A full "best {stat} {class}" build covers Weapon/Ability/Armor/Ring
    # above; Enchantments is the fifth slot. Same RealmEye roll table as
    # the enchant-only branch, filtered to this stat so a Wisdom build
    # doesn't get handed Attack-flat rolls. No stat named ("best kensei
    # build")? Most DPS builds chase whichever stat the class's own
    # abilities scale with | infer that the same way a single-item ask
    # infers from the item's own On Equip bonus, instead of dropping
    # Enchantments from the build entirely.
    effective_stat = stat
    stat_inferred = False
    if class_name and not effective_stat and cached_wiki:
        effective_stat = infer_class_primary_stat(cached_wiki)
        stat_inferred = bool(effective_stat)
    if class_name and effective_stat:
        try:
            enchant_brief = await retrieve_enchanting_brief(
                redis,
                message,
                ttl_seconds=ttl_seconds,
                class_name=class_name,
                stat=effective_stat,
                cache_only=True,
            )
            if enchant_brief:
                if stat_inferred:
                    enchant_brief = (
                        f"No stat was named; {class_name}'s abilities mostly "
                        f"scale with {effective_stat}, so enchants below "
                        f"target {effective_stat}.\n{enchant_brief}"
                    )
                parts.append(enchant_brief)
        except Exception as e:
            logger.bind(error=str(e), class_name=class_name).warning(
                "Enchantment specialist unavailable for build"
            )

    return "\n\n".join(parts)
