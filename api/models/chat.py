from pydantic import BaseModel, Field
from typing import Literal, Optional

# Outer bounds on request size. Input tokens are billed, so an unbounded
# message or history is an unbounded bill. These are deliberately generous |
# anything past them is abuse rather than a long question. History is also
# trimmed further when the prompt is assembled.
MAX_MESSAGE_CHARS = 16_000
MAX_HISTORY_MESSAGES = 50


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str = Field(max_length=MAX_MESSAGE_CHARS)


class ChatAttachment(BaseModel):
    """A file the user attached in the chat composer.

    `data` is raw base64 (no data: URL prefix). Images go to Claude as vision
    blocks; PDFs go as document blocks.
    """

    filename: str
    media_type: str
    data: str


class ChatRequest(BaseModel):
    message: str = Field(max_length=MAX_MESSAGE_CHARS)
    history: list[ChatMessage] = Field(default=[], max_length=MAX_HISTORY_MESSAGES)
    # Retained for backward compatibility. No longer used for rate limiting:
    # it was client-generated, so callers could mint themselves a new quota.
    session_id: str = ""
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
