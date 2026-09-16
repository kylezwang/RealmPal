"""Tiny closed-vocab typo matching. No extra dependency.

Item titles, class names, dungeon names, and chat nicknames all use this
same 1-edit rule. Open-ended fuzzy search against the whole item catalog
is still gated to 4+ letter words in score_nickname; this module is for
small lists (19 classes, 8 stats, nickname keys) where a 3-letter typo
like "brd" -> Bard is unique and worth taking.
"""
from __future__ import annotations

from typing import Iterable, Optional


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def fuzzy_word_match(query_word: str, name_word: str) -> bool:
    """One-letter typo on a 4+ letter word (catalog item titles)."""
    if len(query_word) < 4 or len(name_word) < 4:
        return False
    if abs(len(query_word) - len(name_word)) > 1:
        return False
    max_edits = 1 if max(len(query_word), len(name_word)) <= 7 else 2
    return levenshtein(query_word, name_word) <= max_edits


def fuzzy_closed_vocab(
    token: str,
    pairs: Iterable[tuple[str, str]],
    *,
    min_len: int = 3,
) -> Optional[str]:
    """Map a token onto a small alias table.

    Exact match wins. Otherwise a unique 1-edit hit on an alias at least
    min_len characters long. Two aliases of different canons at the same
    distance is a miss (def vs dex is not a problem because those are
    exact keys; fuzzy only runs when nothing matched exactly).
    """
    needle = (token or "").strip().lower()
    if not needle:
        return None
    table = [(alias.lower(), canon) for alias, canon in pairs if alias]
    exact = [canon for alias, canon in table if alias == needle]
    uniq = set(exact)
    if len(uniq) == 1:
        return next(iter(uniq))
    if len(uniq) > 1:
        return None
    if len(needle) < min_len:
        return None
    hits: list[str] = []
    for alias, canon in table:
        if abs(len(alias) - len(needle)) > 1:
            continue
        if len(alias) < min_len:
            continue
        if levenshtein(needle, alias) <= 1:
            hits.append(canon)
    uniq = set(hits)
    return next(iter(uniq)) if len(uniq) == 1 else None
