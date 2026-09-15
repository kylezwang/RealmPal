from pydantic import BaseModel, Field

# A session's messages are stored/returned as opaque JSON (the backend never
# inspects their shape) so the frontend's StoredMessage interface
# (web/lib/chatHistory.ts) can evolve without a matching backend change -
# this store is a blob, not a schema for chat content.
MAX_SESSION_MESSAGES = 300
MAX_SESSIONS_PER_SYNC = 200


class ChatSessionPayload(BaseModel):
    id: str = Field(max_length=100)
    title: str = Field(default="New chat", max_length=200)
    messages: list[dict] = Field(default=[], max_length=MAX_SESSION_MESSAGES)
    updatedAt: int = 0


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionPayload]


class ChatSessionSyncRequest(BaseModel):
    sessions: list[ChatSessionPayload] = Field(default=[], max_length=MAX_SESSIONS_PER_SYNC)


class ChatSessionOk(BaseModel):
    ok: bool = True
