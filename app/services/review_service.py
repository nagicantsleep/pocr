from __future__ import annotations

from datetime import datetime, timezone

from app.services.audit_log import AuditAction, AuditLogService, get_audit_log_service
from app.services.document_store import DocumentStore, StoredDocument
from app.services.webhook_dispatch import (
    WebhookDispatcher,
    WebhookEvent,
    get_webhook_dispatcher,
)


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
    ) -> StoredDocument:
        doc = self._store.update_status(document_id, "approved", actor, reason)
        if doc is None:
            raise ValueError(f"Document not found: {document_id}")

        await self._audit.log(
            document_id=document_id,
            action=AuditAction.APPROVE,
            actor=actor,
            reason=reason,
        )
        await self._webhooks.dispatch(
            WebhookEvent(
                event_type="document.review_completed",
                document_id=document_id,
                payload={"status": "approved", "actor": actor, "reason": reason},
                timestamp=datetime.now(timezone.utc),
            )
        )
        return doc

    async def reject(
        self,
        document_id: str,
        actor: str,
        reason: str | None = None,
    ) -> StoredDocument:
        doc = self._store.update_status(document_id, "rejected", actor, reason)
        if doc is None:
            raise ValueError(f"Document not found: {document_id}")

        await self._audit.log(
            document_id=document_id,
            action=AuditAction.REJECT,
            actor=actor,
            reason=reason,
        )
        await self._webhooks.dispatch(
            WebhookEvent(
                event_type="document.review_completed",
                document_id=document_id,
                payload={"status": "rejected", "actor": actor, "reason": reason},
                timestamp=datetime.now(timezone.utc),
            )
        )
        return doc

    async def patch_fields(
        self,
        document_id: str,
        fields: dict,
        actor: str,
    ) -> StoredDocument:
        doc = self._store.patch_fields(document_id, fields, actor)
        if doc is None:
            raise ValueError(f"Document not found: {document_id}")

        await self._audit.log(
            document_id=document_id,
            action=AuditAction.PATCH,
            actor=actor,
            changes=fields,
        )
        await self._webhooks.dispatch(
            WebhookEvent(
                event_type="document.fields_patched",
                document_id=document_id,
                payload={"changes": fields, "actor": actor},
                timestamp=datetime.now(timezone.utc),
            )
        )
        return doc

    async def list_documents(
        self,
        review_status: str | None = None,
        document_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        documents = self._store.list_documents(
            review_status=review_status,
            document_type=document_type,
            limit=limit,
            offset=offset,
        )
        total = self._store.count(review_status=review_status)
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
