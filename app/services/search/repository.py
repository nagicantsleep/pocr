"""In-memory search repository with keyword and vector search."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.services.search.chunker import DocumentChunk


@dataclass
class SearchResult:
    """A single search result."""

    document_id: str
    chunk_id: str
    text: str
    score: float
    mode: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenize on word boundaries."""
    return re.findall(r"\w+", text.lower())


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SearchRepository:
    """In-memory search with FTS + vector similarity."""

    def __init__(self) -> None:
        self._chunks: dict[str, DocumentChunk] = {}
        self._document_index: dict[str, list[str]] = {}

    def index_chunks(self, chunks: list[DocumentChunk]) -> None:
        """Index document chunks."""
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk
            self._document_index.setdefault(chunk.document_id, [])
            if chunk.chunk_id not in self._document_index[chunk.document_id]:
                self._document_index[chunk.document_id].append(chunk.chunk_id)

    def remove_document(self, document_id: str) -> None:
        """Remove all chunks for a document."""
        chunk_ids = self._document_index.pop(document_id, [])
        for cid in chunk_ids:
            self._chunks.pop(cid, None)

    def search(
        self,
        query: str,
        query_embedding: list[float] | None = None,
        mode: str = "hybrid",
        alpha: float = 0.7,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Search indexed documents.

        Modes:
        - "keyword": text matching with term-frequency scoring
        - "semantic": cosine similarity on embeddings
        - "hybrid": alpha * cosine + (1 - alpha) * keyword_score
        """
        if not query.strip():
            return []

        results: list[SearchResult] = []

        if mode == "keyword":
            for chunk in self._chunks.values():
                score = self._keyword_score(query, chunk.text)
                if score > 0:
                    results.append(
                        SearchResult(
                            document_id=chunk.document_id,
                            chunk_id=chunk.chunk_id,
                            text=chunk.text,
                            score=score,
                            mode="keyword",
                            metadata=chunk.metadata,
                        )
                    )
        elif mode == "semantic":
            if query_embedding is None:
                return []
            for chunk in self._chunks.values():
                if chunk.embedding is None:
                    continue
                score = _cosine_similarity(query_embedding, chunk.embedding)
                if score > 0:
                    results.append(
                        SearchResult(
                            document_id=chunk.document_id,
                            chunk_id=chunk.chunk_id,
                            text=chunk.text,
                            score=score,
                            mode="semantic",
                            metadata=chunk.metadata,
                        )
                    )
        elif mode == "hybrid":
            if query_embedding is None:
                # Fall back to keyword-only
                for chunk in self._chunks.values():
                    score = self._keyword_score(query, chunk.text)
                    if score > 0:
                        results.append(
                            SearchResult(
                                document_id=chunk.document_id,
                                chunk_id=chunk.chunk_id,
                                text=chunk.text,
                                score=(1 - alpha) * score,
                                mode="hybrid",
                                metadata=chunk.metadata,
                            )
                        )
            else:
                for chunk in self._chunks.values():
                    kw_score = self._keyword_score(query, chunk.text)
                    sem_score = 0.0
                    if chunk.embedding is not None:
                        sem_score = _cosine_similarity(query_embedding, chunk.embedding)
                    combined = alpha * sem_score + (1 - alpha) * kw_score
                    if combined > 0:
                        results.append(
                            SearchResult(
                                document_id=chunk.document_id,
                                chunk_id=chunk.chunk_id,
                                text=chunk.text,
                                score=combined,
                                mode="hybrid",
                                metadata=chunk.metadata,
                            )
                        )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    @staticmethod
    def _keyword_score(query: str, text: str) -> float:
        """Score based on fraction of query terms found in text."""
        query_terms = _tokenize(query)
        if not query_terms:
            return 0.0
        text_lower = text.lower()
        matched = sum(1 for t in query_terms if t in text_lower)
        return matched / len(query_terms)
