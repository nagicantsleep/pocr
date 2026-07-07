"""Search API endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.config import get_settings
from app.services.search.embeddings import EmbeddingService
from app.services.search.repository import SearchRepository
from app.services.search.service import SearchService

router = APIRouter(prefix="/v1/search", tags=["Search"])

# Module-level singletons (in-memory Stage 1)
_repository = SearchRepository()
_embedding_service: EmbeddingService | None = None
_search_service: SearchService | None = None


def _get_search_service() -> SearchService:
    global _embedding_service, _search_service
    if _search_service is None:
        settings = get_settings()
        _embedding_service = EmbeddingService(
            model=settings.SEARCH_EMBEDDING_MODEL,
            api_key=settings.SEARCH_EMBEDDING_API_KEY,
        )
        _search_service = SearchService(_repository, _embedding_service)
    return _search_service


class SearchResultItem(BaseModel):
    document_id: str
    chunk_id: str
    text: str
    score: float
    mode: str
    metadata: dict


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    total: int
    query: str
    mode: str


@router.get("", response_model=SearchResponse)
async def search_documents(
    q: str = Query(..., description="Search query"),
    mode: str = Query("hybrid", enum=["keyword", "semantic", "hybrid"]),
    alpha: float = Query(0.7, ge=0.0, le=1.0),
    limit: int = Query(20, ge=1, le=100),
    svc: SearchService = Depends(_get_search_service),
) -> SearchResponse:
    """Search indexed documents."""
    results = await svc.search(query=q, mode=mode, alpha=alpha, limit=limit)
    items = [
        SearchResultItem(
            document_id=r.document_id,
            chunk_id=r.chunk_id,
            text=r.text,
            score=r.score,
            mode=r.mode,
            metadata=r.metadata,
        )
        for r in results
    ]
    return SearchResponse(results=items, total=len(items), query=q, mode=mode)
