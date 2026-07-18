from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from app.auth import AuthenticatedPrincipal, require_document_reviewer, require_operator
from app.config import get_settings
from app.services.document_store import StoredDocument
from app.services.durable_invoice_service import get_durable_invoice_service
from app.services.review_service import get_document_store, get_review_service

router = APIRouter(prefix="/v1/documents", tags=["Review"])

def _durable_mode_enabled() -> bool:
    return get_settings().INVOICE_JP_DURABLE_MODE


class StoredDocumentResponse(BaseModel):
    id: str
    document_id: str | None = None
    document_type: str
    structured_json: dict
    confidence: float
    needs_review: bool
    review_status: str
    created_at: datetime
    updated_at: datetime
    reviewed_by: str | None = None
    review_reason: str | None = None
    issuer_name: str | None = None
    total_amount: float | str | None = None
    warnings: list[str] | None = None


class DocumentListResponse(BaseModel):
    documents: list[StoredDocumentResponse]
    total: int
    limit: int
    offset: int


def _to_response(doc: StoredDocument) -> StoredDocumentResponse:
    # Filter out internal system keys (e.g. _canonical_response, _page_count)
    data = {k: v for k, v in (doc.structured_json or {}).items() if not k.startswith("_")}
    issuer_name = data.get("issuer_name")
    if isinstance(issuer_name, dict):
        issuer_name = issuer_name.get("value")
    total_amount = data.get("total_amount")
    if isinstance(total_amount, dict):
        total_amount = total_amount.get("value")
    return StoredDocumentResponse(
        id=doc.id,
        document_id=doc.id,
        document_type=doc.document_type,
        structured_json=doc.structured_json,
        confidence=doc.confidence,
        needs_review=doc.needs_review,
        review_status=doc.review_status,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        reviewed_by=doc.reviewed_by,
        review_reason=doc.review_reason,
        issuer_name=issuer_name,
        total_amount=total_amount,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    review_status: Optional[str] = Query(None),
    document_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_operator),
):
    """List documents with filtering and pagination."""
    if _durable_mode_enabled():
        documents, total = get_durable_invoice_service().list(
            review_status=review_status,
            document_type=document_type,
            limit=limit,
            offset=offset,
            tenant_id=principal.tenant_id,
        )
        result = {"documents": documents, "total": total, "limit": limit, "offset": offset}
    else:
        svc = get_review_service()
        result = await svc.list_documents(
            review_status=review_status,
            document_type=document_type,
            limit=limit,
            offset=offset,
            tenant_id=principal.tenant_id,
        )
    return DocumentListResponse(
        documents=[_to_response(d) for d in result["documents"]],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


@router.get("/{document_id}", response_model=StoredDocumentResponse)
async def get_document(
    document_id: str,
    principal: AuthenticatedPrincipal = Depends(require_operator),
):
    """Get a single document."""
    doc = (
        get_durable_invoice_service().get(document_id, tenant_id=principal.tenant_id)
        if _durable_mode_enabled()
        else get_document_store().get(document_id, principal.tenant_id)
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_response(doc)


@router.post("/{document_id}/approve", response_model=StoredDocumentResponse)
async def approve_document(
    document_id: str,
    x_reason: Optional[str] = Header(None, alias="X-Reason"),
    principal: AuthenticatedPrincipal = Depends(require_document_reviewer),
):
    """Approve a document."""
    try:
        doc = (
            get_durable_invoice_service().approve(
                document_id,
                actor=principal.user_id,
                reason=x_reason,
                tenant_id=principal.tenant_id,
            )
            if _durable_mode_enabled()
            else await get_review_service().approve(
                document_id,
                actor=principal.user_id,
                reason=x_reason,
                tenant_id=principal.tenant_id,
            )
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_response(doc)


@router.post("/{document_id}/reject", response_model=StoredDocumentResponse)
async def reject_document(
    document_id: str,
    x_reason: Optional[str] = Header(None, alias="X-Reason"),
    principal: AuthenticatedPrincipal = Depends(require_document_reviewer),
):
    """Reject a document."""
    try:
        doc = (
            get_durable_invoice_service().reject(
                document_id,
                actor=principal.user_id,
                reason=x_reason,
                tenant_id=principal.tenant_id,
            )
            if _durable_mode_enabled()
            else await get_review_service().reject(
                document_id,
                actor=principal.user_id,
                reason=x_reason,
                tenant_id=principal.tenant_id,
            )
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_response(doc)


PATCH_RESERVED_KEYS = frozenset({
    "id", "document_id", "review_status", "created_at", "updated_at",
    "reviewed_by", "review_reason", "structured_json",
})
PATCH_MAX_KEYS = 50


def _validate_patch_body(body: dict) -> None:
    """Reject PATCH bodies that include reserved keys, system-namespaced keys, or are too large."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="PATCH body must be a JSON object")
    if len(body) > PATCH_MAX_KEYS:
        raise HTTPException(status_code=400, detail=f"PATCH body has too many keys (>{PATCH_MAX_KEYS})")
    if reserved := PATCH_RESERVED_KEYS & body.keys():
        raise HTTPException(
            status_code=400,
            detail=f"PATCH body contains reserved keys: {sorted(reserved)}",
        )
    system_keys = [k for k in body if k.startswith("_")]
    if system_keys:
        raise HTTPException(
            status_code=400,
            detail=f"PATCH body contains system-namespaced keys: {sorted(system_keys)}",
        )


@router.patch("/{document_id}/fields", response_model=StoredDocumentResponse)
async def patch_document_fields(
    document_id: str,
    body: dict,
    x_reason: Optional[str] = Header(None, alias="X-Reason"),
    x_force: Optional[str] = Header(None, alias="X-Force"),
    principal: AuthenticatedPrincipal = Depends(require_document_reviewer),
):
    """Patch fields on a document with audit."""
    _validate_patch_body(body)
    force = (x_force or "").lower() in {"1", "true", "yes"}
    try:
        result = (
            get_durable_invoice_service().patch(
                document_id,
                fields=body,
                actor=principal.user_id,
                reason=x_reason,
                force=force,
                tenant_id=principal.tenant_id,
            )
            if _durable_mode_enabled()
            else await get_review_service().patch_fields(
                document_id,
                fields=body,
                actor=principal.user_id,
                reason=x_reason,
                force=force,
                tenant_id=principal.tenant_id,
            )
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")
    response = _to_response(result if _durable_mode_enabled() else result.document)
    if not _durable_mode_enabled() and result.warnings:
        response = response.model_copy(update={"warnings": result.warnings})
    return response
