"""Fail if a tracked text file contains an emoji, an em dash, or an en dash.

RealmEye title strippers may keep U+2013 and U+2014 inside the character
class that matches scraped wiki titles. Every other line must not.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# BMP symbols that are emoji in this repo's sense. Check marks and
# multiplication signs used as UI glyphs (U+2713, U+2715) are not included.
_EMOJI_BMP = {
    0x20E3,  # combining enclosing keycap
    0x23F3,  # hourglass
    0x2694,  # crossed swords
    0x2705,  # white heavy check mark
    0x2728,  # sparkles
    0x274C,  # cross mark
    0xFE0F,  # variation selector-16
}

_SKIP_SUFFIXES = {
    ".mp4",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
}


def _is_emoji(codepoint: int) -> bool:
    if 0x1F300 <= codepoint <= 0x1FAFF:
        return True
    return codepoint in _EMOJI_BMP


def _wiki_title_line(line: str) -> bool:
    return "[-" in line and "RotMG Wiki" in line


def _tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings: list[str] = []
    for rel in _tracked_files(root):
        path = root / rel
        if path.suffix.lower() in _SKIP_SUFFIXES or not path.is_file():
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            allow_dashes = _wiki_title_line(line)
            for column, char in enumerate(line, start=1):
                codepoint = ord(char)
                if _is_emoji(codepoint):
                    findings.append(
                        f"{rel}:{lineno}:{column}: emoji U+{codepoint:04X}"
                    )
                elif not allow_dashes and codepoint in (0x2014, 0x2013):
                    name = "em dash" if codepoint == 0x2014 else "en dash"
                    findings.append(
                        f"{rel}:{lineno}:{column}: {name} U+{codepoint:04X}"
                    )
    if findings:
        print("\n".join(findings))
        print(f"{len(findings)} text hygiene finding(s)", file=sys.stderr)
        return 1
    print("text hygiene ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
