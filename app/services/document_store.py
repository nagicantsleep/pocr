from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class StoredDocument:
    """A stored document for review."""

    id: str
    document_type: str
    structured_json: dict
    confidence: float
    needs_review: bool
    review_status: str  # "pending", "approved", "rejected", "needs_review"
    created_at: datetime
    updated_at: datetime
    reviewed_by: str | None = None
    review_reason: str | None = None
    tenant_id: str = "development"


class DocumentStore:
    """In-memory document store for review workflow."""

    def __init__(self) -> None:
        self._documents: dict[str, StoredDocument] = {}

    def store(self, document: StoredDocument) -> None:
        self._documents[document.id] = document

    def delete(self, document_id: str, tenant_id: str | None = None) -> bool:
        """Remove a document from the store. Returns True if it existed."""
        document = self._documents.get(document_id)
        if document is None or (tenant_id is not None and document.tenant_id != tenant_id):
            return False
        del self._documents[document_id]
        return True

    def get(self, document_id: str, tenant_id: str | None = None) -> StoredDocument | None:
        document = self._documents.get(document_id)
        if document is None or (tenant_id is not None and document.tenant_id != tenant_id):
            return None
        return document

    def list_documents(
        self,
        review_status: str | None = None,
        document_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
        tenant_id: str | None = None,
    ) -> list[StoredDocument]:
        filtered = list(self._documents.values())
        if tenant_id is not None:
            filtered = [document for document in filtered if document.tenant_id == tenant_id]
        if review_status is not None:
            filtered = [d for d in filtered if d.review_status == review_status]
        if document_type is not None:
            filtered = [d for d in filtered if d.document_type == document_type]
        return filtered[offset : offset + limit]

    def count(
        self,
        review_status: str | None = None,
        document_type: str | None = None,
        tenant_id: str | None = None,
    ) -> int:
        filtered = self._documents.values()
        if tenant_id is not None:
            filtered = [document for document in filtered if document.tenant_id == tenant_id]
        if review_status is not None:
            filtered = [d for d in filtered if d.review_status == review_status]
        if document_type is not None:
            filtered = [d for d in filtered if d.document_type == document_type]
        return len(filtered)

    def update_status(
        self,
        document_id: str,
        status: str,
        actor: str,
        reason: str | None = None,
        tenant_id: str | None = None,
    ) -> StoredDocument | None:
        doc = self.get(document_id, tenant_id)
        if doc is None:
            return None
        doc.review_status = status
        doc.reviewed_by = actor
        doc.review_reason = reason
        doc.updated_at = datetime.now(timezone.utc)
        return doc

    def patch_fields(
        self,
        document_id: str,
        fields: dict,
        actor: str,
        tenant_id: str | None = None,
    ) -> StoredDocument | None:
        doc = self.get(document_id, tenant_id)
        if doc is None:
            return None
        doc.structured_json.update(fields)
        doc.reviewed_by = actor
        doc.updated_at = datetime.now(timezone.utc)
        return doc
