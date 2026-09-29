"""LangGraph slot specialists for builds, player lookups, and dungeon guides.

Weapon, Ability, Armor, and Ring each read only their RealmEye pages so
an Attack Archer question cannot pick up Magic-ring MP numbers. A full
"best build" fans out to all four plus Enchantment and asks for a
balanced loadout. A rings-only follow-up runs just the Ring agent. An
enchant-only follow-up reads RealmEye /wiki/enchanting tables (and Umi
BIS notes when a class is known). A DPS-only question uses wiki item
shot data plus RealmShark as a reference board. A named shiny/divine set
runs the Set visualizer, which expands nicknames (QOT, Vest, Lean) to
wiki titles. A skin/outfit dye preview runs the Skin visualizer, which
composites the base sprite with clothing and accessory dyes. A player lookup
runs the Player agent. A dungeon guide question runs the Dungeon agent, which
scrapes the RealmEye wiki walkthrough itself.
"""
from __future__ import annotations

import operator
import re
from typing import Annotated, Any, Literal, Optional, TypedDict

import redis.asyncio as aioredis
from loguru import logger

from .community_knowledge import store_ranking_brief
from .chunks import wrap_slot_chunk
from .dps_specialist import (
    dps_subject_from_history,
    is_dps_follow_up,
    is_dps_query,
    is_stat_number_query,
    retrieve_dps_brief,
)
from .dungeon_guide import extract_dungeon_query, retrieve_dungeon_guide
from .enchanting import is_enchant_query, retrieve_enchanting_brief
from .forging import (
    SOURCE_URL as FORGE_SOURCE_URL,
    _enchant_signal_besides_orb,
    is_forge_query,
    retrieve_forging_brief,
)
from .item_aliases import (
    extract_mentioned_items,
    is_set_visualize_query,
    is_stat_class_shiny_divine_query,
    retrieve_set_visualizer,
)
from .skin_visualizer import is_skin_visualize_query, retrieve_skin_visualizer
from .player_lookup import extract_player_ign, format_player_brief, get_or_scrape_player
from .wiki_scaling import (
    retrieve_ability_brief,
    retrieve_armor_brief,
    retrieve_universal_rings,
    retrieve_weapon_brief,
    resolve_source_rank,
)

SlotName = Literal[
    "weapon",
    "ability",
    "armor",
    "ring",
    "enchantment",
    "forge",
    "dps",
    "set",
    "skin",
    "player",
    "dungeon",
]
Depth = Literal["brief", "deep"]
_GEAR_SLOTS = ("weapon", "ability", "armor", "ring")


class SlotState(TypedDict, total=False):
    message: str
    user_history: list[str]
    class_name: Optional[str]
    stat: Optional[str]
    player_ign: Optional[str]
    dungeon_name: Optional[str]
    unique_build: bool
    community_full_build: bool
    community_source: str
    primary_stat: Optional[str]
    slots: list[str]
    depth: Depth
    ttl_seconds: int
    player_ttl_seconds: int
    reports: Annotated[list[str], operator.add]
    combined: str


