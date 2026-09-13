"""
Payments router | Stripe Checkout for RealmPal Pro.

Flow:
  1. POST /payments/checkout  -> Stripe Checkout URL (signed-in email)
  2. User pays and returns to /?upgraded=true&session_id=cs_...
  3. POST /payments/confirm   -> opens the entitlement and remints the JWT
  4. POST /payments/webhook   -> cancel / past_due / recover from Stripe
  5. GET /payments/verify     -> leftover magic-link redeem (forgot password)
"""
import time
from typing import Annotated

import redis.asyncio as aioredis
import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from ..auth import create_jwt, decode_magic_token, email_from_session_header
from ..config import Settings, get_settings
from ..dependencies import enforce_lookup_rate_limit, get_redis
from ..services import accounts, billing_prefs, entitlements
from ..services.claude_billing import peek_claude_usage
from ..services.validation import validate_email

# Stripe subscription statuses that keep the paid tier on. Everything else
# (canceled, unpaid, past_due, incomplete_expired, ...) revokes it.
_LIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing"})

router = APIRouter(prefix="/payments", tags=["payments"])

# One-time-use marker for a redeemed magic-link jti. TTL matches how long
# the token itself remains signature-valid, so the marker never outlives
# the thing it's guarding against a replay of.
_MAGIC_LINK_USED_PREFIX = "magiclink:used:"


class CheckoutRequest(BaseModel):
    session_id: str = ""
    email: str = ""


class CheckoutResponse(BaseModel):
    checkout_url: str


class ConfirmRequest(BaseModel):
    session_id: str


def _success_url(settings: Settings) -> str:
    return f"{settings.app_url}?upgraded=true&session_id={{CHECKOUT_SESSION_ID}}"


async def _session_payload(email: str, settings: Settings) -> dict:
    paid = await entitlements.is_active(email, settings)
    ign = await accounts.get_ign(email, settings)
    token = create_jwt({"email": email, "paid": paid, "ign": ign}, settings)
    return {"token": token, "email": email, "paid": paid, "ign": ign}


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    dependencies=[Depends(enforce_lookup_rate_limit)],
)
async def create_checkout(
    body: CheckoutRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: str | None = Header(default=None),
) -> CheckoutResponse:
    """Create a Stripe Checkout session for the $7/month plan."""
    if not settings.stripe_configured:
        raise HTTPException(
            status_code=503,
            detail="Stripe is not set up yet. Add STRIPE_SECRET_KEY and STRIPE_PRICE_ID to .env, then restart the API.",
        )

    email = email_from_session_header(authorization, settings)
    if not email:
        try:
            email = validate_email(body.email)
        except HTTPException:
            raise HTTPException(status_code=401, detail="Sign in to upgrade")

    stripe.api_key = settings.stripe_secret_key
    try:
        checkout = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            customer_email=email,
            line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
            success_url=_success_url(settings),
            cancel_url=settings.app_url,
            metadata={"session_id": body.session_id, "email": email},
        )
    except stripe.StripeError as exc:
        logger.exception("Stripe Checkout session failed")
        raise HTTPException(status_code=503, detail="Payments not configured") from exc
    return CheckoutResponse(checkout_url=checkout.url)


@router.post("/confirm", dependencies=[Depends(enforce_lookup_rate_limit)])
async def confirm_checkout(
    body: ConfirmRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: str | None = Header(default=None),
) -> dict:
    """
    After Stripe redirects home, activate Pro from the Checkout session.

    Webhooks still own cancel/refund. This is the return-path so a signed-in
    user does not wait on a local webhook (or a magic-link email).
    """
    email = email_from_session_header(authorization, settings)
    if not email:
        raise HTTPException(status_code=401, detail="Sign in to finish upgrading")
    if not settings.stripe_secret_key or "..." in settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Payments not configured")

    stripe.api_key = settings.stripe_secret_key
    try:
        session = stripe.checkout.Session.retrieve(body.session_id)
    except stripe.StripeError as exc:
        raise HTTPException(status_code=400, detail="Invalid checkout session") from exc

    data = session.to_dict() if hasattr(session, "to_dict") else dict(session)
    details = data.get("customer_details") or {}
    if data.get("status") != "complete" and data.get("payment_status") not in (
        "paid",
        "no_payment_required",
    ):
        raise HTTPException(status_code=400, detail="Checkout is not complete")

    session_email = (
        details.get("email")
        or data.get("customer_email")
        or (data.get("metadata") or {}).get("email")
        or ""
    )
    if session_email and str(session_email).strip().lower() != email:
        raise HTTPException(status_code=403, detail="Checkout belongs to another account")

    await entitlements.upsert(
        email,
        status="active",
        settings=settings,
        stripe_customer_id=data.get("customer"),
        stripe_subscription_id=data.get("subscription"),
    )
    return await _session_payload(email, settings)


async def _apply_stripe_event(event: dict, settings: Settings) -> None:
    """
    Write subscription state to the durable entitlement store.

    This is the "no subscription lookup, no revocation list" gap: before
    this, a payment minted a magic link and nothing about the subscription
    was ever checked again. `checkout.session.completed` now opens a row;
    `customer.subscription.updated` / `.deleted` can close it. The chat path
    (api/routers/chat.py) reads this instead of trusting a JWT forever.
    """
    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        email = (
            data.get("customer_email")
            or (data.get("metadata") or {}).get("email")
            or ""
        )
        if email:
            await entitlements.upsert(
                email,
                status="active",
                settings=settings,
                stripe_customer_id=data.get("customer"),
                stripe_subscription_id=data.get("subscription"),
            )
            logger.bind(customer_id=data.get("customer")).info(
                "Entitlement opened after successful payment"
            )
        return

    if event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        customer_id = data.get("customer")
        stripe_status = data.get("status") or ""
        status = "active" if stripe_status in _LIVE_SUBSCRIPTION_STATUSES else "canceled"
        await entitlements.set_status_by_customer(customer_id, status, settings)


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    stripe_signature: Annotated[str | None, Header(alias="stripe-signature")] = None,
) -> dict:
    """Stripe webhook | fires after checkout and on every subscription change."""
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook: {e}")

    await _apply_stripe_event(event, settings)
    return {"received": True}


