from pydantic import BaseModel
from typing import Literal, Optional


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatAttachment(BaseModel):
    """A file the user attached in the chat composer.

    `data` is raw base64 (no data: URL prefix). Images go to Claude as vision
    blocks; PDFs go as document blocks.
    """

    filename: str
    media_type: str
    data: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    session_id: str  # client-generated UUID, used for rate limiting
    ign: Optional[str] = None  # in-game name for context
    attachment: Optional[ChatAttachment] = None


class UsageResponse(BaseModel):
    used: int
    limit: int
    remaining: int


class PaywallResponse(BaseModel):
    upgrade: bool = True
    message: str = "You've used your 3 free messages. Join Realm Pal for $7/month to continue."
    checkout_url: Optional[str] = None
    used: int = 3
    limit: int = 3
    remaining: int = 0


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    message_id: str
    session_id: str
    response: str = ""
    prompt: Optional[str] = None
    what_went_wrong: Optional[str] = None
    improvement: Optional[str] = None


class FeedbackResponse(BaseModel):
    ok: bool = True
