"""
Chat image attachments: store, opt-in flag, recycle after TTL.
"""
from __future__ import annotations

import httpx
import pytest

from api.config import get_settings
from api.dependencies import get_redis
from api.main import create_app
from api.services import uploads

CALLER = ("198.51.100.7", 44321)

# 1×1 transparent PNG
_MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _client(redis_client, settings) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_settings] = lambda: settings
    transport = httpx.ASGITransport(app=app, client=CALLER)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_upload_stores_an_image(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post(
            "/uploads",
            files={"file": ("shot.png", _MINI_PNG, "image/png")},
            data={"session_id": "sess-1"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "shot.png"
    assert body["train_on_data"] is True
    assert body["id"]
    assert body["expires_at"] > 0


async def test_guest_can_opt_out_of_training(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post(
            "/uploads",
            files={"file": ("shot.png", _MINI_PNG, "image/png")},
            data={"train_on_data": "false"},
        )
    assert response.status_code == 200
    assert response.json()["train_on_data"] is False


async def test_non_image_is_rejected(redis_client, anon_settings):
    async with _client(redis_client, anon_settings) as http:
        response = await http.post(
            "/uploads",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
    assert response.status_code == 400


async def test_store_purges_expired_rows(anon_settings):
    first = await uploads.store(
        data=_MINI_PNG,
        filename="old.png",
        content_type="image/png",
        settings=anon_settings,
    )
    conn = uploads._connection(anon_settings.uploads_db_path)
    conn.execute("UPDATE uploads SET expires_at = 1 WHERE id = ?", (first["id"],))

    await uploads.store(
        data=_MINI_PNG,
        filename="new.png",
        content_type="image/png",
        settings=anon_settings,
    )

    rows = conn.execute("SELECT filename FROM uploads ORDER BY filename").fetchall()
    assert rows == [("new.png",)]
