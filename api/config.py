from functools import lru_cache
from pathlib import Path

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

    # Anthropic
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-6"

    # Embeddings
    embedding_backend: str = "ollama"  # "ollama" | "voyage"
    voyage_api_key: str = ""
    ollama_url: str = "http://localhost:11434"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "realm_pal"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Scraping
    scrape_ttl_hours: int = 24
    pet_sprite_ttl_days: int = 7

    # Rate limiting. Anonymous callers are keyed on IP and get less than
    # signed-in ones, so signing in beats trying to game the quota.
    free_message_limit: int = 10
    anonymous_message_limit: int = 3

    # Only enable behind a proxy you control (Container Apps ingress, nginx).
    # X-Forwarded-For is caller-supplied, so trusting it without a known hop
    # count restores the quota bypass this replaced.
    trust_forwarded_for: bool = False
    forwarded_proxy_hops: int = 1

    # Keys the hashes used for quota buckets so raw IPs never hit Redis.
    # Falls back to jwt_secret when unset; set it explicitly in production.
    pii_hash_secret: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""

    # Auth (magic link JWT) | legacy, being replaced by the identity provider
    # below. Kept so existing paid tokens keep working during the migration.
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_days: int = 30

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
    debug: bool = False

    @property
    def auth_algorithm_list(self) -> tuple[str, ...]:
        """Allowed signing algorithms, filtered to the asymmetric ones."""
        from .identity import SUPPORTED_ALGORITHMS

        requested = [a.strip().upper() for a in self.auth_algorithms.split(",") if a.strip()]
        return tuple(a for a in requested if a in SUPPORTED_ALGORITHMS)

    @property
    def auth_configured(self) -> bool:
        """True only when every field verification needs is present."""
        return bool(
            self.auth_jwks_url
            and self.auth_issuer
            and self.auth_audience
            and self.auth_algorithm_list
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
