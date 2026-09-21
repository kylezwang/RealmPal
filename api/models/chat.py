from pydantic import BaseModel, Field
from typing import Literal, Optional

# Outer bounds on request size. Input tokens are billed, so an unbounded
# message or history is an unbounded bill. These are deliberately generous |
# anything past them is abuse rather than a long question. History is also
# trimmed further when the prompt is assembled.
MAX_MESSAGE_CHARS = 16_000
MAX_HISTORY_MESSAGES = 50


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_MESSAGE_CHARS)


class ChatAttachment(BaseModel):
    """A file the user attached in the chat composer.

    `data` is raw base64 (no data: URL prefix). Images go to Claude as vision blocks.
    """

    filename: str
    media_type: str
    data: str


MAX_ATTACHMENTS = 4


class ChatRequest(BaseModel):
    message: str = Field(max_length=MAX_MESSAGE_CHARS)
    history: list[ChatMessage] = Field(default=[], max_length=MAX_HISTORY_MESSAGES)
    # Retained for backward compatibility. No longer used for rate limiting:
    # it was client-generated, so callers could mint themselves a new quota.
    session_id: str = ""
    ign: Optional[str] = Field(default=None, max_length=32)  # in-game name for context
    attachment: Optional[ChatAttachment] = None
    attachments: list[ChatAttachment] = Field(default=[], max_length=MAX_ATTACHMENTS)


class UsageResponse(BaseModel):
    used: int
    limit: int
    remaining: int
    # "user" once signed in, "ip" for anonymous callers.
    scope: str = "ip"
    # guest (IP), free (signed-in), or paid.
    tier: str = "guest"
    claude_used: int = 0
    claude_limit: int = 0
    claude_remaining: int = 0
    spend_cap_usd: float = 0
    on_demand_spent_usd: float = 0
    # Seconds until the free daily bucket rolls. 0 if it has not started.
    resets_in_seconds: int = 0
    # Server-checked admin role. The notifications modal keys off this,
    # not a client IGN guess or a JWT claim.
    is_admin: bool = False


class PaywallResponse(BaseModel):
    upgrade: bool = True
    message: str = "You've run out of free in-depth responses."
    checkout_url: Optional[str] = None
    # Anonymous callers get a sign-in prompt; signed-in ones get checkout.
    scope: str = "ip"
    used: int = 0
    limit: int = 0
    remaining: int = 0
    # free_quota | claude_pool | spend_cap
    reason: str = "free_quota"
    spend_cap_usd: float = 0
    resets_in_seconds: int = 0


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    message_id: str
    session_id: str
    response: str = ""
    prompt: Optional[str] = None
    what_went_wrong: Optional[str] = None
    improvement: Optional[str] = None


class SiteFeedbackRequest(BaseModel):
    """Header Feedback modal. Separate from per-message thumbs-up/down."""

    rating: Literal["great", "okay", "rough"]
    what_works: str = Field(default="", max_length=4000)
    what_to_improve: str = Field(default="", max_length=4000)
    anything_else: str = Field(default="", max_length=4000)
    ign: Optional[str] = Field(default=None, max_length=32)


class FeedbackResponse(BaseModel):
    ok: bool = True
