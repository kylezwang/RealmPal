from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env whether uvicorn is started from repo root or api/
_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILES = (
    str(_ROOT / ".env"),
    str(Path(__file__).resolve().parent / ".env"),
    ".env",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Claude. Production talks to Microsoft Foundry (Anthropic Messages
    # surface at /anthropic, not the OpenAI-shaped /openai/deployments path).
    # Local fallback is a direct Anthropic key until the Foundry resource exists.
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    # Cheaper pass when the wiki/RAG store already has the facts.
    claude_light_model: str = "claude-haiku-4-5"

    # Foundry resource name *or* full base URL, never both. Resource becomes
    # https://<resource>.services.ai.azure.com/anthropic/
    foundry_resource: str = ""
    foundry_base_url: str = ""
    # Prefer Entra in any deployment so there is no Foundry key in .env.
    # Locally a Foundry API key is fine; the two must not be set together.
    foundry_api_key: str = ""
    foundry_use_entra: bool = False
    # Azure Marketplace bills Claude in CCUs. $0.01 per CCU (100 CCU = $1)
    # at Anthropic list rates; token prices below still drive the daily cap.
    foundry_ccu_usd: float = 0.01
    # This `dev` branch prefers the local Anthropic key so a leftover
    # Foundry resource (billing-blocked, 400s) cannot steal chat.
    # Master keeps False: Foundry wins whenever it is configured.
    prefer_anthropic: bool = True

    # Embeddings
    embedding_backend: str = "ollama"  # "ollama" | "voyage"
    voyage_api_key: str = ""
    ollama_url: str = "http://localhost:11434"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "realm_pal"

    # Scopes Redis keys and the Qdrant collection to one deployment, so
    # several environments can share an instance without reading each other's
    # caches. Leave blank for a single-environment setup.
    deployment_namespace: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Scraping. Wiki pages (items, dungeons, skins, equipment hubs) almost
    # never change — serve Redis/Qdrant and refresh on a weekly job
    # (`api/scripts/refresh_wiki.py`), not on every chat turn. Player
    # profiles change constantly, so those scrape on lookup; the short TTL
    # only collapses duplicate hits in one session (sidebar + chat).
    wiki_scrape_ttl_hours: int = 168
    player_scrape_ttl_seconds: int = 120
    scrape_ttl_hours: int = 168
    pet_sprite_ttl_days: int = 7
    # Some real, correctly-named items (a fresh RealmShark DPS leaderboard
    # entry, e.g. Rift Rippers) genuinely have no RealmEye wiki page yet -
    # every lookup for one used to burn a full two-attempt, ~30s Playwright
    # timeout, every single time, since a scrape failure was never cached.
    # Short TTL: long enough that repeat lookups in the same session/day
    # don't re-pay the timeout, short enough that the item shows up on its
    # own within a few hours of RealmEye actually publishing the page.
    missing_item_ttl_seconds: int = 3600

    @property
    def wiki_ttl_seconds(self) -> int:
        return max(1, self.wiki_scrape_ttl_hours) * 3600

    @property
    def player_ttl_seconds(self) -> int:
        return max(0, self.player_scrape_ttl_seconds)

    # Rate limiting. Anonymous callers are keyed on IP and get less than
    # signed-in ones, so signing in beats trying to game the quota.
    # Signed-in free accounts get two more than guests on the same
    # rolling 24h window. The paywall signup slide sells that delta.
    free_message_limit: int = 5
    anonymous_message_limit: int = 3

    # Only enable behind a proxy you control (Container Apps ingress, nginx).
    # X-Forwarded-For is caller-supplied, so trusting it without a known hop
    # count restores the quota bypass this replaced.
    trust_forwarded_for: bool = False
    forwarded_proxy_hops: int = 1

    # Keys the hashes used for quota buckets so raw IPs never hit Redis.
    # Falls back to jwt_secret when unset; set it explicitly in production.
    pii_hash_secret: str = ""

    # Daily ceiling for paid accounts. Abuse fuse, not expected use.
    paid_message_limit: int = 50
    # Claude replies included in the $7 plan (~$2.50 at ~$0.0365/reply).
    # Stored answers do not count. Old default was 90.
    paid_claude_included: int = 68
    # Price of one Claude reply after the included pool.
    claude_overage_usd: float = 0.08

    # Burst limit for scrape-triggering lookups (players/items/dungeons/
    # skins/sprite). A cache miss launches a real headless browser behind a
    # single-Chromium semaphore, so an unthrottled caller queues everyone
    # else's lookups behind their own flood. Short window, not a daily cap.
    lookup_rate_limit_anonymous: int = 12
    lookup_rate_limit_user: int = 40
    lookup_rate_window_seconds: int = 60

    # Burst limit on /chat/stream itself, including stored (no-Claude) turns.
    # The daily in-depth quota only meters model calls; without this, a
    # guest at that cap could hammer stored lookups with no ceiling.
    chat_burst_limit_anonymous: int = 20
    chat_burst_limit_user: int = 60
    chat_burst_window_seconds: int = 60

    # --- Cost ceilings ---
    # Per-identity quotas stop one abuser; they don't stop a crowd. Once the
    # day's recorded spend reaches this, chat refuses new work until tomorrow.
    monthly_cost_budget_usd: float = 20.0
    # Claude pricing per million tokens. Foundry CCU is these rates converted
    # at foundry_ccu_usd; keep them in lockstep with claude_model.
    model_input_cost_per_mtok_usd: float = 3.0
    model_output_cost_per_mtok_usd: float = 15.0
    light_model_input_cost_per_mtok_usd: float = 1.0
    light_model_output_cost_per_mtok_usd: float = 5.0
    # Bounds the worst case for a single response.
    max_response_tokens: int = 4096
    anthropic_timeout_seconds: float = 120.0
    # Static off switch. The Redis kill switch is preferred | it takes effect
    # without a redeploy.
    chat_enabled: bool = True

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""

    # Durable store backend (api/services/db.py) for entitlements, accounts,
    # uploads, billing prefs, and product_feedback. Empty: SQLite files under data/, good for
    # local dev and tests, no infra dependency. Set to a `postgresql://...`
    # DSN (e.g. Azure Database for PostgreSQL) in any deployment with more
    # than one Container Apps replica - SQLite on a shared volume is not
    # safe with concurrent writers. Until Sep 13, 2026 this was planned as
    # "SQLite on a mounted volume until billing lands, then Postgres" (see
    # BACKLOG.md history); billing landed that day, so this is that move.
    database_url: str = ""

    # Durable entitlement store (api/services/entitlements.py). Stripe
    # webhooks write here; the chat path reads it instead of trusting a
    # magic-link JWT's `paid` claim for its whole lifetime with no way to
    # revoke it early. Path used only for the SQLite backend above.
    entitlements_db_path: str = "data/entitlements.db"

    # Local email+password accounts (api/services/accounts.py). Separate
    # from entitlements so a paid Stripe row can exist for an email that
    # has never registered here (legacy magic-link customers), and a
    # registered free account can exist with no entitlement row at all.
    accounts_db_path: str = "data/accounts.db"

    # Uploaded chat images (api/services/uploads.py). Recycled after
    # upload_ttl_days so the blob store cannot grow without bound.
    uploads_db_path: str = "data/uploads.db"
    upload_ttl_days: int = 7
    upload_max_bytes: int = 4_000_000

    # Server-side chat history sync for signed-in accounts
    # (api/services/chat_sessions.py). Chats used to live only in browser
    # localStorage, which an incognito window's last-tab-closed cleanup
    # wipes even though the account itself is untouched - "sign in, chat,
    # close incognito, sign back in" looked like history vanishing. This
    # makes the account (not the browser) the unit of persistence for
    # signed-in users; anonymous/guest chats stay local-only (no email to
    # key a row on). Capped per account so one browser can't grow the table
    # without bound.
    chat_sessions_db_path: str = "data/chat_sessions.db"
    chat_sessions_max_per_account: int = 200

    # Site-level Feedback modal (not per-message thumbs). SQLite file locally;
    # same Azure Postgres database as the other stores when DATABASE_URL is set.
    # Scan with: SELECT * FROM product_feedback ORDER BY created_at DESC;
    product_feedback_db_path: str = "data/product_feedback.db"
    product_feedback_limit: int = 5
    product_feedback_window_seconds: int = 3600

    # Admin notifications feed (Claude turn costs). Same DATABASE_URL as the
    # other stores when set; SQLite file locally.
    admin_events_db_path: str = "data/admin_events.db"
    # Comma-separated IGNs / emails that may open the admin notifications
    # modal. Server-checked on every /admin call. Default is the founder IGN.
    admin_igns: str = "Turbine"
    admin_emails: str = ""

    # Auth (magic link JWT) | legacy, being replaced by the identity provider
    # below. Kept so existing paid tokens keep working during the migration.
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_days: int = 30

    # Magic links used to be signed with jwt_secret, the same secret that
    # signs every session token. That meant a link leaked from one channel
    # (email logs, a referrer header, a browser history sync) was equally
    # useful for forging a session. Falls back to jwt_secret only so nothing
    # breaks before this is set; set it explicitly in any real deployment.
    magic_link_secret: str = ""
    magic_link_ttl_minutes: int = 30

    # Identity provider (Entra External ID, Supabase Auth, Clerk, Cognito |
    # anything that publishes a JWKS endpoint). Leave blank to run anonymously,
    # which is the local-dev default. `auth_provider` is informational only;
    # verification is driven entirely by the JWKS/issuer/audience trio.
    auth_provider: str = ""
    auth_jwks_url: str = ""
    auth_issuer: str = ""
    auth_audience: str = ""
    # Comma-separated. Asymmetric only | see api/identity.py for why.
    auth_algorithms: str = "RS256,ES256"
    auth_jwks_cache_seconds: int = 600

    # App
    app_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"
    # Comma-separated extra origins CORS should also accept, on top of
    # `app_url`. For a hosting/domain cutover (e.g. the *.azurestaticapps.net
    # URL while a custom domain's DNS/TLS is still propagating, or both the
    # apex and `www` custom domains at once). `app_url` stays the single
    # canonical URL used for redirects, magic links, and Stripe return URLs.
    extra_cors_origins: str = ""
    debug: bool = False
    # Comma-separated IGNs that skip chat + lookup quotas, for the handful of
    # named test accounts we actually control (e.g. the founder's own IGN).
    # Until Sep 14, 2026 this also required DEBUG=true, which meant unlocking
    # it in production dragged in DEBUG's other side effects too (public
    # /docs, muted secret-rotation warnings) - see debug_unlimited_ign_set
    # history below. It's now its own explicit opt-in: setting this env var
    # alone is enough, in any environment. Leave unset in prod unless you
    # mean to name someone.
    debug_unlimited_igns: str = ""

    @property
    def debug_unlimited_ign_set(self) -> frozenset[str]:
        # History: until Sep 14, 2026 this returned frozenset() unless
        # settings.debug was also True, so the only way to use it live was to
        # flip DEBUG=true - which also publicly exposes /docs and silences
        # the JWT-secret/Anthropic-key warnings in _warn_on_default_secrets /
        # _warn_on_llm_config. Decoupled so naming a tester doesn't require
        # accepting those unrelated debug-mode side effects.
        return frozenset(
            name.strip().lower()
            for name in self.debug_unlimited_igns.split(",")
            if name.strip()
        )

    @property
    def admin_ign_set(self) -> frozenset[str]:
        return frozenset(
            name.strip().lower()
            for name in self.admin_igns.split(",")
            if name.strip()
        )

    @property
    def admin_email_set(self) -> frozenset[str]:
        return frozenset(
            name.strip().lower()
            for name in self.admin_emails.split(",")
            if name.strip()
        )

    @property
    def foundry_configured(self) -> bool:
        """True when chat should use the Foundry Anthropic surface."""
        return bool(self.foundry_resource.strip() or self.foundry_base_url.strip())

    @property
    def llm_provider(self) -> str:
        """Which backend `_stream_response` will call: foundry or anthropic."""
        if self.prefer_anthropic and self.anthropic_api_key.strip():
            return "anthropic"
        return "foundry" if self.foundry_configured else "anthropic"

    @property
    def foundry_auth(self) -> str:
        """How Foundry is authenticated, or empty when it isn't in use."""
        if not self.foundry_configured:
            return ""
        return "entra" if self.foundry_use_entra else "api_key"

    @property
    def daily_cost_budget_micros(self) -> int:
        """
        Daily spend ceiling in micro-dollars.

        A flat 30ths split of the monthly budget rather than a calendar-aware
        one: the point is a predictable daily cap, not exact monthly accrual.
        """
        return max(0, round(self.monthly_cost_budget_usd / 30 * 1_000_000))

    @property
    def namespace_slug(self) -> str:
        """Normalized deployment namespace, safe for use in identifiers."""
        return "".join(
            c for c in self.deployment_namespace.strip().lower() if c.isalnum() or c == "_"
        )

    @property
    def qdrant_collection_name(self) -> str:
        """
        The collection to read and write. Namespacing lives here rather than
        at the call sites so `qdrant_collection` is honoured everywhere | it
        used to be defined and then ignored, with "realm_pal" hardcoded in
        both the ingestion and retrieval paths.
        """
        slug = self.namespace_slug
        return f"{self.qdrant_collection}_{slug}" if slug else self.qdrant_collection

    @property
    def redis_key_prefix(self) -> str:
        """Prefix applied to every Redis key. Empty means no namespacing."""
        slug = self.namespace_slug
        return f"{slug}:" if slug else ""

    @property
    def auth_algorithm_list(self) -> tuple[str, ...]:
        """Allowed signing algorithms, filtered to the asymmetric ones."""
        from .identity import SUPPORTED_ALGORITHMS

        requested = [a.strip().upper() for a in self.auth_algorithms.split(",") if a.strip()]
        return tuple(a for a in requested if a in SUPPORTED_ALGORITHMS)

    @property
    def stripe_configured(self) -> bool:
        """True only when Checkout can actually create a session."""
        key = self.stripe_secret_key.strip()
        price = self.stripe_price_id.strip()
        if not key or not price or "..." in key or "..." in price:
            return False
        return price.startswith("price_")

    @property
    def auth_configured(self) -> bool:
        """True only when every field verification needs is present."""
        return bool(
            self.auth_jwks_url
            and self.auth_issuer
            and self.auth_audience
            and self.auth_algorithm_list
        )

    @property
    def cors_allowed_origins(self) -> list[str]:
        """
        Origins the API answers CORS preflights for.

        `app_url` plus any `extra_cors_origins` are the only origins in
        production. `localhost:3000` is added only in debug — it used to be
        hardcoded unconditionally, which meant a deployed API would accept
        credentialed requests from anyone running the frontend locally
        against it.
        """
        origins = [self.app_url]
        for extra in self.extra_cors_origins.split(","):
            extra = extra.strip()
            if extra and extra not in origins:
                origins.append(extra)
        if self.debug and "http://localhost:3000" not in origins:
            origins.append("http://localhost:3000")
        return origins

    @property
    def uses_default_jwt_secret(self) -> bool:
        """True if JWT_SECRET was never rotated off the shipped placeholder."""
        return self.jwt_secret.strip() == "change-me-in-production"

    @property
    def effective_magic_link_secret(self) -> str:
        """MAGIC_LINK_SECRET if set, else the session secret as a fallback."""
        return self.magic_link_secret.strip() or self.jwt_secret

    @property
    def magic_link_secret_is_shared(self) -> bool:
        """True while magic links still ride on the session-signing secret."""
        return not self.magic_link_secret.strip()

    @model_validator(mode="after")
    def _require_llm_credentials(self) -> "Settings":
        """
        Fail closed if chat has nowhere to send tokens.

        Foundry is preferred when a resource or base URL is set. Direct
        Anthropic is the local fallback. Mixing Foundry target fields, or
        mixing Entra with a Foundry key, is a misconfiguration rather than a
        silent preference.
        """
        resource = self.foundry_resource.strip()
        base_url = self.foundry_base_url.strip()
        if resource and base_url:
            raise ValueError(
                "FOUNDRY_RESOURCE and FOUNDRY_BASE_URL are mutually exclusive"
            )
        if self.foundry_use_entra and self.foundry_api_key.strip():
            raise ValueError(
                "FOUNDRY_USE_ENTRA and FOUNDRY_API_KEY are mutually exclusive; "
                "prefer Entra in production so no Foundry key lives in the environment"
            )
        if resource or base_url:
            from .services.llm import validate_foundry_target

            validate_foundry_target(resource=resource, base_url=base_url)
            if not self.foundry_use_entra and not self.foundry_api_key.strip():
                raise ValueError(
                    "Foundry needs FOUNDRY_USE_ENTRA=true or FOUNDRY_API_KEY"
                )
            return self
        if not self.anthropic_api_key.strip():
            raise ValueError(
                "Set ANTHROPIC_API_KEY for local fallback, or configure Foundry "
                "(FOUNDRY_RESOURCE or FOUNDRY_BASE_URL plus Entra or a Foundry key)"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
