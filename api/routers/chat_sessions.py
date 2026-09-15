"""
Server-side chat history sync for signed-in accounts.

See api/services/chat_sessions.py for why this exists (short version: an
incognito window's localStorage disappears when the last incognito window
closes, which looked like chat history vanishing even though the signed-in
account was untouched). This router is the account-scoped mirror the
frontend syncs local sessions to/from once a user is signed in; anonymous
sessions never reach here at all, they stay local-only in the browser.
"""
from typing import Annotated

from fastapi import APIRouter, Depends

from ..config import Settings, get_settings
from ..dependencies import require_user
from ..identity import AuthenticatedUser
from ..models.chat_session import (
    ChatSessionListResponse,
    ChatSessionOk,
    ChatSessionPayload,
    ChatSessionSyncRequest,
)
from ..services import chat_sessions

router = APIRouter(prefix="/chat/sessions", tags=["chat_sessions"])


@router.get("", response_model=ChatSessionListResponse)
async def list_sessions(
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> ChatSessionListResponse:
    sessions = await chat_sessions.list_sessions(settings, user.email or "")
    return ChatSessionListResponse(sessions=sessions)


@router.put("/{session_id}", response_model=ChatSessionOk)
async def upsert_session(
    session_id: str,
    payload: ChatSessionPayload,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> ChatSessionOk:
    await chat_sessions.upsert_session(
        settings,
        user.email or "",
        session_id,
        title=payload.title,
        messages=payload.messages,
        updated_at=payload.updatedAt or None,
    )
    return ChatSessionOk()


@router.delete("/{session_id}", response_model=ChatSessionOk)
async def delete_session(
    session_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> ChatSessionOk:
    await chat_sessions.delete_session(settings, user.email or "", session_id)
    return ChatSessionOk()


@router.post("/sync", response_model=ChatSessionListResponse)
async def sync_sessions(
    payload: ChatSessionSyncRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> ChatSessionListResponse:
    """Push whatever the caller only has locally, then return the full
    server-side merged list so the client can reconcile in one round trip -
    used once, right after sign-in, before per-session PUTs take over."""
    email = user.email or ""
    if payload.sessions:
        await chat_sessions.replace_all(
            settings, email, [s.model_dump() for s in payload.sessions]
        )
    sessions = await chat_sessions.list_sessions(settings, email)
    return ChatSessionListResponse(sessions=sessions)
