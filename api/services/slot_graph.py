"""LangGraph slot specialists for builds, player lookups, and dungeon guides.

Weapon, Ability, Armor, and Ring each read only their RealmEye pages so
an Attack Archer question cannot pick up Magic-ring MP numbers. A full
"best build" fans out to all four and asks for a balanced loadout. A
rings-only follow-up runs just the Ring agent. A named shiny/divine set
runs the Set visualizer, which expands nicknames (QOT, Vest, Lean) to
wiki titles. A skin/outfit dye preview runs the Skin visualizer, which
composites the base sprite with clothing and accessory dyes. A player lookup
runs the Player agent. A dungeon guide question runs the Dungeon agent, which
scrapes the RealmEye wiki walkthrough itself.

Backlog: Enchantment specialist for item enchant rolls / bonuses. Do not
add a slot for it until we have a dedicated RealmEye enchant scrape.
"""
from __future__ import annotations

import operator
import re
from typing import Annotated, Any, Literal, Optional, TypedDict

import redis.asyncio as aioredis
from loguru import logger

from .chunks import wrap_slot_chunk
from .dungeon_guide import extract_dungeon_query, retrieve_dungeon_guide
from .item_aliases import is_set_visualize_query, retrieve_set_visualizer
from .skin_visualizer import is_skin_visualize_query, retrieve_skin_visualizer
from .player_lookup import extract_player_ign, format_player_brief, get_or_scrape_player
from .wiki_scaling import (
    retrieve_ability_brief,
    retrieve_armor_brief,
    retrieve_universal_rings,
    retrieve_weapon_brief,
)

SlotName = Literal["weapon", "ability", "armor", "ring", "set", "skin", "player", "dungeon"]
Depth = Literal["brief", "deep"]

# Planned, not implemented: an "enchantment" SlotName that would read
# RealmEye enchant tables the same way Ring reads ring hubs.


class SlotState(TypedDict, total=False):
    message: str
    user_history: list[str]
    class_name: Optional[str]
    stat: Optional[str]
    player_ign: Optional[str]
    dungeon_name: Optional[str]
    slots: list[str]
    depth: Depth
    ttl_seconds: int
    reports: Annotated[list[str], operator.add]
    combined: str


def route_slots(
    message: str,
    class_name: Optional[str],
    stat: Optional[str],
    player_ign: Optional[str] = None,
    dungeon_name: Optional[str] = None,
) -> tuple[list[SlotName], Depth]:
    """Full builds use every gear slot. Named-slot follow-ups stay narrow.
    A named shiny/divine set uses the set visualizer instead of the four
    gear agents. A skin/outfit dye preview uses the skin visualizer. A
    player lookup adds the player specialist. A guide question adds dungeon."""
    lower = message.lower()
    if is_set_visualize_query(message):
        extras: list[SlotName] = []
        if player_ign:
            extras.append("player")
        if dungeon_name:
            extras.append("dungeon")
        return ["set", *extras], "deep"
    if is_skin_visualize_query(message):
        extras: list[SlotName] = []
        if player_ign:
            extras.append("player")
        if dungeon_name:
            extras.append("dungeon")
        return ["skin", *extras], "deep"

    named: list[SlotName] = []
    if re.search(r"\b(rings?|amulet|bracer|scarf|mask)\b", lower):
        named.append("ring")
    if re.search(r"\b(armou?r|robe|leather|heavy)\b", lower):
        named.append("armor")
    if re.search(r"\b(weapons?|bows?|daggers?|staves|staff|wands?|swords?|katanas?)\b", lower):
        named.append("weapon")
    if re.search(
        r"\b(abilit(?:y|ies)|quiver|lute|cloak|spell|tome|helm|shield|seal|"
        r"poison|skull|trap|orb|prism|scepter|star|wakizashi|mace|sheath|sigil)\b",
        lower,
    ):
        named.append("ability")

    buildish = bool(
        re.search(r"\b(build|loadout|gear|equip|best items?)\b", lower)
        or (class_name and stat and not named)
    )
    slots: list[SlotName] = []
    depth: Depth = "brief"
    if buildish or (class_name and stat and len(named) != 1):
        slots = ["weapon", "ability", "armor", "ring"]
        depth = "brief"
    elif named:
        slots = list(named)
        depth = "deep"
    elif class_name or stat:
        slots = ["weapon", "ability", "armor", "ring"]
        depth = "brief"

    extras: list[SlotName] = []
    if player_ign:
        extras.append("player")
    if dungeon_name:
        extras.append("dungeon")
    if extras and not slots:
        return extras, "deep"
    if extras:
        slots = [*slots, *extras]
    return slots, depth