def route_slots(
    message: str,
    class_name: Optional[str],
    stat: Optional[str],
    player_ign: Optional[str] = None,
    dungeon_name: Optional[str] = None,
    history: Optional[list[str]] = None,
) -> tuple[list[SlotName], Depth]:
    """Full builds use every gear slot. Named-slot follow-ups stay narrow.
    A named shiny/divine set uses the set visualizer instead of the four
    gear agents - so does a shiny/divine class+stat ask with no items
    named ("full shiny divine attack huntress"), which resolves the top
    weapon/ability/armor/ring for that build first (see
    is_stat_class_shiny_divine_query / top_build_items), same visual
    output either way. A skin/outfit dye preview uses the skin visualizer.
    A player lookup adds the player specialist. A guide question adds
    dungeon."""
    lower = message.lower()
    # A breakdown or what-if turn continues the previous DPS answer, so it must
    # be settled before the set/skin branches: they match on wording a
    # follow-up shares, and "what if he swapped to a Doom Bow?" was landing on
    # the skin visualizer with the DPS reconstruct nowhere in the context.
    dps_follow_up = is_dps_follow_up(message, history=history)
    if not dps_follow_up and (
        is_set_visualize_query(message)
        or is_stat_class_shiny_divine_query(message, class_name, stat)
    ):
        extras: list[SlotName] = []
        if player_ign:
            extras.append("player")
        if dungeon_name:
            extras.append("dungeon")
        return ["set", *extras], "deep"
    if not dps_follow_up and is_skin_visualize_query(message, history=history):
        extras: list[SlotName] = []
        if player_ign:
            extras.append("player")
        if dungeon_name:
            extras.append("dungeon")
        return ["skin", *extras], "deep"

    forge_buildish = bool(
        re.search(r"\b(build|loadout|gear|equip|best items?)\b", lower)
        or (class_name and stat)
    )
    if is_forge_query(message) and not forge_buildish and not dps_follow_up:
        forge_slots: list[SlotName] = ["forge"]
        if _enchant_signal_besides_orb(message):
            forge_slots.append("enchantment")
        extras: list[SlotName] = []
        if player_ign:
            extras.append("player")
        if dungeon_name:
            extras.append("dungeon")
        return [*forge_slots, *extras], "deep"

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

    # A what-if names the swapped-in piece ("a Doom Bow" -> weapon), and that
    # slot's wiki page is what lets the reconstruct be rescaled, so keep it
    # alongside dps rather than letting it displace dps.
    if dps_follow_up:
        return ["dps", *named], "deep"

    enchant_only = is_enchant_query(message)
    dps_only = is_dps_query(message, history=history)
    numbers_only = is_stat_number_query(message, history=history)
    buildish = bool(
        re.search(r"\b(build|loadout|gear|equip|best items?)\b", lower)
        or (class_name and stat and not named)
    )
    slots: list[SlotName] = []
    depth: Depth = "brief"
    if numbers_only and not named:
        slots = ["dps"]
        if enchant_only:
            slots.append("enchantment")
        depth = "deep"
    elif enchant_only and not buildish and not named:
        slots = ["enchantment"]
        if len(extract_mentioned_items(message)) >= 2:
            slots.append("dps")
        depth = "deep"
    elif dps_only and not buildish and not named:
        slots = ["dps"]
        depth = "deep"
    elif buildish or (class_name and stat and len(named) != 1):
        slots = ["weapon", "ability", "armor", "ring", "enchantment"]
        if dps_only:
            slots.append("dps")
        depth = "brief"
    elif named:
        slots = list(named)
        if enchant_only:
            slots.append("enchantment")
        if dps_only:
            slots.append("dps")
        depth = "deep"
    elif class_name or stat:
        slots = ["weapon", "ability", "armor", "ring", "enchantment"]
        if dps_only:
            slots.append("dps")
        depth = "brief"

    extras: list[SlotName] = []
    dps_owns_player = "dps" in slots and (numbers_only or (dps_only and not buildish))
    if player_ign and not dps_owns_player:
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
        state["message"],
        class_name,
        stat,
        player_ign,
        dungeon_name,
        history=state.get("user_history"),
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
    player_ttl_seconds: int = 120,
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
        "unique_build": False,
        "community_full_build": False,
        "community_source": "",
        "primary_stat": None,
        "ttl_seconds": ttl_seconds,
        "player_ttl_seconds": player_ttl_seconds,
        "reports": [],
        "combined": "",
    }
    if class_name and stat:
        try:
            rank = await resolve_source_rank(
                redis,
                class_name,
                stat,
                ttl_seconds=ttl_seconds,
                cache_only=True,
            )
            seed["unique_build"] = bool(rank.get("unique_build"))
            seed["community_full_build"] = bool(rank.get("community_full_build"))
            seed["community_source"] = rank.get("community_source") or ""
            seed["primary_stat"] = rank.get("primary_stat")
        except Exception as e:
            logger.bind(error=str(e)).warning("Source rank flags unavailable")
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
                wrap_slot_chunk(
                    "set",
                    await _set_agent(redis, state),
                    source="https://www.realmeye.com",
                )
            ]
        }

    async def skin_visualizer(state: SlotState) -> dict:
        return {
            "reports": [
                wrap_slot_chunk("skin", await _skin_agent(redis, state))
            ]
        }

    async def enchantment(state: SlotState) -> dict:
        return {
            "reports": [
                wrap_slot_chunk("enchantment", await _enchantment_agent(redis, state))
            ]
        }

    async def forge(state: SlotState) -> dict:
        return {
            "reports": [
                wrap_slot_chunk(
                    "forge",
                    await _forge_agent(redis, state),
                    source=FORGE_SOURCE_URL,
                )
            ]
        }

    async def dps(state: SlotState) -> dict:
        return {
            "reports": [wrap_slot_chunk("dps", await _dps_agent(redis, state))]
        }

    def synthesize(state: SlotState) -> dict:
        return {"combined": _join_reports(state)}

    graph = StateGraph(SlotState)
    graph.add_node("intent", _intent)
    graph.add_node("weapon", weapon)
    graph.add_node("ability", ability)
    graph.add_node("armor", armor)
    graph.add_node("ring", ring)
    graph.add_node("enchantment", enchantment)
    graph.add_node("forge", forge)
    graph.add_node("dps", dps)
    graph.add_node("player", player)
    graph.add_node("dungeon", dungeon)
    graph.add_node("set", set_visualizer)
    graph.add_node("skin", skin_visualizer)
    graph.add_node("synthesize", synthesize)
    graph.add_edge(START, "intent")
    graph.add_conditional_edges("intent", _fan_out)
    for slot in (
        "weapon",
        "ability",
        "armor",
        "ring",
        "enchantment",
        "forge",
        "dps",
        "set",
        "skin",
        "player",
        "dungeon",
    ):
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
        "enchantment": _enchantment_agent,
        "forge": _forge_agent,
        "dps": _dps_agent,
    }
    texts = []
    for slot in state.get("slots") or []:
        runner = runners.get(slot)
        if runner:
            body = await runner(redis, state)
            if slot == "forge":
                texts.append(
                    wrap_slot_chunk(slot, body, source=FORGE_SOURCE_URL)
                )
            else:
                texts.append(wrap_slot_chunk(slot, body))
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
    if "set" in slots and not any(slot in slots for slot in _GEAR_SLOTS):
        header = (
            "SET VISUALIZER. Copy the [loadout ...] flags and [item:Wiki Title] "
            "tokens from the set chunk in order (weapon, ability, armor, ring). "
            "Those titles are already expanded from nicknames (QOT, Vest, Lean, "
            "Crown). Use each item's listed kind in prose (a bow is not a sword). "
            "Cite the RealmEye wiki URLs from the set chunk. Do not cite "
            "RealmShark. Short confirmation only. Do not substitute other items."
        )
    elif "skin" in slots and not any(
        slot in slots for slot in (*_GEAR_SLOTS, "set")
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
            "exactly - each fact on its own markdown list line starting with "
            "'- ' (Fame, Guild, Total exaltations, Top pet, Last seen) - "
            "then ## Sources. Do not squash them onto one line. Do not list "
            "characters and do not write a Class/Fame/Weapon/Ability/Armor/"
            "Ring table. The UI already renders the scraped character cards."
        )
    elif slots == ["enchantment"] or (
        depth == "deep" and slots == ["enchantment"]
    ):
        header = (
            "ENCHANTMENT FOLLOW-UP. Stay on rolls and eligible slots from "
            "the enchantment chunk. Copy I/II/III/IV and unique values "
            "exactly. RealmEye is truth; Umi notes are supplementary. "
            "Do not invent a roll that is not in the chunk."
        )
    elif "forge" in slots and "enchantment" not in slots:
        header = (
            "FORGE FOLLOW-UP. Copy forge rules from the forge chunk only. "
            "Cite RealmEye /wiki/forge. Forging is not enchanting. "
            "Do not cite /wiki/enchanting or enchant roll rarity."
        )
    elif slots == ["dps"] or (depth == "deep" and slots == ["dps"]):
        header = (
            "DPS FOLLOW-UP. RealmShark potential-DPS numbers in the chunk "
            "are the source of truth (5s window, 8 ability uses, 0 DEF, "
            "full buffs, on-character enchants already applied). Copy DPS, "
            "the weapon/ability split, and the listed stats. Do not invent "
            "a different number. Do not recommend a set unless the user "
            "asked for gear. Wiki Damage/Shots/Rate of Fire are formula "
            "inputs. If the chunk scales a RealmShark weapon or ability "
            "number after a swap, copy that scaled number and say it is "
            "estimated from the board row, not a new leaderboard entry. "
            "Ability scaling uses the wiki formula and Stat Mod Multiplier "
            "on the scaling stat. A breakdown must name weapon, ability, armor, "
            "and ring. Armor and ring On Equip stats and On Ability procs "
            "change those stats; do not ignore Vesture's On Ability Attack "
            "proc. APS is (1.5 + 6.5 × DEX/75) × item fire rate, not "
            "DEX × RoF / 8. An 8/8-stat tradeoff is a sheet change, not a "
            "fire-rate enchant; it still counts when the ability formula or "
            "working Attack/Dexterity uses that stat."
        )
    elif "dungeon" in slots and not any(slot in slots for slot in _GEAR_SLOTS):
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
            "all 8 monuments until the Idol is dead. After the purple dome on "
            "the clear to Nox, drag all 4 branches/flames to the center - "
            "never call those wings (that is regular The Shatters). Cite every "
            "Source URL in the chunk."
        )
    elif depth == "brief":
        unique = bool(state.get("unique_build"))
        community = bool(state.get("community_full_build"))
        if unique and not community:
            header = (
                f"UNIQUE LOADOUT ({stat} {class_name}). Ability, armor, and "
                "ring stack the highest "
                f"{stat} from the RealmEye Maximum Achievable Stats row. "
                "Weapon may use the overall family base. Do not use general "
                "robe or leather cores. After the recommended set, SLOT "
                "ALTERNATIVES from a matching Umi tab if one exists. Never "
                "list a T7 robe or armor as an alternative."
            )
        elif unique:
            header = (
                f"UNIQUE LOADOUT ({stat} {class_name}). A RealmShark top 5 "
                "or matching Umi tab already has this full set. Copy that "
                "community loadout. Overall family cores are general "
                "gameplay only. After that, SLOT ALTERNATIVES from Umi. "
                "Never list a T7 robe or armor as an alternative."
            )
        else:
            header = (
                f"BALANCED LOADOUT ({stat} {class_name}). Lead with the SET "
                "VISUALIZER PICKS tokens (weapon, ability, armor, ring) as the "
                "recommended loadout, then the single RealmShark top-5 table "
                "if it is in context. After that, SLOT ALTERNATIVES for every "
                "slot that has extras, taken only from the UmiEnjoyers "
                "general-tab chunk. Never list a T7 robe or armor as an "
                "alternative. Use slot chunks only for a short why and "
                "for overall / Umi / wiki disagreements. Do not recap every "
                "source or list five rings. Enchant rolls come from the "
                "enchantment chunk only."
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
        "must be copied from the chunk - do not recall values from memory or "
        "from RealmShark loadouts. Limited Edition clones (Amulet of "
        "Superior/Exalted/Unbound ...) are filtered out on purpose; never "
        "reintroduce them."
    )
    ranking = ""
    real_class = state.get("class_name")
    real_stat = state.get("stat")
    gearish = any(slot in slots for slot in (*_GEAR_SLOTS, "enchantment"))
    if real_class and real_stat and gearish:
        ranking = store_ranking_brief(
            real_class,
            real_stat,
            primary_stat=state.get("primary_stat"),
            community_full_build=bool(state.get("community_full_build")),
            community_source=state.get("community_source") or "",
        )
    if ranking:
        return header + "\n\n" + ranking + "\n\n" + "\n\n".join(reports)
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
        cache_only=True,
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
        cache_only=True,
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
        cache_only=True,
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
        cache_only=True,
    )


