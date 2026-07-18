"""Text embedding service for semantic search."""

from __future__ import annotations

import hashlib
import logging

import httpx

logger = logging.getLogger(__name__)


def _mock_embedding(text: str, dim: int = 1536) -> list[float]:
    """Generate a deterministic mock embedding for testing."""
    h = hashlib.sha256(text.encode()).digest()
    values: list[float] = []
    for i in range(dim):
        byte_val = h[i % len(h)]
        values.append((byte_val / 128.0) - 1.0)
    norm = sum(v**2 for v in values) ** 0.5
    if norm == 0:
        return [0.0] * dim
    return [v / norm for v in values]


class EmbeddingService:
    """Generates text embeddings for semantic search."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        if not api_key:
            logger.warning("No API key provided. EmbeddingService will use mock embeddings. Semantic/hybrid search will fall back to keyword mode.")

    @property
    def is_mock(self) -> bool:
        return self._api_key is None or self._api_key == ""

    @property
    def _use_mock(self) -> bool:
        return self.is_mock

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        if self._use_mock:
            logger.warning("Embedding service running in mock mode (no API key). Semantic search disabled.")
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []

        if self._use_mock:
            return [_mock_embedding(t) for t in texts]

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"input": texts, "model": self._model},
            )
            resp.raise_for_status()
            data = resp.json()

        # Sort by index to guarantee ordering matches input
        sorted_items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_items]
