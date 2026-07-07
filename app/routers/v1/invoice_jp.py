"""v1 JP invoice extraction router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from typing import Optional

router = APIRouter(prefix="/v1/invoice-jp", tags=["invoice-jp"])

_ALLOWED_TYPES = {"image/png", "image/jpeg", "image/tiff", "application/pdf"}


@router.post("/extract")
async def extract_invoice_jp_sync(
    file: UploadFile = File(...),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
):
    """
    Synchronous JP invoice extraction.

    Stage 1 skeleton: accepts file, returns stub response.
    Full extraction pipeline will be wired in Stage 3.
    """
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported content type: {file.content_type}")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Empty file")

    return {
        "request_id": "stub-001",
        "status": "completed",
        "document_type": "qualified_invoice",
        "invoice": None,
        "confidence": None,
        "needs_review": False,
        "message": "Stage 1 skeleton — extraction pipeline not yet wired",
    }


@router.post("/extract:async")
async def extract_invoice_jp_async(
    file: UploadFile = File(...),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
):
    """
    Async JP invoice extraction — returns job_id for polling.

    Stage 1 skeleton: creates a stub job.
    """
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported content type: {file.content_type}")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Empty file")

    job_id = str(uuid.uuid4())

    return {
        "job_id": job_id,
        "status": "received",
        "message": "Stage 1 skeleton — async extraction not yet wired",
    }


@router.get("/{document_id}")
async def get_invoice_jp(document_id: str):
    """Fetch a JP invoice document by ID."""
    raise HTTPException(404, "Not found — Stage 1 skeleton")


@router.post("/{document_id}/approve")
async def approve_invoice_jp(
    document_id: str,
    x_actor: Optional[str] = Header(None, alias="X-Actor"),
):
    """Approve a JP invoice."""
    if not x_actor:
        raise HTTPException(400, "X-Actor header required")
    return {"document_id": document_id, "status": "approved", "actor": x_actor}


@router.post("/{document_id}/reject")
async def reject_invoice_jp(
    document_id: str,
    x_actor: Optional[str] = Header(None, alias="X-Actor"),
    x_reason: Optional[str] = Header(None, alias="X-Reason"),
):
    """Reject a JP invoice."""
    if not x_actor:
        raise HTTPException(400, "X-Actor header required")
    return {"document_id": document_id, "status": "rejected", "actor": x_actor, "reason": x_reason}


@router.patch("/{document_id}/fields")
async def patch_invoice_jp_fields(
    document_id: str,
    x_actor: Optional[str] = Header(None, alias="X-Actor"),
):
    """Patch fields on a JP invoice (with audit)."""
    if not x_actor:
        raise HTTPException(400, "X-Actor header required")
    return {"document_id": document_id, "status": "patched", "actor": x_actor}
