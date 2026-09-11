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

    # Rate limiting
    free_message_limit: int = 3

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""

    # Auth (magic link JWT)
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_days: int = 30

    # App
    app_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
