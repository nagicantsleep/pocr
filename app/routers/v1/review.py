from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from app.services.document_store import StoredDocument
from app.services.review_service import get_document_store, get_review_service

router = APIRouter(prefix="/v1/documents", tags=["Review"])


class StoredDocumentResponse(BaseModel):
    id: str
    document_type: str
    structured_json: dict
    confidence: float
    needs_review: bool
    review_status: str
    created_at: datetime
    updated_at: datetime
    reviewed_by: str | None = None
    review_reason: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[StoredDocumentResponse]
    total: int
    limit: int
    offset: int


def _to_response(doc: StoredDocument) -> StoredDocumentResponse:
    return StoredDocumentResponse(
        id=doc.id,
        document_type=doc.document_type,
        structured_json=doc.structured_json,
        confidence=doc.confidence,
        needs_review=doc.needs_review,
        review_status=doc.review_status,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        reviewed_by=doc.reviewed_by,
        review_reason=doc.review_reason,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    review_status: Optional[str] = Query(None),
    document_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List documents with filtering and pagination."""
    svc = get_review_service()
    result = await svc.list_documents(
        review_status=review_status,
        document_type=document_type,
        limit=limit,
        offset=offset,
    )
    return DocumentListResponse(
        documents=[_to_response(d) for d in result["documents"]],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


@router.get("/{document_id}", response_model=StoredDocumentResponse)
async def get_document(document_id: str):
    """Get a single document."""
    store = get_document_store()
    doc = store.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_response(doc)


@router.post("/{document_id}/approve", response_model=StoredDocumentResponse)
async def approve_document(
    document_id: str,
    x_actor: str = Header(..., alias="X-Actor"),
    x_reason: Optional[str] = Header(None, alias="X-Reason"),
):
    """Approve a document."""
    svc = get_review_service()
    try:
        doc = await svc.approve(document_id, actor=x_actor, reason=x_reason)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_response(doc)


@router.post("/{document_id}/reject", response_model=StoredDocumentResponse)
async def reject_document(
    document_id: str,
    x_actor: str = Header(..., alias="X-Actor"),
    x_reason: Optional[str] = Header(None, alias="X-Reason"),
):
    """Reject a document."""
    svc = get_review_service()
    try:
        doc = await svc.reject(document_id, actor=x_actor, reason=x_reason)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_response(doc)


@router.patch("/{document_id}/fields", response_model=StoredDocumentResponse)
async def patch_document_fields(
    document_id: str,
    body: dict,
    x_actor: str = Header(..., alias="X-Actor"),
):
    """Patch fields on a document with audit."""
    svc = get_review_service()
    try:
        doc = await svc.patch_fields(document_id, fields=body, actor=x_actor)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_response(doc)
