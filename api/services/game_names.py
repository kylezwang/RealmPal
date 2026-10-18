"""Wiki name list for Jev. Built from Redis, never from a live scrape.

Chat reads one key. The weekly refresh and the startup warm rewrite it
after the wiki caches are already filled. A miss means unknown, not player.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from loguru import logger

from ..models.build import CLASS_ALIASES

GAME_NAMES_KEY = "wiki:game-names:v1"

# Ability nouns in CLASS_ALIASES are items, not class nicknames.
_ABILITY_NOUNS = frozenset(
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
        "mace",
        "sheath",
        "sigil",
        "lute",
    }
)
_CLASS_NICKS = frozenset(
    {"wiz", "pally", "necro", "sorc", "myst", "trix", "summ", "rog", "arch"}
)
# A single token alias for these would mark ordinary sentences as game terms.
_ALIAS_STOP = frozenset(
    {
        "the",
        "and",
        "of",
        "from",
        "with",
        "for",
        "mad",
        "god",
        "goddess",
        "king",
        "queen",
        "lord",
        "lady",
        "lost",
        "ancient",
        "great",
        "dark",
        "shadow",
        "stone",
        "white",
        "black",
        "red",
        "blue",
        "new",
        "old",
        "into",
        "over",
        "under",
        "staff",
        "staves",
        "staffs",
        "wand",
        "wands",
        "sword",
        "swords",
        "bow",
        "bows",
        "dagger",
        "daggers",
        "katana",
        "katanas",
        "weapon",
        "weapons",
        "ring",
        "rings",
        "armor",
        "armour",
        "ability",
        "abilities",
        "robe",
        "robes",
        "leather",
        "leathers",
        "heavy",
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
        "mace",
        "sheath",
        "sigil",
        "lute",
        "cloak",
        "quiver",
    }
)
_SKIP_KEYS = frozenset({"a", "an", "the", "of", "and", "or", "to", "my", "i"})

_MEM: dict = {"raw": None, "index": {}}


def _norm(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", (name or "").lower()))


def _put(index: dict, key: str, *, name: str, kind: str, where: str) -> None:
    norm = _norm(key)
    if len(norm) < 2 or norm in _SKIP_KEYS or norm in index:
        return
    index[norm] = {"name": name, "kind": kind, "where": where or ""}


def _add_aliases(index: dict) -> None:
    """Point a rare word at the one game entry that uses it.

    'thessal' finds Thessal the Mermaid Goddess. 'king' and 'staff' do not
    become terms, and a word shared by more than three entries is skipped.
    """
    owners: dict[str, list[str]] = {}
    for key in list(index):
        for word in re.findall(r"[a-z0-9]+", key):
            if len(word) < 4 or word in _ALIAS_STOP:
                continue
            owners.setdefault(word, []).append(key)
    for word, keys in owners.items():
        if word in index:
            continue
        uniq = list(dict.fromkeys(keys))
        if len(uniq) > 3:
            continue
        chosen = uniq[0]
        for key in uniq:
            if index[key]["kind"] == "boss":
                chosen = key
                break
        index[word] = dict(index[chosen])


def compile_index(
    *,
    classes: list[tuple[str, tuple[str, ...]]] | None = None,
    dungeons: list[dict] | None = None,
    bosses: list[dict] | None = None,
    items: list[str] | None = None,
) -> dict:
    """Pure builder. First writer wins: class, then dungeon, then boss, then item."""
    index: dict = {}
    for canon, aliases in classes or []:
        _put(index, canon, name=canon, kind="class", where="")
        for alias in aliases:
            token = (alias or "").strip().lower()
            if token in _ABILITY_NOUNS:
                continue
            plural = token.endswith("s") and token[:-1] == canon.lower()
            if token == canon.lower() or plural or token in _CLASS_NICKS:
                _put(index, token, name=canon, kind="class", where="")
    for row in dungeons or []:
        title = (row.get("title") or "").strip()
        if not title:
            continue
        _put(index, title, name=title, kind="dungeon", where="")
        for alias in row.get("aliases") or []:
            _put(index, str(alias), name=title, kind="dungeon", where="")
    for row in bosses or []:
        name = (row.get("name") or "").strip()
        if name:
            _put(index, name, name=name, kind="boss", where=row.get("where") or "")
    for name in items or []:
        cleaned = (name or "").strip()
        if cleaned and _norm(cleaned) not in _ALIAS_STOP:
            _put(index, cleaned, name=cleaned, kind="item", where="")
    _add_aliases(index)
    return index


def match_terms(message: str, index: dict, *, limit: int = 6) -> list[dict]:
    """Longest wiki names in this sentence. Overlapping shorter hits are dropped."""
    if not index or not (message or "").strip():
        return []
    words = re.findall(r"[a-z0-9']+", message.lower())
    found: list[tuple[int, int, dict, str]] = []
    upper = min(6, len(words))
    for size in range(upper, 0, -1):
        for start in range(0, len(words) - size + 1):
            phrase = " ".join(words[start : start + size])
            entry = index.get(phrase)
            if entry:
                found.append((start, start + size, entry, phrase))
    found.sort(key=lambda row: (row[0] - row[1], row[0]))
    occupied: set[int] = set()
    seen: set[tuple[str, str]] = set()
    hits: list[dict] = []
    for start, end, entry, phrase in found:
        span = set(range(start, end))
        if span & occupied:
            continue
        identity = (entry.get("kind") or "", entry.get("name") or "")
        if identity in seen:
            occupied |= span
            continue
        seen.add(identity)
        occupied |= span
        hit = dict(entry)
        hit["matched"] = phrase
        hits.append(hit)
        if len(hits) >= limit:
            break
    return hits


def format_known_terms(hits: list[dict]) -> str:
    parts: list[str] = []
    for hit in hits[:6]:
        name = hit.get("name") or ""
        kind = hit.get("kind") or ""
        if not name or not kind:
            continue
        where = hit.get("where") or ""
        if where:
            parts.append(f"{name} ({kind}, {where})")
        else:
            parts.append(f"{name} ({kind})")
    return "; ".join(parts)


async def load_game_names(redis) -> dict:
    if redis is None:
        return {}
    try:
        raw = await redis.get(GAME_NAMES_KEY)
    except Exception:
        return {}
    if not raw:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode()
    if raw == _MEM["raw"]:
        return _MEM["index"]
    try:
        index = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(index, dict):
        return {}
    _MEM["raw"] = raw
    _MEM["index"] = index
    return index


async def has_game_names(redis) -> bool:
    if redis is None:
        return False
    try:
        return bool(await redis.exists(GAME_NAMES_KEY))
    except Exception:
        return False


async def lookup_term(redis, name: str) -> Optional[dict]:
    index = await load_game_names(redis)
    if not index:
        return None
    hit = index.get(_norm(name))
    return dict(hit) if hit else None


async def match_message_terms(redis, message: str, *, limit: int = 6) -> list[dict]:
    index = await load_game_names(redis)
    if not index:
        return []
    return match_terms(message, index, limit=limit)


async def rebuild_game_names(redis) -> dict:
    """Rewrite the list from cached hubs, dungeon pages, and class names.

    Cache only. A scrape belongs in the weekly warm, before this runs.
    """
    from .dungeon_guide import (
        PAGE_CACHE_PREFIX,
        _split_drop_sources,
        get_or_scrape_index,
    )
    from .wiki_scaling import HUB_PREFIX

    dungeons: list[dict] = []
    try:
        dungeons = await get_or_scrape_index(
            redis, ttl_seconds=86400, cache_only=True
        )
    except Exception as exc:
        logger.bind(error=type(exc).__name__).warning("Game name dungeon index skipped")
        dungeons = []

    bosses: list[dict] = []
    seen_boss: set[str] = set()
    try:
        async for raw_key in redis.scan_iter(match=f"{PAGE_CACHE_PREFIX}*", count=200):
            raw = await redis.get(raw_key)
            if not raw:
                continue
            try:
                page = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(page, dict):
                continue
            where = (page.get("title") or "").strip()
            if where:
                dungeons.append({"title": where, "aliases": []})
            for row in page.get("drops") or []:
                if not isinstance(row, dict):
                    continue
                for source in _split_drop_sources(row.get("drops_from") or ""):
                    key = source.lower()
                    if key in seen_boss:
                        continue
                    seen_boss.add(key)
                    bosses.append({"name": source, "where": where})
    except Exception as exc:
        logger.bind(error=type(exc).__name__).warning("Game name dungeon pages skipped")

    items: list[str] = []
    seen_item: set[str] = set()
    try:
        async for raw_key in redis.scan_iter(match=f"{HUB_PREFIX}:*", count=100):
            raw = await redis.get(raw_key)
            if not raw:
                continue
            try:
                rows = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(rows, dict):
                rows = rows.get("items") or rows.get("rows") or []
            if not isinstance(rows, list):
                continue
            for row in rows:
                name = ""
                if isinstance(row, dict):
                    name = (row.get("name") or "").strip()
                elif isinstance(row, str):
                    name = row.strip()
                key = name.lower()
                if not name or key in seen_item:
                    continue
                seen_item.add(key)
                items.append(name)
    except Exception as exc:
        logger.bind(error=type(exc).__name__).warning("Game name item hubs skipped")

    index = compile_index(
        classes=list(CLASS_ALIASES.items()),
        dungeons=dungeons,
        bosses=bosses,
        items=items,
    )
    payload = json.dumps(index, sort_keys=True, separators=(",", ":"))
    await redis.set(GAME_NAMES_KEY, payload)
    _MEM["raw"] = payload
    _MEM["index"] = index
    unique = {(entry["kind"], entry["name"]) for entry in index.values()}
    counts: dict[str, int] = {"keys": len(index), "names": len(unique)}
    for kind, _name in unique:
        counts[kind] = counts.get(kind, 0) + 1
    logger.bind(**counts).info("Game name list rewritten")
    return counts
