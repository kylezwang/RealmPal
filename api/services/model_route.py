"""Pick Sonnet vs Haiku for a Claude turn.

Stored answers already skip the model. When Claude still has to write, use
Haiku if the wiki/RAG store already has the facts and the ask is not a
constrained or first-time build. Sonnet stays on the heavy cases.
"""
from __future__ import annotations

from typing import Optional

import re

from ..config import Settings
from .item_aliases import is_set_visualize_query
from .realmshark import parse_query
from .skin_visualizer import is_skin_visualize_query
from .stored_answers import is_constrained

_HEAVY_REASONING = re.compile(
    r"\b("
    r"compare|versus|\bvs\.?\b|which\s+is\s+better|should\s+i|"
    r"enchant|forge|reroll|optimize|theory|"
    r"why\s+(?:is|does|do)|explain\s+how"
    r")\b",
    re.I,
)
_BUILD_ASK = re.compile(
    r"\b(best items?|build|loadout|gear|equip|dps)\b",
    re.I,
)
_STRONG_CONTEXT_CHARS = 400


def pick_chat_model(
    message: str,
    settings: Settings,
    *,
    history: Optional[list[str]] = None,
    context: str = "",
    dungeon_only: bool = False,
    player_only: bool = False,
    has_attachment: bool = False,
) -> str:
    """Sonnet by default. Haiku when the store is doing the heavy lifting."""
    sonnet = settings.claude_model
    haiku = settings.claude_light_model or sonnet
    if has_attachment or is_constrained(message):
        return sonnet
    class_name, stat, buildish = parse_query(message, history=history)
    if buildish and class_name and stat:
        return sonnet
    if buildish and stat and _BUILD_ASK.search(message or ""):
        return sonnet
    if _HEAVY_REASONING.search(message or ""):
        return sonnet
    if (
        dungeon_only
        or player_only
        or is_skin_visualize_query(message, history=history)
        or is_set_visualize_query(message)
    ):
        return haiku
    if context and len(context) >= _STRONG_CONTEXT_CHARS:
        return haiku
    return sonnet
