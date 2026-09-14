"""
Embedding abstraction layer.

Supports two backends:
  1. Ollama (local, free) | nomic-embed-text, 768 dims  [default for dev]
  2. Voyage AI via Anthropic | voyage-4-lite, 1024 dims  [recommended for prod]

Switch via EMBEDDING_BACKEND env var: "ollama" | "voyage"

IMPORTANT: the two backends do NOT share a vector space or dimension - a
Qdrant collection seeded with one cannot be queried with the other (the
old `voyage-3-lite` note here claimed dimension compatibility with Ollama;
that was never actually verified against a live Voyage call and is wrong -
voyage-3-lite is a fixed 512 dims, voyage-4-lite defaults to 1024, neither
is 768). Switching backends in production requires recreating the Qdrant
collection at the new VECTOR_SIZE and re-running every seed script - see
BACKLOG.md's embeddings-backend entry for the exact steps.
"""
import os
from typing import Sequence

import httpx
from loguru import logger

from ..config import get_settings

# NOTE: read fresh from get_settings() inside each function below, not as
# module-level constants computed once via os.getenv(). get_settings() is a
# pydantic-settings BaseSettings with `env_file=...` configured (see
# config.py) - it loads values straight out of `.env` without ever touching
# the real process `os.environ`, so a bare `os.getenv("EMBEDDING_BACKEND")`
# silently returns the "ollama" default for anyone using a `.env` file
# instead of real exported shell/container env vars (i.e. every local dev
# setup). This was caught Sep 14 re-seeding Qdrant: `get_settings()` in a
# one-off script correctly reported `voyage`, but this module's old
# `os.getenv()` constant still said `ollama` in the same process.
_LEGACY_BACKEND_FALLBACK = os.getenv("EMBEDDING_BACKEND", "ollama")


def _backend() -> str:
    return get_settings().embedding_backend or _LEGACY_BACKEND_FALLBACK


def vector_size() -> int:
    """768 for Ollama's nomic-embed-text, 1024 for Voyage's voyage-4-lite
    default output_dimension. Must match the actual live Qdrant collection's
    configured vector size - see this module's docstring."""
    return 1024 if _backend() == "voyage" else 768


# Back-compat module-level constant for callers that import it directly
# (`ingestion.py`) - computed once at import time like before. Fine for a
# single process's lifetime (the backend doesn't change mid-run in any real
# deployment), but scripts/tests that need the *current* value after
# changing `.env` mid-session should call `vector_size()` instead.
VECTOR_SIZE = vector_size()


async def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Return a list of embedding vectors for the given texts."""
    if _backend() == "voyage":
        return await _embed_voyage(list(texts))
    return await _embed_ollama(list(texts))


async def _embed_ollama(texts: list[str]) -> list[list[float]]:
    """Embed using local Ollama nomic-embed-text model."""
    ollama_url = get_settings().ollama_url
    vectors = []
    async with httpx.AsyncClient(timeout=30) as client:
        for text in texts:
            resp = await client.post(
                f"{ollama_url}/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": text},
            )
            resp.raise_for_status()
            data = resp.json()
            vectors.append(data["embedding"])
    return vectors


async def _embed_voyage(texts: list[str]) -> list[list[float]]:
    """
    Embed using Voyage AI voyage-4-lite (via direct API).

    voyage-4-lite (not the older voyage-3-lite) specifically: it's the only
    lite-tier model still covered by Voyage's 200M free-token grant per
    account (voyage-3-lite predates that grant), and default output is 1024
    dims, matching vector_size() above.
    """
    api_key = get_settings().voyage_api_key
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "voyage-4-lite", "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]