def _intent(state: SlotState) -> dict:
    class_name = state.get("class_name")
    stat = state.get("stat")
    player_ign = state.get("player_ign") or extract_player_ign(
        state["message"], state.get("user_history")
    )
    dungeon_name = state.get("dungeon_name") or extract_dungeon_query(
        state["message"], state.get("user_history")
    )
    slots, depth = route_slots(
        state["message"], class_name, stat, player_ign, dungeon_name
    )
    return {
        "class_name": class_name,
        "stat": stat,
        "player_ign": player_ign,
        "dungeon_name": dungeon_name,
        "slots": list(slots),
        "depth": depth,
        "reports": [],
    }


def _fan_out(state: SlotState) -> list[Any]:
    from langgraph.types import Send

    return [Send(slot, state) for slot in state.get("slots") or []]


async def run_slot_agents(
    redis: aioredis.Redis,
    message: str,
    *,
    ttl_seconds: int,
    user_history: Optional[list[str]] = None,
    class_name: Optional[str] = None,
    stat: Optional[str] = None,
    player_ign: Optional[str] = None,
    dungeon_name: Optional[str] = None,
) -> str:
    """Run the slot graph; fall back to the same specialists without LangGraph."""
    seed: SlotState = {
        "message": message,
        "user_history": list(user_history or []),
        "class_name": class_name,
        "stat": stat,
        "player_ign": player_ign,
        "dungeon_name": dungeon_name,
        "ttl_seconds": ttl_seconds,
        "reports": [],
        "combined": "",
    }
    try:
        graph = _compile_graph(redis)
        result = await graph.ainvoke(seed)
        return (result or {}).get("combined") or ""
    except Exception as e:
        logger.bind(error=str(e)).warning(
            "LangGraph slot workflow unavailable; running specialists directly"
        )
        return await _run_specialists(redis, seed)


