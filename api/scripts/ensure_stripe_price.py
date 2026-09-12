"""Create the $7/month RealmPal Pro price if .env has a Stripe secret and no price."""
from __future__ import annotations

import re
from pathlib import Path

import stripe

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"


def _env_value(text: str, name: str) -> str:
    match = re.search(rf"^{name}=(.*)$", text, re.M)
    if not match:
        return ""
    return match.group(1).strip().strip('"').strip("'")


def main() -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    key = _env_value(text, "STRIPE_SECRET_KEY")
    if not key or "..." in key:
        raise SystemExit(
            "Paste a real Stripe test secret (sk_test_...) into .env, then re-run."
        )

    current = _env_value(text, "STRIPE_PRICE_ID")
    stripe.api_key = key

    existing = None
    if current and current.startswith("price_"):
        try:
            existing = stripe.Price.retrieve(current)
        except stripe.StripeError:
            existing = None

    if existing is None:
        for price in stripe.Price.list(
            active=True, limit=100, expand=["data.product"]
        ).auto_paging_iter():
            product = price.product
            name = getattr(product, "name", "") or ""
            recurring = price.recurring or {}
            if (
                recurring.get("interval") == "month"
                and price.unit_amount == 700
                and ("RealmPal" in name)
            ):
                existing = price
                break

    created = False
    if existing is None:
        product = stripe.Product.create(
            name="RealmPal Pro",
            description="RealmPal Pro monthly subscription",
        )
        existing = stripe.Price.create(
            product=product.id,
            unit_amount=700,
            currency="usd",
            recurring={"interval": "month"},
        )
        created = True

    price_id = existing.id
    if re.search(r"^STRIPE_PRICE_ID=", text, re.M):
        text = re.sub(r"^STRIPE_PRICE_ID=.*$", f"STRIPE_PRICE_ID={price_id}", text, flags=re.M)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += f"STRIPE_PRICE_ID={price_id}\n"
    ENV_PATH.write_text(text, encoding="utf-8")
    print(("created" if created else "reused"), price_id)


if __name__ == "__main__":
    main()
