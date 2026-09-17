"""Sprite TLDR farm cards for a few ultra-rare drops.

Chat emits `[farm:ogmur]` or `[farm:scythe]`. The web client paints a
sprite panel (swaps, prohibition marks, short labels) instead of a
screenshot. Keep the prose short; the card is the answer.
"""
from __future__ import annotations

import re
from typing import Optional

GUIDES = {
    "ogmur": {
        "aliases": (
            "ogmur",
            "shield of ogmur",
            "shield ogmur",
        ),
        "text": (
            "[farm:ogmur]\n"
            "**Shield of Ogmur** is a cosmically rare Armor Break shield.\n\n"
            "Main farm: **Lord of the Lost Lands** in Runic Tundra. Stun as the "
            "last protection crystal breaks so he does not spawn extra "
            "Guardians. Do not waste the fight chasing Knights and Guardians. "
            "They respawn. If you already have Ogmur or Crystallised Fang's "
            "Venom, Armor Break makes the Lord much faster.\n\n"
            "Also drops from Skeletal Centipede and Bilgewater's Galleon, or "
            "50 Ancient Schematics at the Tinkerer.\n\n"
            "[item:Shield of Ogmur]\n"
            "[item:Crystallised Fang's Venom]"
        ),
    },
    "scythe": {
        "aliases": (
            "scythe",
            "jailer's scythe",
            "jailers scythe",
            "jailer scythe",
        ),
        "text": (
            "[farm:scythe]\n"
            "**Jailer's Scythe** drops from the **Spectral Jailer**, a rare "
            "Veteran biome spawn with no quest marker. Clear Floral Escape, "
            "Carboniferous, Sanguine Forest, Runic Tundra, or Deep Sea Abyss "
            "with a crowd-clear class. If the biome is empty, hop to the next "
            "one. After the kill, check under the Spectral Penitentiary "
            "portal. The bag hides there.\n\n"
            "Skeletal Centipede in Sanguine Forest is the easier guaranteed "
            "dungeon source.\n\n"
            "[item:Jailer's Scythe]"
        ),
    },
}

_FARMISH = re.compile(
    r"\b(farm|farming|how\s+(?:do\s+i|to)\s+(?:get|find|farm|kill)|"
    r"where\s+(?:can|do)\s+i\s+(?:get|find|farm)|"
    r"where\s+(?:does|do)\s+\w[\w' ]{0,40}\s+drop)\b",
    re.I,
)


def extract_farm_guide(message: str) -> Optional[str]:
    text = re.sub(r"['’]", "", (message or "").strip().lower())
    if not text or not _FARMISH.search(text):
        return None
    hits: list[tuple[int, str]] = []
    for guide_id, spec in GUIDES.items():
        for alias in spec["aliases"]:
            if re.search(rf"\b{re.escape(alias)}\b", text):
                hits.append((len(alias), guide_id))
    if not hits:
        return None
    hits.sort(reverse=True)
    return hits[0][1]


def farm_reply_text(guide_id: str) -> Optional[str]:
    spec = GUIDES.get(guide_id)
    return None if spec is None else str(spec["text"])
