"""Kafka worker for durable JP invoice extraction jobs."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException

from app.config import get_settings
from app.repositories.invoice_repository import ReviewStatus, get_invoice_repository
from app.routers.v1.invoice_jp import _run_extraction_pages
from app.services.durable_invoice_service import get_durable_invoice_service
from app.services.quality_gate import QualityGate
from app.storage import get_storage_adapter

logger = logging.getLogger(__name__)

_DOCUMENT_STATUS_TO_REVIEW = {
    "approved": ReviewStatus.REVIEWED,
    "rejected": ReviewStatus.REJECTED,
    "needs_review": ReviewStatus.NEEDS_REVIEW,
    "pending": "pending",
}


def _job_result(results: list[tuple[Any, Any, Any]]) -> dict[str, Any]:
    documents = [
        {
            "status": "success",
            "document_id": document.id,
            "document_type": document.document_type,
            "confidence": document.confidence,
            "needs_review": document.needs_review,
        }
        for document, _, _ in results
    ]
    return {"documents": documents, "page_count": len(documents)}


def _invoice_writes(results: list[tuple[Any, Any, Any]]) -> list[dict[str, Any]]:
    writes = []
    for document, _extraction_result, deferred in results:
        if not isinstance(deferred, dict):
            raise ValueError("deferred extraction result is missing durable metadata")
        writes.append(
            {
                "invoice_id": document.id,
                "actor": "invoice-extraction-worker",
                "invoice_data": {
                    "source": deferred["source"],
                    "raw_ocr": deferred["raw_ocr"],
                    "extracted": document.structured_json or {},
                    "validation": {
                        "_durable_document": {
                            "document_type": document.document_type,
                            "confidence": document.confidence,
                            "needs_review": document.needs_review,
                            "reviewed_by": document.reviewed_by,
                            "review_reason": document.review_reason,
                        }
                    },
                    "review_status": _DOCUMENT_STATUS_TO_REVIEW.get(
                        document.review_status,
                        ReviewStatus.NEEDS_REVIEW,
                    ),
                },
            }
        )
    return writes


def _artifact_keys(document_ids: set[str]) -> list[str]:
    return [
        key
        for document_id in document_ids
        for key in (
            f"documents/{document_id}/raw",
            f"documents/{document_id}/extracted.json",
            f"documents/{document_id}/raw.pdf",
        )
    ]


async def _cleanup_artifact_keys(storage_adapter: Any, keys: list[str]) -> bool:
    cleaned = True
    for key in keys:
        try:
            await storage_adapter.delete(key)
            if hasattr(storage_adapter, "exists") and await storage_adapter.exists(key):
                cleaned = False
                logger.warning("Artifact cleanup did not remove %s", key)
        except Exception:
            cleaned = False
            logger.warning("Artifact cleanup failed for %s", key, exc_info=True)
    return cleaned


def _result_document_ids(result: dict[str, Any]) -> set[str]:
    return {
        document["document_id"]
        for document in result.get("documents", [])
        if isinstance(document.get("document_id"), str)
    }


def _renew_claim(
    repository: Any,
    *,
    job_id: str,
    tenant_id: str,
    lease_token: str,
    lost_claim: threading.Event,
    stop: threading.Event,
    interval_seconds: int,
) -> None:
    while not stop.wait(interval_seconds):
        if not repository.renew_extraction_job_claim(
            job_id,
            tenant_id=tenant_id,
            lease_token=lease_token,
        ):
            lost_claim.set()
            logger.warning("Extraction job %s lost its lease during renewal", job_id)
            return


def _cleanup_cancelled_artifacts(repository: Any, storage_adapter: Any) -> None:
    for job in repository.list_cancelled_extraction_jobs_for_cleanup():
        keys = list(dict.fromkeys(job["artifact_cleanup_keys"]))
        if asyncio.run(_cleanup_artifact_keys(storage_adapter, keys)):
            repository.complete_extraction_job_artifact_cleanup(
                job["job_id"],
                tenant_id=job["tenant_id"],
                keys=keys,
            )


def _recover_expired_extraction_jobs(repository: Any, storage_adapter: Any) -> None:
    """Reclaim jobs abandoned by a worker that died after consuming Kafka."""
    for job in repository.list_expired_extraction_jobs():
        process_extraction_event(
            {
                "event_type": "document.extraction_requested",
                "tenant_id": job["tenant_id"],
                "payload": {"job_id": job["job_id"]},
            },
            repository=repository,
            storage_adapter=storage_adapter,
        )


def _run_cleanup_retry_loop(
    repository: Any,
    storage_adapter: Any,
    *,
    stop: threading.Event,
    interval_seconds: float,
) -> None:
    while not stop.is_set():
        try:
            _cleanup_cancelled_artifacts(repository, storage_adapter)
        except Exception:
            logger.exception("Cancelled extraction artifact cleanup scan failed")
        stop.wait(interval_seconds)


async def _cleanup_derived_artifacts(storage_adapter: Any, result: dict[str, Any]) -> bool:
    return await _cleanup_artifact_keys(storage_adapter, _artifact_keys(_result_document_ids(result)))


async def _cleanup_document_ids(storage_adapter: Any, document_ids: set[str]) -> bool:
    return await _cleanup_artifact_keys(storage_adapter, _artifact_keys(document_ids))


async def _execute_extraction_job(
    job: dict[str, Any],
    *,
    extractor: Callable[..., Awaitable[list[tuple[Any, Any, Any]]]] = _run_extraction_pages,
    storage_adapter: Any | None = None,
    created_document_ids: set[str] | None = None,
    artifact_journal: Callable[[list[str]], bool] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    storage_adapter = storage_adapter or get_storage_adapter()
    existing = get_durable_invoice_service().get(
        job["job_id"],
        tenant_id=job["tenant_id"],
    )
    if existing is not None:
        return {
            "documents": [
                {
                    "status": "success",
                    "document_id": existing.id,
                    "document_type": existing.document_type,
                    "confidence": existing.confidence,
                    "needs_review": existing.needs_review,
                }
            ],
            "page_count": 1,
        }, []

    content = await storage_adapter.get(job["source_key"])
    results = await extractor(
        content,
        job["content_type"],
        job.get("ocr_lang"),
        first_document_id=job["job_id"],
        quality_gate=QualityGate(),
        storage_adapter=storage_adapter,
        raw_content_type=job["content_type"],
        tenant_id=job["tenant_id"],
        actor="invoice-extraction-worker",
        defer_durable_commit=True,
        created_document_ids=created_document_ids,
        artifact_journal=artifact_journal,
    )
    return _job_result(results), _invoice_writes(results)


def process_extraction_event(
    event: dict[str, Any],
    *,
    repository: Any | None = None,
    storage_adapter: Any | None = None,
    extractor: Callable[..., Awaitable[list[tuple[Any, Any, Any]]]] = _run_extraction_pages,
    lease_seconds: int = 300,
) -> bool:
    """Claim and execute one durable extraction request exactly once per lease."""
    if event.get("event_type") != "document.extraction_requested":
        return False
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("extraction event payload must be an object")
    job_id = payload.get("job_id")
    tenant_id = event.get("tenant_id")
    if not isinstance(job_id, str) or not job_id:
        raise ValueError("extraction event job_id is required")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("extraction event tenant_id is required")

    repository = repository or get_invoice_repository()
    job = repository.claim_extraction_job(
        job_id,
        tenant_id=tenant_id,
        lease_seconds=lease_seconds,
    )
    if job is None:
        if repository.has_active_extraction_job_claim(job_id, tenant_id=tenant_id):
            logger.info("Deferring extraction job %s while another worker lease is active", job_id)
            return None
        logger.info("Ignoring duplicate, cancelled, or terminal extraction job %s", job_id)
        return False
    lease_token = job.get("lease_token")
    if not isinstance(lease_token, str) or not lease_token:
        raise RuntimeError(f"Extraction job {job_id} was claimed without a lease token")
    storage_adapter = storage_adapter or get_storage_adapter()
    created_document_ids: set[str] = set()
    lost_claim = threading.Event()
    stop_renewal = threading.Event()
    renewal = threading.Thread(
        target=_renew_claim,
        kwargs={
            "repository": repository,
            "job_id": job_id,
            "tenant_id": tenant_id,
            "lease_token": lease_token,
            "lost_claim": lost_claim,
            "stop": stop_renewal,
            "interval_seconds": max(1, lease_seconds // 3),
        },
        daemon=True,
    )
    renewal.start()
    result: dict[str, Any] | None = None
    artifact_journal = lambda keys: repository.journal_extraction_job_artifacts(
        job_id,
        tenant_id=tenant_id,
        lease_token=lease_token,
        keys=keys,
    )

    try:
        result, invoice_writes = asyncio.run(
            _execute_extraction_job(
                job,
                extractor=extractor,
                storage_adapter=storage_adapter,
                created_document_ids=created_document_ids,
                artifact_journal=artifact_journal,
            )
        )
        if lost_claim.is_set():
            repository.add_extraction_job_artifact_cleanup(
                job_id,
                tenant_id=tenant_id,
                keys=_artifact_keys(created_document_ids),
            )
            asyncio.run(_cleanup_document_ids(storage_adapter, created_document_ids))
            return False
        document_id = result["documents"][0]["document_id"]
        if invoice_writes:
            completed = repository.complete_extraction_job_and_store_invoices(
                job_id,
                tenant_id=tenant_id,
                lease_token=lease_token,
                invoice_writes=invoice_writes,
                result=result,
            )
        else:
            completed = repository.complete_extraction_job(
                job_id,
                tenant_id=tenant_id,
                lease_token=lease_token,
                document_id=document_id,
                result=result,
            )
        if not completed:
            logger.warning("Extraction job %s lost its completion lease", job_id)
            repository.add_extraction_job_artifact_cleanup(
                job_id,
                tenant_id=tenant_id,
                keys=_artifact_keys(created_document_ids),
            )
            asyncio.run(_cleanup_document_ids(storage_adapter, created_document_ids))
            return False
        return True
    except HTTPException as exc:
        repository.add_extraction_job_artifact_cleanup(
            job_id,
            tenant_id=tenant_id,
            keys=_artifact_keys(created_document_ids),
        )
        asyncio.run(_cleanup_document_ids(storage_adapter, created_document_ids))
        repository.fail_extraction_job(
            job_id,
            tenant_id=tenant_id,
            lease_token=lease_token,
            error=str(exc.detail),
        )
        return False
    except Exception as exc:
        logger.exception("Extraction job %s failed", job_id)
        repository.add_extraction_job_artifact_cleanup(
            job_id,
            tenant_id=tenant_id,
            keys=_artifact_keys(created_document_ids),
        )
        asyncio.run(_cleanup_document_ids(storage_adapter, created_document_ids))
        repository.fail_extraction_job(
            job_id,
            tenant_id=tenant_id,
            lease_token=lease_token,
            error=str(exc),
        )
        return False
    finally:
        stop_renewal.set()
        renewal.join(timeout=max(1, lease_seconds // 3 + 1))


def _process_until_extraction_lease_clears(
    process: Callable[[], bool | None],
    *,
    retry_seconds: float,
) -> bool:
    """Keep the current Kafka record uncommitted while its job is leased elsewhere."""
    result = process()
    while result is None:
        time.sleep(retry_seconds)
        result = process()
    return result


def run_worker() -> None:
    """Consume extraction request events from the invoice outbox topic."""
    from confluent_kafka import Consumer

    settings = get_settings()
    consumer = Consumer(
        {
            "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "group.id": f"{settings.INVOICE_OUTBOX_CONSUMER_GROUP}-extraction",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([settings.INVOICE_OUTBOX_TOPIC])
    repository = get_invoice_repository()
    storage_adapter = get_storage_adapter()
    stop_cleanup_retry = threading.Event()
    cleanup_retry = threading.Thread(
        target=_run_cleanup_retry_loop,
        kwargs={
            "repository": repository,
            "storage_adapter": storage_adapter,
            "stop": stop_cleanup_retry,
            "interval_seconds": max(0.1, settings.INVOICE_OUTBOX_POLL_SECONDS),
        },
        daemon=True,
    )
    cleanup_retry.start()
    try:
        while True:
            _recover_expired_extraction_jobs(repository, storage_adapter)
            kafka_message = consumer.poll(settings.INVOICE_OUTBOX_POLL_SECONDS)
            if kafka_message is None:
                continue
            if kafka_message.error():
                logger.error("Kafka consumer error: %s", kafka_message.error())
                continue
            event = json.loads(kafka_message.value().decode("utf-8"))
            _process_until_extraction_lease_clears(
                lambda: process_extraction_event(
                    event,
                    repository=repository,
                    storage_adapter=storage_adapter,
                ),
                retry_seconds=max(0.1, settings.INVOICE_OUTBOX_POLL_SECONDS),
            )
            consumer.commit(kafka_message)
    finally:
        stop_cleanup_retry.set()
        cleanup_retry.join(timeout=max(1, settings.INVOICE_OUTBOX_POLL_SECONDS + 1))
        consumer.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            run_worker()
        except Exception:
            logger.exception("Invoice extraction worker crashed")
            time.sleep(5)
