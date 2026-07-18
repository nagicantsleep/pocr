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
        tenant_id: str | None = None,
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
        chunks = self._chunks.values()
        if tenant_id is not None:
            chunks = (
                chunk
                for chunk in chunks
                if chunk.metadata.get("tenant_id") == tenant_id
            )

        if mode == "keyword":
            for chunk in chunks:
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
            for chunk in chunks:
                if chunk.embedding is None:
                    continue
                raw_score = _cosine_similarity(query_embedding, chunk.embedding)
                score = max(0.0, min(1.0, (raw_score + 1.0) / 2.0))
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
                for chunk in chunks:
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
                for chunk in chunks:
                    kw_score = self._keyword_score(query, chunk.text)
                    sem_score = 0.0
                    if chunk.embedding is not None:
                        raw_sem = _cosine_similarity(query_embedding, chunk.embedding)
                        sem_score = max(0.0, min(1.0, (raw_sem + 1.0) / 2.0))
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


class PostgresSearchRepository:
    """Durable tenant-scoped chunks maintained by the invoice event worker."""

    def __init__(self, repository: Any | None = None) -> None:
        from app.repositories.invoice_repository import get_invoice_repository

        self._repository = repository or get_invoice_repository()

    def index_chunks(self, chunks: list[DocumentChunk]) -> None:
        """Atomically replace one document projection for its tenant."""
        if not chunks:
            return
        tenant_id = chunks[0].metadata.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise ValueError("durable search chunks require tenant_id metadata")
        document_id = chunks[0].document_id
        if any(
            chunk.document_id != document_id
            or chunk.metadata.get("tenant_id") != tenant_id
            for chunk in chunks
        ):
            raise ValueError("all chunks must belong to one tenant document")

        self._repository.save_search_chunks(
            document_id,
            tenant_id=tenant_id,
            chunks=[
                {
                    "content": chunk.text,
                    "metadata": {
                        **chunk.metadata,
                        "_chunk_id": chunk.chunk_id,
                        "_chunk_type": chunk.chunk_type,
                        "_embedding": chunk.embedding,
                    },
                }
                for chunk in chunks
            ],
        )

    def remove_document(self, document_id: str) -> None:
        raise RuntimeError(
            "durable search deletion requires tenant_id; use the repository directly"
        )

    def search(
        self,
        query: str,
        query_embedding: list[float] | None = None,
        mode: str = "hybrid",
        alpha: float = 0.7,
        limit: int = 20,
        tenant_id: str | None = None,
    ) -> list[SearchResult]:
        """Read one tenant's durable projection and preserve current ranking behavior."""
        if not tenant_id or not query.strip():
            return []
        if mode == "keyword":
            rows = self._repository.search_search_chunks(
                tenant_id=tenant_id,
                terms=_tokenize(query),
                limit=limit,
            )
            return [
                SearchResult(
                    document_id=row["invoice_id"],
                    chunk_id=row["metadata"].get(
                        "_chunk_id",
                        f"{row['invoice_id']}:{row['chunk_index']}",
                    ),
                    text=row["content"],
                    score=row["score"],
                    mode="keyword",
                    metadata={
                        key: value
                        for key, value in row["metadata"].items()
                        if not key.startswith("_")
                    },
                )
                for row in rows
            ]
        invoice_ids = self._repository.list_invoices(
            tenant_id=tenant_id,
            limit=200,
            offset=0,
        )[0]

        transient = SearchRepository()
        for invoice in invoice_ids:
            document_id = invoice["id"]
            chunks = self._repository.list_search_chunks(document_id, tenant_id=tenant_id)
            transient.index_chunks(
                [
                DocumentChunk(
                    chunk_id=chunk["metadata"].get("_chunk_id", f"{document_id}:{chunk['chunk_index']}"),
                    document_id=document_id,
                    chunk_type=chunk["metadata"].get("_chunk_type", "paragraph"),
                    text=chunk["content"],
                    metadata={
                        key: value
                        for key, value in chunk["metadata"].items()
                        if not key.startswith("_")
                    },
                    embedding=chunk["metadata"].get("_embedding"),
                )
                for chunk in chunks
            ]
            )
        # ponytail: semantic/hybrid still reconstruct up to 200 documents;
        # replace JSON embeddings with a tenant-scoped vector index before those modes need 10k scale.
        return transient.search(query, query_embedding, mode, alpha, limit, tenant_id)
