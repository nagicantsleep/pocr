"""PostgreSQL-backed adapter for the existing JP review document shape."""

from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.invoice_repository import (
    DEFAULT_TENANT_ID,
    InvoiceRepository,
    ReviewStatus,
    get_invoice_repository,
)
from app.services.audit_log import AuditAction, AuditEntry
from app.services.document_store import StoredDocument


_DOCUMENT_METADATA_KEY = "_durable_document"
_REVIEW_STATUS_TO_DOCUMENT = {
    ReviewStatus.AUTO_APPROVED: "approved",
    ReviewStatus.REVIEWED: "approved",
    ReviewStatus.REJECTED: "rejected",
    ReviewStatus.NEEDS_REVIEW: "needs_review",
    ReviewStatus.EXPORTED: "approved",
}
_DOCUMENT_STATUS_TO_REVIEW = {
    "approved": ReviewStatus.REVIEWED,
    "rejected": ReviewStatus.REJECTED,
    "needs_review": ReviewStatus.NEEDS_REVIEW,
    "pending": "pending",
}


class DurableInvoiceService:
    """Durable document/review adapter without changing the StoredDocument contract."""

    def __init__(self, repository: InvoiceRepository | None = None) -> None:
        self._repository = repository or get_invoice_repository()

    @staticmethod
    def _metadata(document: StoredDocument) -> dict:
        return {
            "document_type": document.document_type,
            "confidence": document.confidence,
            "needs_review": document.needs_review,
            "reviewed_by": document.reviewed_by,
            "review_reason": document.review_reason,
        }

    @staticmethod
    def _as_datetime(value: datetime | str | None) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc)

    @classmethod
    def _to_document(cls, invoice: dict) -> StoredDocument:
        validation = invoice.get("validation_json") or {}
        metadata = validation.get(_DOCUMENT_METADATA_KEY, {})
        review_status = _REVIEW_STATUS_TO_DOCUMENT.get(
            invoice["review_status"],
            invoice["review_status"],
        )
        return StoredDocument(
            id=invoice["id"],
            document_type=metadata.get("document_type", "invoice_jp"),
            structured_json=invoice.get("extracted_json") or {},
            confidence=float(metadata.get("confidence", 0.0)),
            needs_review=bool(metadata.get("needs_review", review_status == "needs_review")),
            review_status=review_status,
            created_at=cls._as_datetime(invoice.get("created_at")),
            updated_at=cls._as_datetime(invoice.get("updated_at")),
            reviewed_by=metadata.get("reviewed_by"),
            review_reason=metadata.get("review_reason"),
            tenant_id=invoice["tenant_id"],
        )

    def store_extraction(
        self,
        document: StoredDocument,
        *,
        raw_ocr: dict | None = None,
        source: dict | None = None,
        actor: str = "system",
        reason: str = "",
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
        canonical_response: dict | None = None,
    ) -> StoredDocument:
        """Persist an extraction and its committed notification intent atomically."""
        if not document.id:
            raise ValueError("document.id must be non-empty")
        tenant_id = document.tenant_id or DEFAULT_TENANT_ID
        status = _DOCUMENT_STATUS_TO_REVIEW.get(document.review_status, ReviewStatus.NEEDS_REVIEW)
        invoice_data = {
            "source": source or {},
            "raw_ocr": raw_ocr,
            "extracted": document.structured_json or {},
            "validation": {_DOCUMENT_METADATA_KEY: self._metadata(document)},
            "review_status": status,
        }
        if idempotency_key is not None or request_fingerprint is not None or canonical_response is not None:
            if not (idempotency_key and request_fingerprint and canonical_response is not None):
                raise ValueError("durable idempotency requires key, fingerprint, and canonical response")
            self._repository.save_invoice_and_complete_idempotency(
                invoice_data,
                tenant_id=tenant_id,
                invoice_id=document.id,
                actor=actor,
                reason=reason,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                canonical_response=canonical_response,
            )
        else:
            self._repository.save_invoice(
                invoice_data,
                tenant_id=tenant_id,
                invoice_id=document.id,
                actor=actor,
                reason=reason,
            )
        persisted = self.get(document.id, tenant_id=tenant_id)
        if persisted is None:
            raise RuntimeError("document was committed but cannot be read")
        return persisted

    def claim_idempotency(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        resource_id: str,
        expires_at: datetime,
    ) -> tuple[bool, dict]:
        """Claim a tenant-scoped durable key before storing its extraction."""
        return self._repository.claim_idempotency_record(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            resource_id=resource_id,
            expires_at=expires_at,
        )

    def store_extractions_and_complete_idempotency(
        self,
        documents: list[StoredDocument],
        *,
        sources: list[dict | None],
        raw_ocr_pages: list[dict | None],
        actor: str,
        idempotency_key: str,
        request_fingerprint: str,
        canonical_response: dict,
    ) -> list[StoredDocument]:
        """Commit every PDF page and the canonical response as one durable unit."""
        if not documents:
            raise ValueError("documents must not be empty")
        if len(documents) != len(sources) or len(documents) != len(raw_ocr_pages):
            raise ValueError("documents, sources, and raw_ocr_pages must have equal length")
        tenant_id = documents[0].tenant_id or DEFAULT_TENANT_ID
        if any((document.tenant_id or DEFAULT_TENANT_ID) != tenant_id for document in documents):
            raise ValueError("all documents must belong to the same tenant")

        writes = []
        for document, source, raw_ocr in zip(documents, sources, raw_ocr_pages):
            if not document.id:
                raise ValueError("document.id must be non-empty")
            writes.append(
                {
                    "invoice_id": document.id,
                    "actor": actor,
                    "invoice_data": {
                        "source": source or {},
                        "raw_ocr": raw_ocr,
                        "extracted": document.structured_json or {},
                        "validation": {_DOCUMENT_METADATA_KEY: self._metadata(document)},
                        "review_status": _DOCUMENT_STATUS_TO_REVIEW.get(
                            document.review_status,
                            ReviewStatus.NEEDS_REVIEW,
                        ),
                    },
                }
            )
        self._repository.save_invoices_and_complete_idempotency(
            writes,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            resource_id=documents[0].id,
            canonical_response=canonical_response,
        )
        persisted = [self.get(document.id, tenant_id=tenant_id) for document in documents]
        if any(document is None for document in persisted):
            raise RuntimeError("documents were committed but cannot be read")
        return [document for document in persisted if document is not None]

    def store_extractions(
        self,
        documents: list[StoredDocument],
        *,
        sources: list[dict | None],
        raw_ocr_pages: list[dict | None],
        actor: str,
    ) -> list[StoredDocument]:
        """Commit every PDF page as one durable transaction without idempotency."""
        if not documents:
            raise ValueError("documents must not be empty")
        if len(documents) != len(sources) or len(documents) != len(raw_ocr_pages):
            raise ValueError("documents, sources, and raw_ocr_pages must have equal length")
        tenant_id = documents[0].tenant_id or DEFAULT_TENANT_ID
        if any((document.tenant_id or DEFAULT_TENANT_ID) != tenant_id for document in documents):
            raise ValueError("all documents must belong to the same tenant")

        writes = []
        for document, source, raw_ocr in zip(documents, sources, raw_ocr_pages):
            if not document.id:
                raise ValueError("document.id must be non-empty")
            writes.append(
                {
                    "invoice_id": document.id,
                    "actor": actor,
                    "invoice_data": {
                        "source": source or {},
                        "raw_ocr": raw_ocr,
                        "extracted": document.structured_json or {},
                        "validation": {_DOCUMENT_METADATA_KEY: self._metadata(document)},
                        "review_status": _DOCUMENT_STATUS_TO_REVIEW.get(
                            document.review_status,
                            ReviewStatus.NEEDS_REVIEW,
                        ),
                    },
                }
            )
        self._repository.save_invoices(writes, tenant_id=tenant_id)
        persisted = [self.get(document.id, tenant_id=tenant_id) for document in documents]
        if any(document is None for document in persisted):
            raise RuntimeError("documents were committed but cannot be read")
        return [document for document in persisted if document is not None]

    def release_idempotency(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        resource_id: str,
    ) -> bool:
        return self._repository.release_idempotency_record(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            resource_id=resource_id,
        )

    def get(self, document_id: str, *, tenant_id: str) -> StoredDocument | None:
        invoice = self._repository.get_invoice(document_id, tenant_id=tenant_id)
        return self._to_document(invoice) if invoice is not None else None

    def list(
        self,
        *,
        tenant_id: str,
        review_status: str | None = None,
        document_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[StoredDocument], int]:
        persisted_status = (
            _DOCUMENT_STATUS_TO_REVIEW.get(review_status, review_status)
            if review_status is not None
            else None
        )
        invoices, total = self._repository.list_invoices(
            tenant_id=tenant_id,
            review_status=persisted_status,
            document_type=document_type,
            limit=limit,
            offset=offset,
        )
        return [self._to_document(invoice) for invoice in invoices], total

    def approve(
        self,
        document_id: str,
        *,
        actor: str,
        reason: str | None = None,
        tenant_id: str,
    ) -> StoredDocument:
        return self._review(
            document_id,
            status=ReviewStatus.REVIEWED,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
        )

    def reject(
        self,
        document_id: str,
        *,
        actor: str,
        reason: str | None = None,
        tenant_id: str,
    ) -> StoredDocument:
        return self._review(
            document_id,
            status=ReviewStatus.REJECTED,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
        )

    def _review(
        self,
        document_id: str,
        *,
        status: str,
        actor: str,
        reason: str | None,
        tenant_id: str,
    ) -> StoredDocument:
        existing_invoice = self._repository.get_invoice(document_id, tenant_id=tenant_id)
        if existing_invoice is None:
            raise ValueError(f"Document not found: {document_id}")
        if existing_invoice["review_status"] in {ReviewStatus.REVIEWED, ReviewStatus.REJECTED}:
            raise PermissionError("Document review is already terminal")
        existing = self._to_document(existing_invoice)
        validation = {
            _DOCUMENT_METADATA_KEY: {
                **self._metadata(existing),
                "reviewed_by": actor,
                "review_reason": reason,
            }
        }
        if not self._repository.update_invoice(
            document_id,
            {"review_status": status, "validation_json": validation},
            actor=actor,
            reason=reason or "",
            tenant_id=tenant_id,
            expected_version=existing_invoice["document_version"],
            audit_action=(
                AuditAction.APPROVE.value
                if status == ReviewStatus.REVIEWED
                else AuditAction.REJECT.value
            ),
        ):
            raise RuntimeError("review update lost its document version")
        document = self.get(document_id, tenant_id=tenant_id)
        if document is None:
            raise RuntimeError("review was committed but document cannot be read")
        return document

    def patch(
        self,
        document_id: str,
        *,
        fields: dict,
        actor: str,
        reason: str | None = None,
        force: bool = False,
        tenant_id: str,
    ) -> StoredDocument:
        existing_invoice = self._repository.get_invoice(document_id, tenant_id=tenant_id)
        if existing_invoice is None:
            raise ValueError(f"Document not found: {document_id}")
        existing = self._to_document(existing_invoice)
        if existing.review_status in {"approved", "rejected"} and not force:
            raise PermissionError(
                f"Cannot patch fields on {existing.review_status} document without X-Force header"
            )
        updated_document = StoredDocument(
            **{
                **existing.__dict__,
                "structured_json": {**existing.structured_json, **fields},
                "reviewed_by": actor,
                "review_reason": reason,
            }
        )
        if not self._repository.update_invoice(
            document_id,
            {
                "extracted_json": updated_document.structured_json,
                "validation_json": {_DOCUMENT_METADATA_KEY: self._metadata(updated_document)},
            },
            actor=actor,
            reason=reason or "",
            tenant_id=tenant_id,
            expected_version=existing_invoice["document_version"],
            audit_action=AuditAction.PATCH.value,
        ):
            raise RuntimeError("patch update lost its document version")
        document = self.get(document_id, tenant_id=tenant_id)
        if document is None:
            raise RuntimeError("patch was committed but document cannot be read")
        return document

    def list_audit(
        self,
        document_id: str,
        *,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditEntry], int]:
        return self.list_audit_entries(
            tenant_id=tenant_id,
            document_id=document_id,
            limit=limit,
            offset=offset,
        )

    def list_audit_entries(
        self,
        *,
        tenant_id: str,
        document_id: str | None = None,
        action: AuditAction | str | None = None,
        actor: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditEntry], int]:
        """Return durable audit entries using the existing /v1/audit filters."""
        action_value = action.value if isinstance(action, AuditAction) else action
        records, total = self._repository.list_audit_entries(
            tenant_id=tenant_id,
            document_id=document_id,
            action=action_value,
            actor=actor,
            limit=limit,
            offset=offset,
        )
        entries = [
            AuditEntry(
                id=str(record["id"]),
                document_id=record["invoice_id"],
                action=AuditAction(record["action"])
                if record["action"] in AuditAction._value2member_map_
                else AuditAction.REVIEW,
                actor=record["actor"],
                reason=record["reason"],
                changes=(record["after_json"] or {}).get("extracted_json"),
                created_at=self._as_datetime(record["created_at"]),
                tenant_id=record["tenant_id"],
            )
            for record in records
        ]
        return entries, total


_durable_invoice_service: DurableInvoiceService | None = None


def get_durable_invoice_service() -> DurableInvoiceService:
    global _durable_invoice_service
    if _durable_invoice_service is None:
        _durable_invoice_service = DurableInvoiceService()
    return _durable_invoice_service
