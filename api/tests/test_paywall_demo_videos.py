"""Paywall demo MP4s must be mobile-playable on Azure Static Web Apps."""

from __future__ import annotations

import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAYWALL_VIDEOS = ROOT / "web" / "public" / "videos" / "paywall"
SWA_CONFIG = ROOT / "web" / "public" / "staticwebapp.config.json"
PAYWALL_MODAL = ROOT / "web" / "components" / "chat" / "PaywallModal.tsx"
DEMO_FILES = ("set-building-demo.mp4", "visualizer.mp4")


def _top_level_boxes(path: Path) -> list[str]:
    size = path.stat().st_size
    types: list[str] = []
    with path.open("rb") as handle:
        offset = 0
        while offset + 8 <= size:
            handle.seek(offset)
            header = handle.read(8)
            box_size, raw_type = struct.unpack(">I4s", header)
            box_type = raw_type.decode("latin1")
            header_size = 8
            if box_size == 1:
                box_size = struct.unpack(">Q", handle.read(8))[0]
                header_size = 16
            elif box_size == 0:
                box_size = size - offset
            if box_size < header_size:
                break
            types.append(box_type)
            offset += box_size
    return types


def test_static_web_app_serves_mp4_as_video():
    config = json.loads(SWA_CONFIG.read_text(encoding="utf-8"))
    assert config["mimeTypes"][".mp4"] == "video/mp4"


def test_paywall_mp4s_are_faststart():
    for name in DEMO_FILES:
        path = PAYWALL_VIDEOS / name
        assert path.is_file(), name
        types = _top_level_boxes(path)
        assert "moov" in types and "mdat" in types, types
        assert types.index("moov") < types.index("mdat"), types


def test_paywall_player_declares_mp4_type():
    source = PAYWALL_MODAL.read_text(encoding="utf-8")
    assert 'type="video/mp4"' in source
    assert "src={src}" in source
    assert "playsInline" in source
    assert "autoPlay" in source
    assert 'preload="metadata"' in source
    assert 'aria-label={`Play ${label}`}' in source


def test_static_web_app_video_route_sets_mp4_type():
    config = json.loads(SWA_CONFIG.read_text(encoding="utf-8"))
    video_route = next(r for r in config["routes"] if r["route"] == "/videos/*")
    assert video_route["headers"]["Content-Type"] == "video/mp4"
