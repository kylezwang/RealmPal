"""LangChain chunking for slot-agent context.

Each specialist writes a small, labeled chunk so Attack rings cannot
pick up Limited Edition amulets or Magic-ring MP numbers from another
slot's text.
"""
from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

SLOT_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=900,
    chunk_overlap=80,
    separators=["\n\n", "\n| ", "\n", ". ", " "],
)

GUIDE_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=100,
    separators=["\n\n", "\n", ". ", " "],
)


def split_guide(text: str) -> list[str]:
    parts = [p.strip() for p in GUIDE_SPLITTER.split_text(text or "") if p.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


def wrap_slot_chunk(slot: str, body: str, *, source: str = "") -> str:
    """Isolate one specialist's findings. Empty body is dropped."""
    text = (body or "").strip()
    if not text:
        return ""
    # A split markdown table loses its header row, which is how ring rows
    # ended up detached from their stat column. Player summaries must stay
    # one list so Fame/Guild cannot collapse onto a single line.
    has_table = "| --- |" in text
    keep_whole = has_table or slot in {"player", "set", "skin"}
    parts = (
        SLOT_SPLITTER.split_text(text)
        if len(text) > 1100 and not keep_whole
        else [text]
    )
    blocks = []
    total = len(parts)
    src = f' source="{source}"' if source else ""
    for i, part in enumerate(parts, start=1):
        blocks.append(
            f'<slot_chunk slot="{slot}" part="{i}/{total}"{src}>\n'
            f"{part.strip()}\n"
            f"</slot_chunk>"
        )
    return "\n".join(blocks)
