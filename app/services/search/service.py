"""High-level search service."""

from __future__ import annotations

from typing import Any

from app.services.search.chunker import DocumentChunk, chunk_document
from app.services.search.embeddings import EmbeddingService
from app.services.search.repository import SearchRepository, SearchResult


class SearchService:
    """High-level search service."""

    def __init__(
        self, repository: SearchRepository, embedding_service: EmbeddingService
    ) -> None:
        self._repo = repository
        self._embed = embedding_service

    async def index_document(
        self,
        document_id: str,
        extracted_json: dict[str, Any],
        ocr_lines: list[dict[str, Any]] | None = None,
    ) -> int:
        """Chunk and index a document. Returns number of chunks indexed."""
        chunks = chunk_document(document_id, extracted_json, ocr_lines)

        # Generate embeddings for all chunks
        texts = [c.text for c in chunks]
        embeddings = await self._embed.embed_batch(texts)
        for chunk, emb in zip(chunks, embeddings):
            chunk.embedding = emb

        self._repo.index_chunks(chunks)
        return len(chunks)

    async def search(
        self,
        query: str,
        mode: str = "hybrid",
        alpha: float = 0.7,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Search with query embedding generated on the fly."""
        query_embedding: list[float] | None = None
        if mode in ("semantic", "hybrid"):
            query_embedding = await self._embed.embed(query)

        return self._repo.search(
            query=query,
            query_embedding=query_embedding,
            mode=mode,
            alpha=alpha,
            limit=limit,
        )

    async def remove_document(self, document_id: str) -> None:
        """Remove a document from the index."""
        self._repo.remove_document(document_id)
