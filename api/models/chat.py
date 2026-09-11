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
    # "user" once signed in, "ip" for anonymous callers.
    scope: str = "ip"


class PaywallResponse(BaseModel):
    upgrade: bool = True
    message: str = "You've run out of free messages."
    checkout_url: Optional[str] = None
    # Anonymous callers get a sign-in prompt; signed-in ones get checkout.
    scope: str = "ip"
    used: int = 0
    limit: int = 0
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