async def _player_agent(redis: aioredis.Redis, state: SlotState) -> str:
    username = state.get("player_ign")
    if not username:
        return ""
    try:
        profile = await get_or_scrape_player(
            redis,
            username,
            ttl_seconds=int(state.get("player_ttl_seconds") or 120),
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
            redis,
            dungeon_name,
            ttl_seconds=state["ttl_seconds"],
            cache_only=True,
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
            stat=state.get("stat"),
            allow_scrape=False,
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


async def _enchantment_agent(redis: aioredis.Redis, state: SlotState) -> str:
    try:
        return await retrieve_enchanting_brief(
            redis,
            state["message"],
            ttl_seconds=state["ttl_seconds"],
            class_name=state.get("class_name"),
            stat=state.get("stat"),
            cache_only=True,
        )
    except Exception as e:
        logger.bind(error=str(e)).warning("Enchantment specialist unavailable")
        return ""


async def _forge_agent(redis: aioredis.Redis, state: SlotState) -> str:
    try:
        return await retrieve_forging_brief(
            redis,
            state["message"],
            ttl_seconds=state["ttl_seconds"],
            cache_only=True,
        )
    except Exception as e:
        logger.bind(error=str(e)).warning("Forge specialist unavailable")
        return ""


async def _dps_agent(redis: aioredis.Redis, state: SlotState) -> str:
    history = list(state.get("user_history") or [])
    ign = state.get("player_ign")
    class_name = state.get("class_name")
    # A breakdown or what-if names neither the player nor the class, so recover
    # what the conversation's last DPS turn was about. Without this the slot
    # answers with a class-ceiling board and no worn set, which reads to the
    # model as "I have no numbers" right after it gave the user real ones.
    if is_dps_follow_up(state["message"], history=history):
        prior_ign, prior_class = dps_subject_from_history(history)
        ign = ign or prior_ign
        class_name = class_name or prior_class
    try:
        return await retrieve_dps_brief(
            redis,
            state["message"],
            ttl_seconds=state["ttl_seconds"],
            class_name=class_name,
            stat=state.get("stat"),
            player_ign=ign,
            player_ttl_seconds=int(state.get("player_ttl_seconds") or 120),
            cache_only=True,
        )
    except Exception as e:
        logger.bind(error=str(e)).warning("DPS specialist unavailable")
        return ""

