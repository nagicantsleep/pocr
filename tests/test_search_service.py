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

    results, eff_mode, degraded = await svc.search("hosting", mode="keyword")
    assert len(results) > 0
    assert any("hosting" in r.text.lower() for r in results)


@pytest.mark.asyncio
async def test_semantic_search_returns_sorted_results(svc):
    await svc.index_document("d1", SAMPLE_DOC)
    await svc.index_document("d2", {"issuer_name": "Other Vendor", "date": "2023-01-01"})

    results, eff_mode, degraded = await svc.search("cloud hosting", mode="semantic")
    assert len(results) > 0
    # Scores should be descending
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_hybrid_search_falls_back_to_keyword_with_mock(svc):
    await svc.index_document("d1", SAMPLE_DOC)

    results, eff_mode, degraded = await svc.search("Acme hosting", mode="hybrid")
    assert len(results) > 0
    # With mock embeddings, hybrid falls back to keyword
    assert results[0].mode == "keyword"
    assert eff_mode == "keyword"
    assert degraded is True
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_remove_document_removes_chunks(svc):
    await svc.index_document("d1", SAMPLE_DOC)
    results_before, _, _ = await svc.search("Acme", mode="keyword")
    assert len(results_before) > 0

    await svc.remove_document("d1")
    results_after, _, _ = await svc.search("Acme", mode="keyword")
    assert len(results_after) == 0


@pytest.mark.asyncio
async def test_empty_query_returns_no_results(svc):
    await svc.index_document("d1", SAMPLE_DOC)
    results, _, _ = await svc.search("", mode="keyword")
    assert results == []


@pytest.mark.asyncio
async def test_limit_returns_only_top_results(svc):
    await svc.index_document("d1", SAMPLE_DOC)
    results, _, _ = await svc.search("Acme Corp hosting support", mode="keyword", limit=1)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_semantic_falls_back_to_keyword_with_mock_embedder(svc):
    """Semantic search must fall back to keyword when embeddings are mock."""
    await svc.index_document("d1", SAMPLE_DOC)

    results, eff_mode, degraded = await svc.search("hosting", mode="semantic")
    assert len(results) > 0
    assert all(r.mode == "keyword" for r in results)
    assert eff_mode == "keyword"
    assert degraded is True


@pytest.mark.asyncio
async def test_hybrid_falls_back_to_keyword_with_mock_embedder(svc):
    """Hybrid search must fall back to keyword when embeddings are mock."""
    await svc.index_document("d1", SAMPLE_DOC)

    results, eff_mode, degraded = await svc.search("hosting", mode="hybrid")
    assert len(results) > 0
    assert all(r.mode == "keyword" for r in results)
    assert eff_mode == "keyword"
    assert degraded is True
