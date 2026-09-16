"""
Crop one cell out of a RealmEye (or Umi) sprite sheet.

The browser cannot do this itself: RealmEye sends no CORS headers, so a
canvas draw taints and `toDataURL` fails. The tab icon therefore asks the
API for a standalone PNG.
"""
from __future__ import annotations

from io import BytesIO
from urllib.parse import urlparse

import httpx
from PIL import Image

ALLOWED_SPRITE_HOSTS = frozenset(
    {
        "www.realmeye.com",
        "realmeye.com",
        "static.realmeye.com",
        "www.umienjoyers.com",
        "umienjoyers.com",
    }
)

MAX_SHEET_BYTES = 8 * 1024 * 1024
MIN_CROP = 1
MAX_CROP = 256
ICON_SIZE = 64


class SpriteCropError(ValueError):
    """Invalid URL, crop, or sheet payload."""


def assert_allowed_sheet_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SpriteCropError("unsupported sprite url")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_SPRITE_HOSTS:
        raise SpriteCropError("sprite host not allowed")


def crop_sheet_bytes(content: bytes, x: int, y: int, size: int) -> bytes:
    if size < MIN_CROP or size > MAX_CROP or x < 0 or y < 0:
        raise SpriteCropError("invalid crop")
    if len(content) > MAX_SHEET_BYTES:
        raise SpriteCropError("sheet too large")
    try:
        img = Image.open(BytesIO(content)).convert("RGBA")
    except Exception as e:
        raise SpriteCropError("unreadable sprite sheet") from e
    width, height = img.size
    if x + size > width or y + size > height:
        raise SpriteCropError("crop out of bounds")
    cell = img.crop((x, y, x + size, y + size))
    icon = cell.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.NEAREST)
    buf = BytesIO()
    icon.save(buf, format="PNG")
    return buf.getvalue()


async def fetch_and_crop_sprite(sheet_url: str, x: int, y: int, size: int) -> bytes:
    assert_allowed_sheet_url(sheet_url)
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        response = await client.get(
            sheet_url,
            headers={"User-Agent": "RealmPal/1.0 (sprite crop)"},
        )
        response.raise_for_status()
        return crop_sheet_bytes(response.content, x, y, size)
