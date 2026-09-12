"""
Chat image attachments. Stored in SQLite and recycled after upload_ttl_days.
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile

from ..auth import email_from_session_header
from ..config import Settings, get_settings
from ..dependencies import enforce_lookup_rate_limit
from ..services import accounts, uploads

router = APIRouter(prefix="/uploads", tags=["uploads"])

_ALLOWED_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})


@router.post("", dependencies=[Depends(enforce_lookup_rate_limit)])
async def upload_image(
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
    session_id: str = Form(default=""),
    train_on_data: Optional[str] = Form(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Only image uploads are accepted")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.upload_max_bytes:
        raise HTTPException(status_code=400, detail="Image is too large")

    email = email_from_session_header(authorization, settings)
    if email:
        train = await accounts.get_train_on_data(email, settings)
    elif train_on_data is not None:
        train = train_on_data.strip().lower() not in {"0", "false", "off", "no"}
    else:
        train = True

    return await uploads.store(
        data=data,
        filename=file.filename or "upload",
        content_type=content_type,
        settings=settings,
        email=email,
        session_id=session_id or None,
        train_on_data=train,
    )