def _compile_graph(redis: aioredis.Redis):
    from langgraph.graph import END, START, StateGraph

    async def weapon(state: SlotState) -> dict:
        return {"reports": [wrap_slot_chunk("weapon", await _weapon_agent(redis, state))]}

    async def ability(state: SlotState) -> dict:
        return {"reports": [wrap_slot_chunk("ability", await _ability_agent(redis, state))]}

    async def armor(state: SlotState) -> dict:
        return {"reports": [wrap_slot_chunk("armor", await _armor_agent(redis, state))]}

    async def ring(state: SlotState) -> dict:
        return {"reports": [wrap_slot_chunk("ring", await _ring_agent(redis, state))]}

    async def player(state: SlotState) -> dict:
        ign = state.get("player_ign") or ""
        return {
            "reports": [
                wrap_slot_chunk(
                    "player",
                    await _player_agent(redis, state),
                    source=f"https://www.realmeye.com/player/{ign}" if ign else "",
                )
            ]
        }

    async def dungeon(state: SlotState) -> dict:
        return {
            "reports": [
                wrap_slot_chunk("dungeon", await _dungeon_agent(redis, state))
            ]
        }

    async def set_visualizer(state: SlotState) -> dict:
        return {
            "reports": [
                wrap_slot_chunk("set", await _set_agent(redis, state))
            ]
        }

    async def skin_visualizer(state: SlotState) -> dict:
        return {
            "reports": [
                wrap_slot_chunk("skin", await _skin_agent(redis, state))
            ]
        }

    def synthesize(state: SlotState) -> dict:
        return {"combined": _join_reports(state)}

    graph = StateGraph(SlotState)
    graph.add_node("intent", _intent)
    graph.add_node("weapon", weapon)
    graph.add_node("ability", ability)
    graph.add_node("armor", armor)
    graph.add_node("ring", ring)
    graph.add_node("player", player)
    graph.add_node("dungeon", dungeon)
    graph.add_node("set", set_visualizer)
    graph.add_node("skin", skin_visualizer)
    graph.add_node("synthesize", synthesize)
    graph.add_edge(START, "intent")
    graph.add_conditional_edges("intent", _fan_out)
    for slot in ("weapon", "ability", "armor", "ring", "set", "skin", "player", "dungeon"):
        graph.add_edge(slot, "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


async def _run_specialists(redis: aioredis.Redis, seed: SlotState) -> str:
    updates = _intent(seed)
    state: SlotState = {**seed, **updates}
    runners = {
        "weapon": _weapon_agent,
        "ability": _ability_agent,
        "armor": _armor_agent,
        "ring": _ring_agent,
        "player": _player_agent,
        "dungeon": _dungeon_agent,
        "set": _set_agent,
        "skin": _skin_agent,
    }
    texts = []
    for slot in state.get("slots") or []:
        runner = runners.get(slot)
        if runner:
            texts.append(wrap_slot_chunk(slot, await runner(redis, state)))
    state["reports"] = [t for t in texts if t]
    return _join_reports(state)


def _join_reports(state: SlotState) -> str:
    reports = [r for r in (state.get("reports") or []) if r]
    if not reports:
        return ""
    depth = state.get("depth") or "brief"
    class_name = state.get("class_name") or "this class"
    stat = state.get("stat") or "the requested stat"
    slots = state.get("slots") or []
    if "set" in slots and not any(
        slot in slots for slot in ("weapon", "ability", "armor", "ring")
    ):
        header = (
            "SET VISUALIZER. Copy the [loadout ...] flags and [item:Wiki Title] "
            "tokens from the set chunk in order (weapon, ability, armor, ring). "
            "Those titles are already expanded from nicknames (QOT, Vest, Lean). "
            "Short confirmation only. Do not substitute other items."
        )
    elif "skin" in slots and not any(
        slot in slots for slot in ("weapon", "ability", "armor", "ring", "set")
    ):
        header = (
            "SKIN VISUALIZER. Copy the [skin:Class|Skin Name|Clothing|Accessory] "
            "token from the skin chunk exactly. Short confirmation of the class, "
            "skin, clothing dye/cloth, and accessory dye/cloth. Do not emit "
            "[item:] tokens for dyes. The UI composites the portrait."
        )
    elif slots == ["player"] or (depth == "deep" and slots == ["player"]):
        header = (
            "PLAYER LOOKUP. Copy the summary bullets from the player chunk "
            "exactly — each fact on its own markdown list line starting with "
            "'- ' (Fame, Guild, Total exaltations, Top pet, Last seen) — "
            "then ## Sources. Do not squash them onto one line. Do not list "
            "characters and do not write a Class/Fame/Weapon/Ability/Armor/"
            "Ring table. The UI already renders the scraped character cards."
        )
    elif "dungeon" in slots and not any(
        slot in slots for slot in ("weapon", "ability", "armor", "ring")
    ):
        header = (
            "DUNGEON GUIDE. Walk the user through the route from the dungeon "
            "chunk. Open with a level-1 heading such as # Moonlight Village "
            "Guide. Use ## headings for Route, Bosses, Kitsune Umi, Example "
            "Layout, and Sources. The UI already lists Drops of Interest with "
            "each item's source | do not write that section. Copy shrine/NPC quiz "
            "answers exactly when they appear | those unlock secret bosses "
            "(e.g. Kitsune Umi). Copy mechanics from the chunk only | do not "
            "invent phases, skips, or loot. Include the provided markdown "
            "images for layouts. Do not [item:] potions; Marks are fine. "
            "Hardmode Shatters bosses are Valen the Unbreakable, then Nox the "
            "Wild Shadow, then King Azamoth and The Shattered Queen. Before "
            "Valen, kill the Stone Idol via the Void Phantasm; do not break "
            "all 8 monuments until the Idol is dead. Cite every "
            "Source URL in the chunk."
        )
    elif depth == "brief":
        header = (
            f"BALANCED LOADOUT ({stat} {class_name}). Cover Weapon, Ability, "
            "Armor, and Ring in similar depth — 2-3 alternatives each. Do not "
            "open with a rings-only table or list five rings. Rings are one "
            "slot, same weight as the others."
        )
    else:
        header = (
            f"SLOT FOLLOW-UP ({stat} {class_name}). The user asked about a "
            "specific slot. Stay on that slot. T7 rings are Transcendent. "
            "Only RealmShark loadout rows and player equipment may show a "
            "lower-tier ring that was actually worn."
        )
    header += (
        " Each <slot_chunk> is isolated context for that slot only. "
        "Do not mention an item that does not appear inside its slot chunk, "
        "and never move an item between slots. Every stat number you print "
        "must be copied from the chunk — do not recall values from memory or "
        "from RealmShark loadouts. Limited Edition clones (Amulet of "
        "Superior/Exalted/Unbound ...) are filtered out on purpose; never "
        "reintroduce them."
    )
    return header + "\n\n" + "\n\n".join(reports)


async def _weapon_agent(redis: aioredis.Redis, state: SlotState) -> str:
    class_name = state.get("class_name")
    if not class_name:
        return ""
    brief = state.get("depth") != "deep"
    text = await retrieve_weapon_brief(
        redis,
        class_name,
        state.get("stat"),
        ttl_seconds=state["ttl_seconds"],
        limit=3 if brief else 5,
        brief=brief,
    )
    return wrap_slot_chunk("weapon", text, source="realmeye-weapons")


async def _ability_agent(redis: aioredis.Redis, state: SlotState) -> str:
    class_name = state.get("class_name")
    if not class_name:
        return ""
    brief = state.get("depth") != "deep"
    return await retrieve_ability_brief(
        redis,
        class_name,
        stat=state.get("stat"),
        ttl_seconds=state["ttl_seconds"],
        brief=brief,
    )


async def _armor_agent(redis: aioredis.Redis, state: SlotState) -> str:
    class_name = state.get("class_name")
    stat = state.get("stat")
    if not class_name or not stat:
        return ""
    brief = state.get("depth") != "deep"
    return await retrieve_armor_brief(
        redis,
        class_name,
        stat,
        ttl_seconds=state["ttl_seconds"],
        limit=3 if brief else 5,
        brief=brief,
    )


async def _ring_agent(redis: aioredis.Redis, state: SlotState) -> str:
    stat = state.get("stat")
    if not stat:
        return ""
    brief = state.get("depth") != "deep"
    return await retrieve_universal_rings(
        redis,
        stat,
        ttl_seconds=state["ttl_seconds"],
        limit=3 if brief else 5,
        brief=brief,
    )


async def _player_agent(redis: aioredis.Redis, state: SlotState) -> str:
    username = state.get("player_ign")
    if not username:
        return ""
    try:
        profile = await get_or_scrape_player(
            redis, username, ttl_seconds=state["ttl_seconds"]
        )
    except Exception as e:
        logger.bind(username=username, error=str(e)).warning(
            "Player lookup specialist could not load a profile"
        )
        return ""
    return format_player_brief(profile)


async def _dungeon_agent(redis: aioredis.Redis, state: SlotState) -> str:
    dungeon_name = state.get("dungeon_name")
    if not dungeon_name:
        return ""
    try:
        return await retrieve_dungeon_guide(
            redis, dungeon_name, ttl_seconds=state["ttl_seconds"]
        )
    except Exception as e:
        logger.bind(dungeon=dungeon_name, error=str(e)).warning(
            "Dungeon guide specialist could not load a wiki page"
        )
        return ""


async def _set_agent(redis: aioredis.Redis, state: SlotState) -> str:
    try:
        return await retrieve_set_visualizer(
            redis,
            state["message"],
            ttl_seconds=state["ttl_seconds"],
            class_name=state.get("class_name"),
        )
    except Exception as e:
        logger.bind(error=str(e)).warning("Set visualizer specialist unavailable")
        return ""


async def _skin_agent(redis: aioredis.Redis, state: SlotState) -> str:
    try:
        return await retrieve_skin_visualizer(
            redis,
            state["message"],
            ttl_seconds=state["ttl_seconds"],
            class_name=state.get("class_name"),
            history=state.get("user_history"),
        )
    except Exception as e:
        logger.bind(error=str(e)).warning("Skin visualizer specialist unavailable")
        return ""

