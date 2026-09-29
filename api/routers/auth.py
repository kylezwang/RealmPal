"""
Local account auth: email+password is the primary path.

Magic links stay as a fallback (`POST /auth/request-link`) so Forgot
password does not depend on a paid transactional-email API. Entra External
ID would later send OTP mail as part of Azure's identity service; until
that is wired, a password is cheaper and simpler.

A successful register or sign-in mints the same session JWT that
`/payments/verify` does. `paid` is always looked up in
api/services/entitlements.py - registering does not grant the paid tier.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from ..auth import create_jwt, email_from_session_header, send_magic_link
from ..config import Settings, get_settings
from ..dependencies import enforce_lookup_rate_limit
from ..services import accounts, entitlements
from ..services.admin_access import jwt_role
from ..services.validation import sanitize_lookup_name, validate_email, validate_password

router = APIRouter(prefix="/auth", tags=["auth"])


class RequestLinkBody(BaseModel):
    email: str


class PasswordBody(BaseModel):
    email: str
    password: str


class RegisterBody(PasswordBody):
    ign: str
    confirm_password: str = ""


async def _session_for(email: str, settings: Settings) -> dict:
    paid = await entitlements.is_active(email, settings)
    ign = await accounts.get_ign(email, settings)
    role = await jwt_role(email, ign, settings)
    token = create_jwt(
        {"email": email, "paid": paid, "ign": ign, "role": role}, settings
    )
    return {"token": token, "email": email, "paid": paid, "ign": ign, "role": role}


@router.post("/register", dependencies=[Depends(enforce_lookup_rate_limit)])
async def register(
    body: RegisterBody,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    email = validate_email(body.email)
    password = validate_password(body.password)
    if body.confirm_password != password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    ign = sanitize_lookup_name(body.ign, field="ign")
    if await accounts.email_for_ign(ign, settings):
        raise HTTPException(status_code=409, detail="An account with this IGN already exists")
    created = await accounts.create(email, password, settings, ign=ign)
    if not created:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    return await _session_for(email, settings)


@router.post("/signin", dependencies=[Depends(enforce_lookup_rate_limit)])
async def sign_in(
    body: PasswordBody,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    # `email` on the body is the login identifier: a real email, or the
    # account IGN. Length-check only on the password - a miss and a wrong
    # password must look the same, so we do not reject a too-short password
    # before the dummy verify.
    identifier = (body.email or "").strip()
    password = body.password or ""
    if "@" in identifier:
        email = validate_email(identifier)
    else:
        try:
            ign = sanitize_lookup_name(identifier, field="ign")
        except HTTPException:
            await accounts.verify("", password, settings)
            raise HTTPException(status_code=401, detail="Invalid email or password")
        emails = await accounts.emails_for_ign(ign, settings)
        if not emails:
            await accounts.verify("", password, settings)
            raise HTTPException(status_code=401, detail="Invalid email or password")
        for email in emails:
            if await accounts.verify(email, password, settings):
                return await _session_for(email, settings)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if await accounts.verify(email, password, settings):
        return await _session_for(email, settings)
    raise HTTPException(status_code=401, detail="Invalid email or password")


@router.post("/request-link", dependencies=[Depends(enforce_lookup_rate_limit)])
async def request_sign_in_link(
    body: RequestLinkBody,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """
    Email a sign-in link for `body.email`. Optional fallback, not the
    primary path - that is `/auth/signin`.

    Always reports success. This is passwordless and open to any address,
    so there is no "account already exists" state worth leaking, and no
    reason to tell a caller which addresses look real versus made up.
    """
    email = validate_email(body.email)
    await send_magic_link(email, settings)
    return {"sent": True}


_OAUTH_PROVIDERS = frozenset({"google", "microsoft"})


@router.get("/oauth/{provider}")
async def start_oauth(provider: str) -> None:
    """
    Start Google or Microsoft sign-in.

    Entra External ID will own the real redirect once portal values exist.
    Until then this is a visible button, not a silent no-op: 501 so the
    frontend can say the provider isn't wired yet instead of hanging.
    """
    if provider not in _OAUTH_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown sign-in provider")
    raise HTTPException(
        status_code=501,
        detail=f"Sorry, {provider.title()} sign-in isn't set up yet",
    )


class PreferencesBody(BaseModel):
    train_on_data: bool


@router.get("/preferences")
async def get_preferences(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: str | None = Header(default=None),
) -> dict:
    """
    Default is on. Guests without a session get the default rather than an
    error - Settings can render the toggle before anyone has signed in.
    """
    email = email_from_session_header(authorization, settings)
    if not email:
        return {"train_on_data": True}
    return {"train_on_data": await accounts.get_train_on_data(email, settings)}


@router.patch("/preferences")
async def update_preferences(
    body: PreferencesBody,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: str | None = Header(default=None),
) -> dict:
    email = email_from_session_header(authorization, settings)
    if not email:
        raise HTTPException(status_code=401, detail="Sign in to save this setting")
    value = await accounts.set_train_on_data(email, body.train_on_data, settings)
    return {"train_on_data": value}
