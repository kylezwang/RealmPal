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

BACKEND = os.getenv("EMBEDDING_BACKEND", "ollama")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
# 768 for Ollama's nomic-embed-text, 1024 for Voyage's voyage-4-lite default
# output_dimension. `ingestion.py` imports this rather than redeclaring it -
# must match the actual live Qdrant collection's configured vector size,
# see this module's docstring.
VECTOR_SIZE = 1024 if BACKEND == "voyage" else 768


async def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Return a list of embedding vectors for the given texts."""
    if BACKEND == "voyage":
        return await _embed_voyage(list(texts))
    return await _embed_ollama(list(texts))


async def _embed_ollama(texts: list[str]) -> list[list[float]]:
    """Embed using local Ollama nomic-embed-text model."""
    vectors = []
    async with httpx.AsyncClient(timeout=30) as client:
        for text in texts:
            resp = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
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
    dims, matching VECTOR_SIZE above.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {VOYAGE_API_KEY}"},
            json={"model": "voyage-4-lite", "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]
