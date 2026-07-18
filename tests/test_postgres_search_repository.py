from app.services.search.repository import PostgresSearchRepository


class KeywordChunkRepository:
    def __init__(self):
        self.calls = []

    def search_search_chunks(self, *, tenant_id, terms, limit):
        self.calls.append((tenant_id, terms, limit))
        return [
            {
                "invoice_id": "document-10000",
                "chunk_index": 2,
                "content": "株式会社テスト 合計 1200",
                "metadata": {
                    "_chunk_id": "document-10000:2",
                    "_chunk_type": "overview",
                    "tenant_id": tenant_id,
                },
                "score": 1.0,
            }
        ]

    def list_invoices(self, **_kwargs):
        raise AssertionError("keyword search must not reconstruct a bounded invoice list")


def test_keyword_search_uses_tenant_chunk_query_without_document_cap():
    repository = KeywordChunkRepository()

    results = PostgresSearchRepository(repository).search(
        "株式会社テスト",
        mode="keyword",
        tenant_id="tenant-a",
    )

    assert repository.calls == [("tenant-a", ["株式会社テスト"], 20)]
    assert [(result.document_id, result.score, result.mode) for result in results] == [
        ("document-10000", 1.0, "keyword")
    ]
