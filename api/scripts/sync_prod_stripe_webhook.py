"""Point Stripe at the production webhook and store the signing secret.

Does not print secrets. Uses the Stripe key already in Settings, then
writes only the webhook signing secret onto the Container App.
"""
from __future__ import annotations

import subprocess
import sys

import stripe

from api.config import Settings

WEBHOOK_URL = (
    "https://realmpal-api.mangoflower-33aeb683.eastus2.azurecontainerapps.io"
    "/payments/webhook"
)
EVENTS = (
    "checkout.session.completed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
)
APP = "realmpal-api"
GROUP = "rg-realmpal"
# Container App secret names cannot be longer than 20 characters.
SECRET_NAME = "stripe-whsec"


def _az(args: list[str], extra_env: dict[str, str] | None = None) -> None:
    env = None
    if extra_env:
        import os

        env = os.environ.copy()
        env.update(extra_env)
    az = "az.cmd" if sys.platform == "win32" else "az"
    result = subprocess.run(
        [az, *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").replace("\n", " ")
        if "whsec_" in err:
            err = "az rejected the secret payload"
        raise SystemExit(f"az failed ({result.returncode}): {err[:240]}")


def main() -> None:
    settings = Settings()
    key = settings.stripe_secret_key.strip()
    if not key or "..." in key:
        raise SystemExit("Stripe is not configured")
    stripe.api_key = key

    existing = None
    for endpoint in stripe.WebhookEndpoint.list(limit=20).auto_paging_iter():
        if endpoint.url == WEBHOOK_URL:
            existing = endpoint
            break
        if "/payments/webhook" in (endpoint.url or ""):
            stripe.WebhookEndpoint.delete(endpoint.id)

    if existing is None:
        created = stripe.WebhookEndpoint.create(
            url=WEBHOOK_URL,
            enabled_events=list(EVENTS),
            description="RealmPal production API",
        )
        secret = created.secret
        print("webhook created")
    else:
        stripe.WebhookEndpoint.modify(
            existing.id,
            enabled_events=list(EVENTS),
        )
        # Signing secret is only returned on create. Recreate if Azure
        # does not already have one.
        print("webhook already existed; recreate to mint a new secret")
        stripe.WebhookEndpoint.delete(existing.id)
        created = stripe.WebhookEndpoint.create(
            url=WEBHOOK_URL,
            enabled_events=list(EVENTS),
            description="RealmPal production API",
        )
        secret = created.secret
        print("webhook recreated")

    if not secret or not secret.startswith("whsec_"):
        raise SystemExit("Stripe did not return a webhook secret")

    _az(
        [
            "containerapp",
            "secret",
            "set",
            "--name",
            APP,
            "--resource-group",
            GROUP,
            "--secrets",
            f"{SECRET_NAME}={secret}",
            "--output",
            "none",
        ]
    )
    _az(
        [
            "containerapp",
            "update",
            "--name",
            APP,
            "--resource-group",
            GROUP,
            "--set-env-vars",
            f"STRIPE_WEBHOOK_SECRET=secretref:{SECRET_NAME}",
            "--output",
            "none",
        ]
    )
    print("container app secret set")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"sync failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
