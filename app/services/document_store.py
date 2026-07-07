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


class DocumentStore:
    """In-memory document store for review workflow."""

    def __init__(self) -> None:
        self._documents: dict[str, StoredDocument] = {}

    def store(self, document: StoredDocument) -> None:
        self._documents[document.id] = document

    def get(self, document_id: str) -> StoredDocument | None:
        return self._documents.get(document_id)

    def list_documents(
        self,
        review_status: str | None = None,
        document_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StoredDocument]:
        filtered = list(self._documents.values())
        if review_status is not None:
            filtered = [d for d in filtered if d.review_status == review_status]
        if document_type is not None:
            filtered = [d for d in filtered if d.document_type == document_type]
        return filtered[offset : offset + limit]

    def count(self, review_status: str | None = None) -> int:
        if review_status is not None:
            return sum(
                1 for d in self._documents.values() if d.review_status == review_status
            )
        return len(self._documents)

    def update_status(
        self,
        document_id: str,
        status: str,
        actor: str,
        reason: str | None = None,
    ) -> StoredDocument | None:
        doc = self._documents.get(document_id)
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
    ) -> StoredDocument | None:
        doc = self._documents.get(document_id)
        if doc is None:
            return None
        doc.structured_json.update(fields)
        doc.reviewed_by = actor
        doc.updated_at = datetime.now(timezone.utc)
        return doc
