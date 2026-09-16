"""parse_query: class/stat history inheritance and when it must not fire.

Follow-ups like "what other rings" legitimately continue an earlier build
conversation with no class/stat of their own, so parse_query inherits from
history for them. But a message can also lack its own class/stat while
asking about something else entirely (an enchant question, a dungeon guide,
a player lookup, a skin/set visualization) - inheriting a stale class/stat
into one of those is a distinct bug class from the enchant-specific
regression covered in test_stored_answers.py.
"""
from __future__ import annotations

from api.services.realmshark import parse_query


def test_thin_build_followup_still_inherits_class_and_stat():
    """The legitimate case this inheritance exists for: no class/stat of its
    own, no competing specialist topic, so it should still glue onto the
    prior turn's build context."""
    history = ["Best attack ninja build"]
    class_name, stat, buildish = parse_query("what other rings are good", history=history)
    assert class_name == "Ninja"
    assert stat == "Attack"
    assert buildish is True


def test_enchant_question_does_not_inherit_stale_class_and_stat():
    """Regression: found live Sep 14 - "Shiny divine snake eye ring. Is it
    insane with the awakened enchantment?" has no class/stat of its own,
    but "ring" alone flips the weak half of the buildish regex True, which
    used to be enough to glue in Ninja/Attack from several turns back."""
    history = [
        "Best attack ninja build",
        "Would this be the bis attack ninja then?",
    ]
    class_name, stat, buildish = parse_query(
        "Shiny divine snake eye ring. Is it insane with the awakened enchantment?",
        history=history,
    )
    assert class_name is None
    assert stat is None


def test_dungeon_guide_followup_does_not_inherit_stale_class_and_stat():
    history = ["Best wis mystic build"]
    class_name, stat, _buildish = parse_query(
        "how to do moonlight village", history=history
    )
    assert class_name is None
    assert stat is None


def test_player_lookup_does_not_inherit_stale_class_and_stat():
    history = ["Best wis mystic build"]
    class_name, stat, _buildish = parse_query(
        "look up player Turbine", history=history
    )
    assert class_name is None
    assert stat is None


def test_message_with_its_own_class_and_stat_ignores_history_entirely():
    """Baseline: a message that already fully specifies its own class/stat
    was never affected by inheritance and must not regress."""
    history = ["Best wis mystic build"]
    class_name, stat, buildish = parse_query("Best attack ninja build", history=history)
    assert class_name == "Ninja"
    assert stat == "Attack"
    assert buildish is True


def test_one_letter_class_typo_still_resolves():
    """Closed-vocab: brd is unique 1-edit from Bard. Slot nouns stay exact."""
    class_name, stat, buildish = parse_query("best att brd")
    assert class_name == "Bard"
    assert stat == "Attack"
    assert buildish is True
    class_name, _stat, _buildish = parse_query("best spell wizard")
    assert class_name == "Wizard"
    class_name, _stat, _buildish = parse_query("what about spel")
    assert class_name is None