@router.get("/verify", dependencies=[Depends(enforce_lookup_rate_limit)])
async def verify_magic_link(
    token: str,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
) -> dict:
    """
    Validate a magic link token and return a JWT session token.

    Single-use: a link that's been redeemed once (browser prefetch, a
    forwarded email, someone re-clicking it) must not mint a second session.
    The `SET NX` is the enforcement | check-then-set here would race two
    concurrent redemptions of the same link into both succeeding.
    """
    try:
        claims = decode_magic_token(token, settings.effective_magic_link_secret)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired magic link")

    remaining_ttl = max(1, claims.exp - int(time.time()))
    first_use = await redis.set(
        f"{_MAGIC_LINK_USED_PREFIX}{claims.jti}", "1", nx=True, ex=remaining_ttl
    )
    if not first_use:
        logger.bind(email=claims.email).info("Magic link reused; rejecting")
        raise HTTPException(status_code=400, detail="Invalid or expired magic link")

    # This link may have come from a Stripe checkout (api/routers/payments.py's
    # webhook) or from the free, unauthenticated /auth/request-link - the
    # token itself can't tell those apart, so `paid` is always looked up
    # fresh here rather than assumed from "someone redeemed a valid link."
    return await _session_payload(claims.email, settings)


class OnDemandRequest(BaseModel):
    spend_cap_usd: float = 0


class OnDemandResponse(BaseModel):
    spend_cap_usd: float
    allowed_caps_usd: list[float]
    claude_used: int
    claude_limit: int
    claude_remaining: int
    on_demand_spent_usd: float
    overage_usd: float


class BillingResponse(BaseModel):
    tier: str
    subscription_status: str | None = None
    plan_name: str = "RealmPal Pro"
    plan_price_usd: float = 7.0
    claude_used_percent: int | None = None
    spend_cap_usd: float | None = None
    on_demand_spent_usd: float | None = None
    overage_usd: float | None = None
    allowed_caps_usd: list[float] | None = None


def _usage_percent(used: int, limit: int) -> int:
    safe_limit = max(1, limit)
    return min(100, round(max(0, used) / safe_limit * 100))


@router.get("/billing", response_model=BillingResponse)
async def get_billing(
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    authorization: str | None = Header(default=None),
) -> BillingResponse:
    """Plan and usage summary for the signed-in account."""
    email = email_from_session_header(authorization, settings)
    if not email:
        raise HTTPException(status_code=401, detail="Sign in to view billing")

    paid = await entitlements.is_active(email, settings)
    status = await entitlements.get_status(email, settings)
    if not paid:
        return BillingResponse(tier="free", subscription_status=status)

    claude = await peek_claude_usage(redis, email, settings)
    return BillingResponse(
        tier="paid",
        subscription_status=status or "active",
        plan_price_usd=7.0,
        claude_used_percent=_usage_percent(claude.used, claude.included),
        spend_cap_usd=claude.spend_cap_usd,
        on_demand_spent_usd=claude.on_demand_spent_usd,
        overage_usd=settings.claude_overage_usd,
        allowed_caps_usd=list(billing_prefs.ALLOWED_CAPS_USD),
    )


async def _paid_email(authorization: str | None, settings: Settings) -> str:
    email = email_from_session_header(authorization, settings)
    if not email:
        raise HTTPException(status_code=401, detail="Sign in to manage usage")
    if not await entitlements.is_active(email, settings):
        raise HTTPException(status_code=403, detail="Usage billing is for Pro accounts")
    return email


@router.get("/on-demand", response_model=OnDemandResponse)
async def get_on_demand(
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    authorization: str | None = Header(default=None),
) -> OnDemandResponse:
    email = await _paid_email(authorization, settings)
    claude = await peek_claude_usage(redis, email, settings)
    return OnDemandResponse(
        spend_cap_usd=claude.spend_cap_usd,
        allowed_caps_usd=list(billing_prefs.ALLOWED_CAPS_USD),
        claude_used=claude.used,
        claude_limit=claude.included,
        claude_remaining=claude.remaining,
        on_demand_spent_usd=claude.on_demand_spent_usd,
        overage_usd=settings.claude_overage_usd,
    )


@router.post("/on-demand", response_model=OnDemandResponse)
async def set_on_demand(
    body: OnDemandRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    authorization: str | None = Header(default=None),
) -> OnDemandResponse:
    email = await _paid_email(authorization, settings)
    await billing_prefs.set_spend_cap_usd(email, body.spend_cap_usd, settings)
    claude = await peek_claude_usage(redis, email, settings)
    return OnDemandResponse(
        spend_cap_usd=claude.spend_cap_usd,
        allowed_caps_usd=list(billing_prefs.ALLOWED_CAPS_USD),
        claude_used=claude.used,
        claude_limit=claude.included,
        claude_remaining=claude.remaining,
        on_demand_spent_usd=claude.on_demand_spent_usd,
        overage_usd=settings.claude_overage_usd,
    )
