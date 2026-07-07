"""Tests for search service: indexing, search modes, and removal."""

from __future__ import annotations

import pytest

from app.services.search.embeddings import EmbeddingService
from app.services.search.repository import SearchRepository
from app.services.search.service import SearchService


@pytest.fixture
def svc():
    repo = SearchRepository()
    embed = EmbeddingService(api_key=None)  # mock mode
    return SearchService(repo, embed)


SAMPLE_DOC = {
    "issuer_name": "Acme Corp",
    "date": "2024-06-15",
    "total_amount": 5000,
    "line_items": [
        {"description": "Cloud hosting Q2", "amount": 3000},
        {"description": "Support contract", "amount": 2000},
    ],
}


@pytest.mark.asyncio
async def test_index_document_stores_chunks(svc):
    count = await svc.index_document("d1", SAMPLE_DOC)
    assert count >= 4  # header + 2 line items + overview


@pytest.mark.asyncio
async def test_keyword_search_finds_matching_text(svc):
    await svc.index_document("d1", SAMPLE_DOC)

    results = await svc.search("hosting", mode="keyword")
    assert len(results) > 0
    assert any("hosting" in r.text.lower() for r in results)


@pytest.mark.asyncio
async def test_semantic_search_returns_sorted_results(svc):
    await svc.index_document("d1", SAMPLE_DOC)
    await svc.index_document("d2", {"issuer_name": "Other Vendor", "date": "2023-01-01"})

    results = await svc.search("cloud hosting", mode="semantic")
    assert len(results) > 0
    # Scores should be descending
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_hybrid_search_combines_scores(svc):
    await svc.index_document("d1", SAMPLE_DOC)

    results = await svc.search("Acme hosting", mode="hybrid")
    assert len(results) > 0
    assert results[0].mode == "hybrid"
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_remove_document_removes_chunks(svc):
    await svc.index_document("d1", SAMPLE_DOC)
    results_before = await svc.search("Acme", mode="keyword")
    assert len(results_before) > 0

    await svc.remove_document("d1")
    results_after = await svc.search("Acme", mode="keyword")
    assert len(results_after) == 0


@pytest.mark.asyncio
async def test_empty_query_returns_no_results(svc):
    await svc.index_document("d1", SAMPLE_DOC)
    results = await svc.search("", mode="keyword")
    assert results == []


@pytest.mark.asyncio
async def test_limit_returns_only_top_results(svc):
    await svc.index_document("d1", SAMPLE_DOC)
    results = await svc.search("Acme Corp hosting support", mode="keyword", limit=1)
    assert len(results) == 1
