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


# Ordinary English words a player types without meaning any game term. A
# real typo is almost always a non-word ("brd", "atack", "dext"), so refusing
# to 1-edit-correct a word that already exists in English is the cheap way to
# keep conversational filler out of the game vocabulary. Found live Sep 17:
# "What do the numbers look like?" mapped "like" onto the HP alias "life", so
# a plain follow-up question arrived at the build path carrying stat=HP.
# Exact aliases are matched before this guard, so a stat legitimately spelled
# "life" or "health" and a class spelled "knight" still resolve. Game nouns
# (life, health, speed, attack, set, hit, ring, gem, bow) are deliberately
# absent from this list even though they are English words.
_ENGLISH_FILLER = frozenset(
    """
    about after again all also always and another any are ask asked away
    back bad because been before being best better between both but came can
    cant come could did does doing done dont down each else even ever every
    few find first for from get gets give given goes going gone good got
    great had has have help her here hers high him his how however its just
    keep kind know known last late later least less let lets like liked
    likes little long look looks lot love made make makes many may maybe
    mean means might more most much must near need needs never new next nice
    not now off often old once one only open other our ours out over own
    part place put quite rather read real really right said same saw say says
    see seem seen should show shows side since small some soon sort still
    stop such sure take tell than thanks that the their them then there these
    they thing things think this those though three through time times too
    try two under until upon use used uses using very want wants was way we
    well went were what when where which while who whole why will with work
    works worse worst would yes yet you your yours
    """.split()
)


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
    min_len characters long, skipping tokens that are ordinary English words
    (see _ENGLISH_FILLER). Two aliases of different canons at the same
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
    if needle in _ENGLISH_FILLER:
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
