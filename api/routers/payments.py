"""
Payments router | Stripe Checkout + magic link auth.

Flow:
  1. POST /payments/checkout  -> returns Stripe Checkout URL
  2. Stripe webhook -> POST /payments/webhook -> verifies payment, sends magic link email
  3. GET /payments/verify?token=... -> validates magic link, returns JWT
"""
import time
from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from ..auth import create_jwt, send_magic_link
from ..config import Settings, get_settings

router = APIRouter(prefix="/payments", tags=["payments"])


class CheckoutRequest(BaseModel):
    session_id: str
    email: str


class CheckoutResponse(BaseModel):
    checkout_url: str


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CheckoutRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> CheckoutResponse:
    """Create a Stripe Checkout session for the $7/month plan."""
    if not settings.stripe_secret_key or not settings.stripe_price_id:
        raise HTTPException(status_code=503, detail="Payments not configured")

    stripe.api_key = settings.stripe_secret_key
    checkout = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        customer_email=body.email,
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url=f"{settings.app_url}?upgraded=true&email={body.email}",
        cancel_url=settings.app_url,
        metadata={"session_id": body.session_id, "email": body.email},
    )
    return CheckoutResponse(checkout_url=checkout.url)


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    stripe_signature: Annotated[str | None, Header(alias="stripe-signature")] = None,
) -> dict:
    """Stripe webhook | fires after successful subscription payment."""
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook: {e}")

    if event["type"] == "checkout.session.completed":
        session_data = event["data"]["object"]
        email = session_data.get("customer_email") or session_data.get("metadata", {}).get("email")
        if email:
            await send_magic_link(email, settings)
            logger.info("Magic link sent after successful payment", email=email)

    return {"received": True}


@router.get("/verify")
async def verify_magic_link(
    token: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Validate a magic link token and return a JWT session token."""
    from ..auth import decode_magic_token

    try:
        email = decode_magic_token(token, settings.jwt_secret)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired magic link")

    jwt_token = create_jwt({"email": email, "paid": True}, settings)
    return {"token": jwt_token, "email": email}
