from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.audit_log import AuditAction, AuditLogService, get_audit_log_service
from app.services.document_store import DocumentStore, StoredDocument

logger = logging.getLogger(__name__)
from app.services.webhook_dispatch import (
    WebhookDeliveryError,
    WebhookDispatcher,
    WebhookEvent,
    get_webhook_dispatcher,
)


@dataclass
class PatchResult:
    """Result of a patch_fields operation, including any degradation warnings."""
    document: StoredDocument
    warnings: list[str] = field(default_factory=list)


class ReviewService:
    """Coordinates review actions with audit logging and webhook dispatch."""

    def __init__(
        self,
        doc_store: DocumentStore,
        audit_log: AuditLogService,
        webhook_dispatcher: WebhookDispatcher,
    ) -> None:
        self._store = doc_store
        self._audit = audit_log
        self._webhooks = webhook_dispatcher

    async def approve(
        self,
        document_id: str,
        actor: str,
        reason: str | None = None,
        tenant_id: str | None = None,
    ) -> StoredDocument:
        doc = self._store.update_status(document_id, "approved", actor, reason, tenant_id)
        if doc is None:
            raise ValueError(f"Document not found: {document_id}")

        await self._audit.log(
            document_id=document_id,
            action=AuditAction.APPROVE,
            actor=actor,
            reason=reason,
            tenant_id=doc.tenant_id,
        )
        await self._webhooks.dispatch(
            WebhookEvent(
                event_type="document.review_completed",
                document_id=document_id,
                payload={"status": "approved", "actor": actor, "reason": reason},
                timestamp=datetime.now(timezone.utc),
                tenant_id=doc.tenant_id,
            )
        )
        return doc

    async def reject(
        self,
        document_id: str,
        actor: str,
        reason: str | None = None,
        tenant_id: str | None = None,
    ) -> StoredDocument:
        doc = self._store.update_status(document_id, "rejected", actor, reason, tenant_id)
        if doc is None:
            raise ValueError(f"Document not found: {document_id}")

        await self._audit.log(
            document_id=document_id,
            action=AuditAction.REJECT,
            actor=actor,
            reason=reason,
            tenant_id=doc.tenant_id,
        )
        await self._webhooks.dispatch(
            WebhookEvent(
                event_type="document.review_completed",
                document_id=document_id,
                payload={"status": "rejected", "actor": actor, "reason": reason},
                timestamp=datetime.now(timezone.utc),
                tenant_id=doc.tenant_id,
            )
        )
        return doc

    async def patch_fields(
        self,
        document_id: str,
        fields: dict,
        actor: str,
        reason: str | None = None,
        force: bool = False,
        tenant_id: str | None = None,
    ) -> PatchResult:
        # Guard against mutating audited state. Approved/rejected docs require X-Force.
        existing = self._store.get(document_id, tenant_id)
        if existing is None:
            raise ValueError(f"Document not found: {document_id}")
        if existing.review_status in {"approved", "rejected"} and not force:
            raise PermissionError(
                f"Cannot patch fields on {existing.review_status} document without X-Force header"
            )

        doc = self._store.patch_fields(document_id, fields, actor, tenant_id)
        if doc is None:
            raise ValueError(f"Document not found: {document_id}")

        await self._audit.log(
            document_id=document_id,
            action=AuditAction.PATCH,
            actor=actor,
            reason=reason,
            changes=fields,
            tenant_id=doc.tenant_id,
        )
        await self._webhooks.dispatch(
            WebhookEvent(
                event_type="document.fields_patched",
                document_id=document_id,
                payload={"changes": fields, "actor": actor, "forced": force},
                timestamp=datetime.now(timezone.utc),
                tenant_id=doc.tenant_id,
            )
        )

        warnings: list[str] = []
        # Re-index in search so patched fields are reflected in /v1/search
        try:
            from app.routers.v1.search import _get_search_service

            search_svc = _get_search_service()
            await search_svc.remove_document(document_id)
            await search_svc.index_document(
                document_id,
                doc.structured_json,
                tenant_id=doc.tenant_id,
            )
        except Exception:
            msg = f"Search re-index failed for {document_id}; document patched but may not appear in search results"
            logger.warning(msg, exc_info=True)
            warnings.append(msg)

        return PatchResult(document=doc, warnings=warnings)

    async def list_documents(
        self,
        review_status: str | None = None,
        document_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
        tenant_id: str | None = None,
    ) -> dict:
        documents = self._store.list_documents(
            review_status=review_status,
            document_type=document_type,
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
        )
        total = self._store.count(
            review_status=review_status,
            document_type=document_type,
            tenant_id=tenant_id,
        )
        return {
            "documents": documents,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


# Module-level singletons
_document_store = DocumentStore()
_audit_log = get_audit_log_service()
_webhook_dispatcher = get_webhook_dispatcher()
_review_service = ReviewService(_document_store, _audit_log, _webhook_dispatcher)


def get_review_service() -> ReviewService:
    return _review_service


def get_document_store() -> DocumentStore:
    return _document_store
