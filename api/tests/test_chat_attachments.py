"""Chat composer images go to Claude as vision blocks."""

from __future__ import annotations

import base64

import pytest
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from api.models.chat import MAX_ATTACHMENTS, ChatAttachment, ChatRequest
from api.routers.chat import _request_attachments, _user_content, _validate_attachment
from api.services.model_route import pick_chat_model
from api.tests.test_model_route import _settings

_MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)
_PNG_B64 = base64.b64encode(_MINI_PNG).decode("ascii")


def _image(name: str = "shot.png") -> ChatAttachment:
    return ChatAttachment(filename=name, media_type="image/png", data=_PNG_B64)


def test_user_content_plain_text_without_images():
    body = ChatRequest(message="best bard build")
    assert _user_content(body, []) == "best bard build"


def test_user_content_sends_image_blocks():
    att = _image("vault.png")
    body = ChatRequest(message="what should I keep?", attachments=[att])
    content = _user_content(body, [att])
    assert isinstance(content, list)
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
    assert content[0]["source"]["data"] == _PNG_B64
    assert content[1]["type"] == "text"
    assert "what should I keep?" in content[1]["text"]


def test_user_content_image_only_uses_rotmg_caption():
    att = _image()
    body = ChatRequest(message="  ", attachments=[att])
    content = _user_content(body, [att])
    assert isinstance(content, list)
    assert "RotMG" in content[-1]["text"]


def test_legacy_single_attachment_still_counts():
    att = _image("old.png")
    body = ChatRequest(message="hi", attachment=att)
    assert _request_attachments(body) == [att]


def test_legacy_plus_list_are_combined():
    first = _image("a.png")
    second = _image("b.png")
    body = ChatRequest(message="hi", attachment=first, attachments=[second])
    assert [item.filename for item in _request_attachments(body)] == ["a.png", "b.png"]


def test_too_many_attachments_are_rejected():
    atts = [_image(f"{i}.png") for i in range(MAX_ATTACHMENTS + 1)]
    body = ChatRequest(message="hi")
    body.attachments = atts
    with pytest.raises(HTTPException, match="At most"):
        _request_attachments(body)


def test_pydantic_caps_attachments_list():
    atts = [_image(f"{i}.png") for i in range(MAX_ATTACHMENTS + 1)]
    with pytest.raises(ValidationError):
        ChatRequest(message="hi", attachments=atts)


def test_composer_wires_screenshot_thumbnails():
    root = Path(__file__).resolve().parents[2]
    composer = (root / "web" / "components" / "chat" / "ChatInterface.tsx").read_text(
        encoding="utf-8"
    )
    assert "ComposerImages" in composer
    assert "CHAT_IMAGE_ACCEPT" in composer
    assert "onPaste={handleComposerPaste}" in composer
    assert "pickGhostHit" in composer
    suggest = (root / "web" / "components" / "chat" / "ComposerSuggest.tsx").read_text(
        encoding="utf-8"
    )
    assert "ghostRemainder" in suggest
    assert "lastSuggestToken" in suggest
    assert "text-[#737373]" in suggest
    assert "z-10" in suggest
    thumbs = (root / "web" / "components" / "chat" / "ComposerImages.tsx").read_text(
        encoding="utf-8"
    )
    assert 'preview="image"' in thumbs
    zoom = (root / "web" / "components" / "chat" / "SpriteZoom.tsx").read_text(encoding="utf-8")
    assert '"image"' in zoom
    bubble = (root / "web" / "components" / "chat" / "MessageBubble.tsx").read_text(
        encoding="utf-8"
    )
    assert "ChatImageThumb" in bubble


def test_non_image_attachment_is_rejected():
    att = ChatAttachment(filename="notes.txt", media_type="text/plain", data=_PNG_B64)
    with pytest.raises(HTTPException, match="Unsupported"):
        _validate_attachment(att)


def test_screenshot_turns_stay_on_sonnet():
    settings = _settings()
    assert (
        pick_chat_model("what is this gear", settings, has_attachment=True)
        == settings.claude_model
    )
