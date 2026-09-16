from io import BytesIO
from unittest.mock import patch

import httpx
import pytest
from PIL import Image

from api.config import get_settings
from api.dependencies import get_redis
from api.main import create_app
from api.services.sprite_crop import (
    SpriteCropError,
    assert_allowed_sheet_url,
    crop_sheet_bytes,
)

CALLER = ("198.51.100.7", 44321)


def _sheet_png(width: int = 80, height: int = 80) -> bytes:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for px in range(16):
        for py in range(16):
            img.putpixel((40 + px, 40 + py), (255, 80, 20, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_realmeye_sheet_host_is_allowed():
    assert_allowed_sheet_url("https://www.realmeye.com/s/ht/img/renders.png")


def test_unknown_sheet_host_is_rejected():
    with pytest.raises(SpriteCropError, match="not allowed"):
        assert_allowed_sheet_url("https://evil.example/sheet.png")


def test_crop_sheet_bytes_returns_64px_png():
    png = crop_sheet_bytes(_sheet_png(), x=40, y=40, size=16)
    out = Image.open(BytesIO(png))
    assert out.size == (64, 64)
    assert out.getpixel((0, 0))[0] == 255


def test_crop_out_of_bounds_is_rejected():
    with pytest.raises(SpriteCropError, match="out of bounds"):
        crop_sheet_bytes(_sheet_png(), x=70, y=70, size=16)


def _client(redis_client, settings) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_settings] = lambda: settings
    transport = httpx.ASGITransport(app=app, client=CALLER)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_sprite_crop_endpoint_returns_png(redis_client, anon_settings):
    png = crop_sheet_bytes(_sheet_png(), x=40, y=40, size=16)

    async def fake_crop(sheet_url: str, x: int, y: int, size: int) -> bytes:
        return png

    with patch("api.routers.sprite.fetch_and_crop_sprite", new=fake_crop):
        async with _client(redis_client, anon_settings) as http:
            response = await http.get(
                "/sprite/crop",
                params={
                    "sheet": "https://www.realmeye.com/s/ht/img/renders.png",
                    "x": 40,
                    "y": 40,
                    "size": 16,
                },
            )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert Image.open(BytesIO(response.content)).size == (64, 64)


@pytest.mark.asyncio
async def test_sprite_crop_rejects_unknown_host(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.get(
            "/sprite/crop",
            params={
                "sheet": "https://evil.example/sheet.png",
                "x": 0,
                "y": 0,
                "size": 16,
            },
        )
    assert response.status_code == 400
