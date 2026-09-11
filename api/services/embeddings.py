"""
Embedding abstraction layer.

Supports two backends:
  1. Ollama (local, free) | nomic-embed-text  [default for dev]
  2. Voyage AI via Anthropic | voyage-3-lite  [recommended for prod]

Switch via EMBEDDING_BACKEND env var: "ollama" | "voyage"
"""
import os
from typing import Sequence

import httpx
from loguru import logger

BACKEND = os.getenv("EMBEDDING_BACKEND", "ollama")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
VECTOR_SIZE = 768


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
    """Embed using Voyage AI voyage-3-lite (via direct API)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {VOYAGE_API_KEY}"},
            json={"model": "voyage-3-lite", "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]
