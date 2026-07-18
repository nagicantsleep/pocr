"""Durable status and cancellation API for v1 JP invoice extraction jobs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth import AuthenticatedPrincipal, require_operator
from app.config import get_settings
from app.repositories.invoice_repository import get_invoice_repository
from app.services.job_store import get_job_store
from app.storage import get_storage_adapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/jobs", tags=["Jobs"])


def _job_response(job: dict) -> dict:
    """Return the public job representation without raw upload content."""
    response = {
        key: job[key]
        for key in (
            "job_id",
            "status",
            "created_at",
            "completed_at",
            "error",
        )
        if job.get(key) is not None
    }
    if job.get("result") is not None:
        response["results"] = job["result"]
    if job.get("document_id") is not None:
        response["document_id"] = job["document_id"]
    return response


def _legacy_job_response(job: dict) -> dict:
    return {
        key: job[key]
        for key in (
            "job_id",
            "status",
            "created_at",
            "started_at",
            "completed_at",
            "results",
            "progress",
            "error",
        )
        if key in job
    }


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    principal: AuthenticatedPrincipal = Depends(require_operator),
) -> dict:
    """Return the current status of a job created via /v1/invoice-jp/extract:async."""
    if not get_settings().INVOICE_JP_DURABLE_MODE:
        job = get_job_store().get_job(job_id)
        if job is None or job.get("tenant_id") != principal.tenant_id:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return _legacy_job_response(job)
    job = get_invoice_repository().get_extraction_job(
        job_id,
        tenant_id=principal.tenant_id,
    )
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _job_response(job)


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    principal: AuthenticatedPrincipal = Depends(require_operator),
) -> dict:
    """Cancel a pending/running job."""
    if not get_settings().INVOICE_JP_DURABLE_MODE:
        job_store = get_job_store()
        job = job_store.get_job(job_id)
        if job is None or job.get("tenant_id") != principal.tenant_id:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        if not job_store.cancel_job(job_id):
            raise HTTPException(status_code=409, detail=f"Job {job_id} cannot be cancelled")
        idempotency_key = job.get("idempotency_key")
        fingerprint = job.get("request_fingerprint")
        if idempotency_key and fingerprint:
            from app.routers.v1.invoice_jp import _idempotency_service

            await _idempotency_service.release_pending_operation(
                idempotency_key,
                job_id,
                fingerprint,
            )
        return {"job_id": job_id, "status": "cancelled"}
    repository = get_invoice_repository()
    job = repository.get_extraction_job(
        job_id,
        tenant_id=principal.tenant_id,
    )
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    ok = repository.cancel_extraction_job(
        job_id,
        tenant_id=principal.tenant_id,
    )
    if not ok:
        raise HTTPException(status_code=409, detail=f"Job {job_id} cannot be cancelled")
    try:
        await get_storage_adapter().delete(job["source_key"])
    except Exception:
        logger.warning("Source artifact cleanup failed for cancelled job %s", job_id, exc_info=True)
    return {"job_id": job_id, "status": "cancelled"}
