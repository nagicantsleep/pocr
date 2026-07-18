"""v1 JP invoice extraction router."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from typing import Callable, Optional

from app.auth import AuthenticatedPrincipal, require_document_reviewer, require_operator
from app.config import get_settings
from app.routers.v1.review import _validate_patch_body

from app.schemas.registry.schema_registry import SchemaRegistry
from app.repositories.invoice_repository import get_invoice_repository
from app.services.document_store import StoredDocument
from app.services.durable_invoice_service import get_durable_invoice_service
from app.services.extraction_kernel import ExtractionKernel, source_registry
from app.services.extraction_kernel.receipt_source_registry import register_receipt_sources
from app.services.ocr_engine import run_ocr
from app.services.audit_log import AuditAction, get_audit_log_service
from app.services.idempotency import IdempotencyService
from app.services.lang_detect import detect_language
from app.services.job_store import JobStatus, get_job_store
from app.services.pdf_render.renderer import PDFRenderer
from app.services.quality_gate import QualityGate
from app.services.review_service import get_document_store, get_review_service
from app.routers.v1.search import _get_search_service
from app.storage import get_storage_adapter
from app.services.webhook_dispatch import WebhookEvent, get_webhook_dispatcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/invoice-jp", tags=["invoice-jp"])

_ALLOWED_TYPES = {"image/png", "image/jpeg", "image/tiff", "application/pdf"}
_UPLOAD_CHUNK_SIZE = 64 * 1024
_SCHEMA_VERSION = "invoice-jp/v1.0.0"
_IDEMPOTENCY_LEASE_SECONDS = 300

# Module-level initialization
register_receipt_sources(source_registry)

_schema_registry = SchemaRegistry(
    schemas_dir="app/schemas/registry",
)
_schema_registry.load()

_kernel = ExtractionKernel(source_registry)

# Redis-backed idempotency service (fails closed to prevent duplicate jobs)
_settings = get_settings()
_idempotency_service = IdempotencyService(redis_url=_settings.REDIS_URL, fail_closed=True)

# In-memory store for canonical idempotency responses (keyed by resource_id).
# Kept separate from structured_json so GET never leaks internal metadata.
_canonical_responses: dict[str, dict] = {}

def _durable_mode_enabled() -> bool:
    return get_settings().INVOICE_JP_DURABLE_MODE


def _build_cache_hit_response(doc: StoredDocument) -> dict:
    """Build full response dict from a cached document for idempotency cache-hit.

    Returns the canonical response shape matching the fresh extraction response,
    including request_id, storage, and page_count.
    """
    canonical = _canonical_responses.get(doc.id)
    if canonical is not None:
        return canonical
    # Fallback for documents stored before canonical response was introduced.
    raw = doc.structured_json or {}
    fields = {}
    for key, val in raw.items():
        if key.startswith("_"):
            continue
        if isinstance(val, dict) and "value" in val:
            fields[key] = val
        elif key not in ("line_items", "tables", "quality_score"):
            fields[key] = val
    return {
        "request_id": None,
        "status": "completed",
        "document_type": doc.document_type,
        "document_id": doc.id,
        "fields": fields,
        "line_items": raw.get("line_items", []),
        "tables": raw.get("tables", {}),
        "confidence": doc.confidence,
        "needs_review": doc.needs_review,
        "quality_score": raw.get("quality_score"),
        "storage": {
            "raw_key": f"documents/{doc.id}/raw",
            "structured_key": f"documents/{doc.id}/extracted.json",
        },
        "page_count": 1,
    }


def _preprocess_if_image(content: bytes, content_type: str) -> bytes:
    """Preprocess image bytes (deskew/denoise/binarize) before OCR.

    Returns processed bytes; silently returns original on failure or for PDFs.
    """
    if content_type == "application/pdf":
        return content
    try:
        from app.services.preprocessing.chain import PreprocessingChain
        result = PreprocessingChain().process(content)
        return result.image_bytes
    except Exception:
        logger.debug("Preprocessing skipped (cv2 unavailable or decode failed)")
        return content


async def _read_upload_with_limit(file: UploadFile) -> bytes:
    """Read a multipart upload incrementally and reject at the configured limit."""
    max_bytes = get_settings().max_image_size_bytes
    total = 0
    chunks: list[bytes] = []
    while chunk := await file.read(_UPLOAD_CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                413,
                f"Upload exceeds maximum size of {get_settings().MAX_IMAGE_SIZE_MB}MB",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _request_fingerprint(content: bytes, content_type: str, x_lang: str | None) -> str:
    """Bind an idempotency key to the complete normalized extraction request."""
    digest = hashlib.sha256()
    for value in (_SCHEMA_VERSION, content_type.lower(), x_lang or ""):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    digest.update(content)
    return digest.hexdigest()


async def _cleanup_uncommitted_documents(document_ids: set[str]) -> None:
    """Delete documents and artifacts created by an extraction that did not commit."""
    document_store = get_document_store()
    storage_adapter = get_storage_adapter()
    search_service = _get_search_service()
    for document_id in document_ids:
        for key in (
            f"documents/{document_id}/raw",
            f"documents/{document_id}/extracted.json",
            f"documents/{document_id}/raw.pdf",
        ):
            try:
                await storage_adapter.delete(key)
            except Exception:
                logger.debug("Artifact cleanup failed for %s", key, exc_info=True)
        try:
            await search_service.remove_document(document_id)
        except Exception:
            logger.debug("Search cleanup failed for %s", document_id, exc_info=True)
        document_store.delete(document_id)
        _canonical_responses.pop(document_id, None)


async def _renew_operation_lease(
    key: str,
    resource_id: str,
    fingerprint: str,
) -> None:
    """Keep a synchronous extraction's pending idempotency lease alive."""
    while True:
        await asyncio.sleep(_IDEMPOTENCY_LEASE_SECONDS // 3)
        if not await _idempotency_service.renew_pending_operation(
            key,
            resource_id,
            fingerprint,
            ttl_seconds=_IDEMPOTENCY_LEASE_SECONDS,
        ):
            logger.warning("Idempotency lease renewal failed for key=%s", key)
            return


def _build_fields_dict(result) -> dict:
    """Convert ExtractionResult fields to a serializable dict."""
    fields = {}
    for name, field_result in result.fields.items():
        fields[name] = {
            "value": field_result.value,
            "confidence": field_result.confidence,
            "source_used": field_result.source_used,
        }
    return fields


def _build_line_items(result) -> list[dict]:
    """Extract line_items from the first table in an ExtractionResult."""
    for _table_id, rows in result.tables.items():
        return rows
    return []


def _build_tables(result) -> dict[str, list[dict]]:
    """Return all tables from an ExtractionResult."""
    return dict(result.tables)


async def _run_extraction_pages(
    content: bytes,
    content_type: str,
    lang: str | None,
    first_document_id: str | None = None,
    quality_gate: QualityGate | None = None,
    storage_adapter=None,
    raw_content_type: str | None = None,
    created_document_ids: set[str] | None = None,
    tenant_id: str = "development",
    actor: str = "system",
    idempotency_key: str | None = None,
    request_fingerprint: str | None = None,
    canonical_request_id: str | None = None,
    defer_durable_commit: bool = False,
    artifact_journal: Callable[[list[str]], bool] | None = None,
) -> list[tuple[StoredDocument, object, object]]:
    """Run OCR + kernel on one image, or per-page for PDF. Returns (stored_doc, result) tuples."""
    is_pdf = content_type == "application/pdf"
    original_pdf_bytes: bytes | None = None
    if is_pdf:
        original_pdf_bytes = content
        try:
            pages = PDFRenderer().render_pages(content)
        except ValueError as exc:
            raise HTTPException(400, f"PDF render failed: {exc}") from exc
        if not pages:
            raise HTTPException(400, "PDF produced no pages")
        page_bytes_list = [_preprocess_if_image(p.image_bytes, "image/png") for p in pages]
    else:
        processed = _preprocess_if_image(content, content_type)
        page_bytes_list = [processed]

    schema = _schema_registry.get("invoice-jp", "1.0.0")
    if schema is None:
        raise HTTPException(500, "Invoice-jp schema not found")

    # Quality gate: assess every rendered page
    quality_scores: list[dict] = []
    if quality_gate is not None:
        threshold = get_settings().QUALITY_GATE_THRESHOLD
        for idx, page_bytes in enumerate(page_bytes_list):
            qs = quality_gate.assess(page_bytes, threshold=threshold)
            quality_scores.append({
                "page": idx + 1,
                "overall": qs.overall,
                "sharpness": qs.sharpness,
                "contrast": qs.contrast,
                "brightness": qs.brightness,
                "noise_level": qs.noise_level,
                "is_acceptable": qs.is_acceptable,
                "rejection_reason": qs.rejection_reason,
            })
            if not qs.is_acceptable:
                raise HTTPException(
                    422,
                    f"Page {idx + 1} rejected by quality gate: {qs.rejection_reason or 'quality below threshold'}",
                )

    # Language detection: when X-Lang is absent, detect from first page OCR text
    effective_lang = lang
    detected_lang_info: dict | None = None
    if not effective_lang:
        locale_hint = get_settings().LANG_DETECT_LOCALE_HINT
        first_ocr = run_ocr(page_bytes_list[0], lang="ja")
        if "error" not in first_ocr:
            first_text = " ".join(r.get("text", "") for r in first_ocr.get("results", []))
            detection = detect_language(first_text, locale_hint=locale_hint)
            if detection.language != "unknown":
                effective_lang = detection.language
                detected_lang_info = {
                    "language": detection.language,
                    "confidence": detection.confidence,
                    "script": detection.script,
                }
        if not effective_lang:
            effective_lang = "ja"

    now = datetime.now(timezone.utc)
    output: list[tuple[StoredDocument, object]] = []
    durable_sources: list[dict] = []
    durable_raw_ocr_pages: list[dict] = []
    for idx, page_bytes in enumerate(page_bytes_list):
        ocr_result = run_ocr(page_bytes, lang=effective_lang)
        if "error" in ocr_result:
            raise HTTPException(
                500,
                f"OCR failed on page {idx + 1}: {ocr_result.get('message', 'unknown error')}",
            )
        ocr_items = [
            {"text": r["text"], "confidence": r["confidence"], "bbox": r.get("bbox", {})}
            for r in ocr_result.get("results", [])
        ]
        extraction_result = _kernel.extract(schema, ocr_items, image_bytes=page_bytes)

        structured = _build_fields_dict(extraction_result)
        structured["line_items"] = _build_line_items(extraction_result)
        structured["tables"] = _build_tables(extraction_result)
        if detected_lang_info:
            structured["language_detection"] = detected_lang_info
        if effective_lang:
            structured["ocr_lang"] = effective_lang
        if quality_scores:
            structured["quality_score"] = quality_scores[idx] if idx < len(quality_scores) else quality_scores[0]

        doc_id = first_document_id if idx == 0 and first_document_id else str(uuid.uuid4())
        stored = StoredDocument(
            id=doc_id,
            document_type=extraction_result.document_type,
            structured_json=structured,
            confidence=extraction_result.overall_confidence,
            needs_review=extraction_result.needs_review,
            review_status="needs_review" if extraction_result.needs_review else "pending",
            created_at=now,
            updated_at=now,
            tenant_id=tenant_id,
        )
        # Persist artifacts via storage adapter
        if storage_adapter is not None:
            artifact_keys = [
                f"documents/{doc_id}/raw",
                f"documents/{doc_id}/extracted.json",
                f"documents/{doc_id}/raw.pdf",
            ]
            if artifact_journal is not None and not artifact_journal(artifact_keys):
                raise HTTPException(409, "Extraction job is no longer owned")
            try:
                # Store the original PDF once under the first document
                if is_pdf and original_pdf_bytes and idx == 0:
                    pdf_key = f"documents/{doc_id}/raw.pdf"
                    await storage_adapter.put(
                        pdf_key, original_pdf_bytes, content_type="application/pdf",
                    )
                # Store rendered page as PNG (not the original content type for PDFs)
                page_content_type = "image/png" if is_pdf else (raw_content_type or content_type)
                raw_key = f"documents/{doc_id}/raw"
                await storage_adapter.put(raw_key, page_bytes, content_type=page_content_type)
                structured_key = f"documents/{doc_id}/extracted.json"
                import json as _json
                await storage_adapter.put(
                    structured_key,
                    _json.dumps(structured, default=str, ensure_ascii=False).encode("utf-8"),
                    content_type="application/json",
                )
            except Exception:
                logger.warning("Storage persistence failed for %s", doc_id, exc_info=True)
                cleanup_docs = [doc for doc, _, _ in output] + [stored]
                for cleanup_doc in cleanup_docs:
                    for key in (
                        f"documents/{cleanup_doc.id}/raw",
                        f"documents/{cleanup_doc.id}/extracted.json",
                        f"documents/{cleanup_doc.id}/raw.pdf",
                    ):
                        try:
                            await storage_adapter.delete(key)
                        except Exception:
                            logger.debug("Storage cleanup failed for %s", key, exc_info=True)
                    get_document_store().delete(cleanup_doc.id)
                raise HTTPException(
                    503,
                    "Artifact storage failed; extraction was rolled back",
                )

        if not _durable_mode_enabled() and not defer_durable_commit:
            get_document_store().store(stored)
        if created_document_ids is not None:
            created_document_ids.add(stored.id)
        source = {
            "file_path": f"documents/{doc_id}/raw",
            "file_hash": hashlib.sha256(page_bytes).hexdigest(),
        }
        output.append(
            (
                stored,
                extraction_result,
                {"raw_ocr": ocr_result, "source": source}
                if defer_durable_commit
                else True,
            )
        )
        durable_sources.append(source)
        durable_raw_ocr_pages.append(ocr_result)

    if _durable_mode_enabled() and not defer_durable_commit:
        documents = [document for document, _, _ in output]
        try:
            durable_service = get_durable_invoice_service()
            if idempotency_key and request_fingerprint and canonical_request_id:
                first_document, first_result, _ = output[0]
                canonical_response = {
                    "request_id": canonical_request_id,
                    "status": "completed",
                    "document_type": first_result.document_type,
                    "document_id": first_document.id,
                    "fields": _build_fields_dict(first_result),
                    "line_items": _build_line_items(first_result),
                    "tables": _build_tables(first_result),
                    "confidence": first_result.overall_confidence,
                    "needs_review": first_result.needs_review,
                    "quality_score": first_document.structured_json.get("quality_score"),
                    "storage": {
                        "raw_key": f"documents/{first_document.id}/raw",
                        "structured_key": f"documents/{first_document.id}/extracted.json",
                    },
                    "page_count": len(page_bytes_list),
                }
                persisted_documents = durable_service.store_extractions_and_complete_idempotency(
                    documents,
                    sources=durable_sources,
                    raw_ocr_pages=durable_raw_ocr_pages,
                    actor=actor,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    canonical_response=canonical_response,
                )
            else:
                persisted_documents = durable_service.store_extractions(
                    documents,
                    sources=durable_sources,
                    raw_ocr_pages=durable_raw_ocr_pages,
                    actor=actor,
                )
        except Exception as exc:
            logger.exception("Durable document batch commit failed")
            if storage_adapter is not None:
                for document in documents:
                    for key in (
                        f"documents/{document.id}/raw",
                        f"documents/{document.id}/extracted.json",
                        f"documents/{document.id}/raw.pdf",
                    ):
                        try:
                            await storage_adapter.delete(key)
                        except Exception:
                            logger.debug("Artifact cleanup failed for %s", key, exc_info=True)
            raise HTTPException(
                503,
                "Durable document batch commit failed; extraction was rolled back",
            ) from exc
        output = [
            (persisted_document, extraction_result, True)
            for persisted_document, (_, extraction_result, _) in zip(persisted_documents, output)
        ]
    return output


async def _dispatch_webhook_background(stored_doc: StoredDocument, extraction_result=None) -> None:
    """Fire-and-forget webhook dispatch — errors are logged, never propagated."""
    try:
        doc_type = getattr(extraction_result, "document_type", stored_doc.document_type)
        confidence = getattr(extraction_result, "overall_confidence", stored_doc.confidence)
        needs_review = getattr(extraction_result, "needs_review", stored_doc.needs_review)
        await get_webhook_dispatcher().dispatch(WebhookEvent(
            event_type="document.extraction_completed",
            document_id=stored_doc.id,
            payload={
                "status": "completed",
                "document_type": doc_type,
                "confidence": confidence,
                "needs_review": needs_review,
            },
            timestamp=datetime.now(timezone.utc),
            tenant_id=stored_doc.tenant_id,
        ))
    except Exception:
        logger.warning("Webhook dispatch failed for %s", stored_doc.id, exc_info=True)


async def _index_search_background(
    results: list[tuple[StoredDocument, object, bool]],
) -> None:
    """Fire-and-forget search indexing — errors are logged, never propagated."""
    for doc, _, _ in results:
        try:
            await _get_search_service().index_document(
                doc.id,
                doc.structured_json,
                tenant_id=doc.tenant_id,
            )
        except Exception:
            logger.warning("Search indexing failed for %s", doc.id, exc_info=True)


@router.post("/extract")
async def extract_invoice_jp_sync(
    file: UploadFile = File(...),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
    principal: AuthenticatedPrincipal = Depends(require_operator),
):
    """Synchronous JP invoice extraction."""
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported content type: {file.content_type}")

    content = await _read_upload_with_limit(file)
    if len(content) == 0:
        raise HTTPException(400, "Empty file")

    content_type = file.content_type or ""

    # Atomic idempotency claim BEFORE doing expensive work.
    # claim_id will be the document_id of this request; if a previous request
    # already claimed the key, existing_id points to that stored document.
    placeholder_id = str(uuid.uuid4())
    fingerprint: str | None = None
    lease_task: asyncio.Task | None = None
    durable_idempotency = _durable_mode_enabled() and bool(idempotency_key)
    request_id = str(uuid.uuid4())
    if idempotency_key:
        fingerprint = _request_fingerprint(content, content_type, x_lang)
        scoped_idempotency_key = f"{principal.tenant_id}:{idempotency_key}"
        if durable_idempotency:
            claimed, record = get_durable_invoice_service().claim_idempotency(
                tenant_id=principal.tenant_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                resource_id=placeholder_id,
                expires_at=datetime.now(timezone.utc),
            )
            if not claimed:
                if record["request_fingerprint"] != fingerprint:
                    raise HTTPException(409, "Idempotency key already used with a different payload")
                if record["state"] == "completed" and record["canonical_response_json"] is not None:
                    return record["canonical_response_json"]
                if record["state"] == "pending":
                    return {"document_id": record["resource_id"], "status": "processing"}
                raise HTTPException(409, "Idempotency resource is no longer available")
        else:
            claim_result = await _idempotency_service.claim_or_get_operation(
                scoped_idempotency_key,
                placeholder_id,
                fingerprint,
                pending_ttl_seconds=_IDEMPOTENCY_LEASE_SECONDS,
            )
            if claim_result is None:
                raise HTTPException(503, "Idempotency service unavailable")
            claimed, existing_id, payload_conflict, state = claim_result
            if not claimed:
                if payload_conflict:
                    raise HTTPException(
                        409, "Idempotency key already used with a different payload",
                    )
                cached_doc = get_document_store().get(existing_id or "", principal.tenant_id)
                if state == "completed" and cached_doc:
                    return _build_cache_hit_response(cached_doc)
                if state == "pending":
                    return {
                        "document_id": existing_id,
                        "status": "processing",
                    }
                raise HTTPException(409, "Idempotency resource is no longer available")
            lease_task = asyncio.create_task(
                _renew_operation_lease(scoped_idempotency_key, placeholder_id, fingerprint),
            )

    quality_gate = QualityGate()
    storage_adapter = get_storage_adapter()
    created_document_ids: set[str] = set()

    try:
        results = await _run_extraction_pages(
            content, content_type, x_lang,
            first_document_id=placeholder_id,
            quality_gate=quality_gate,
            storage_adapter=storage_adapter,
            raw_content_type=file.content_type,
            created_document_ids=created_document_ids,
            tenant_id=principal.tenant_id,
            actor=principal.user_id,
            idempotency_key=idempotency_key if durable_idempotency else None,
            request_fingerprint=fingerprint if durable_idempotency else None,
            canonical_request_id=request_id if durable_idempotency else None,
        )
    except Exception:
        await _cleanup_uncommitted_documents(created_document_ids)
        if idempotency_key and fingerprint:
            if durable_idempotency:
                get_durable_invoice_service().release_idempotency(
                    tenant_id=principal.tenant_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                    resource_id=placeholder_id,
                )
            else:
                await _idempotency_service.release_pending_operation(
                    scoped_idempotency_key, placeholder_id, fingerprint,
                )
        raise
    finally:
        if lease_task:
            lease_task.cancel()
            try:
                await lease_task
            except asyncio.CancelledError:
                pass
    if not results:
        raise HTTPException(500, "Extraction produced no results")
    stored_doc, extraction_result, _ = results[0]

    quality_score = stored_doc.structured_json.get("quality_score")

    response = {
        "request_id": request_id,
        "status": "completed",
        "document_type": extraction_result.document_type,
        "document_id": stored_doc.id,
        "fields": _build_fields_dict(extraction_result),
        "line_items": _build_line_items(extraction_result),
        "tables": _build_tables(extraction_result),
        "confidence": extraction_result.overall_confidence,
        "needs_review": extraction_result.needs_review,
        "quality_score": quality_score,
        "storage": {
            "raw_key": f"documents/{stored_doc.id}/raw",
            "structured_key": f"documents/{stored_doc.id}/extracted.json",
        },
        "page_count": len(results),
    }

    # Commit boundary: audit is critical — if it fails, rollback everything.
    # This must happen before promoting the idempotency key so a failed commit
    # never leaves a "completed" idempotency record pointing at rolled-back docs.
    if not _durable_mode_enabled():
        audit_svc = get_audit_log_service()
        try:
            for doc, _, _ in results:
                await audit_svc.log(
                    document_id=doc.id,
                    action=AuditAction.CREATE,
                    actor=principal.user_id,
                    tenant_id=principal.tenant_id,
                )
        except Exception:
            logger.exception("Audit log failed; rolling back extraction")
            await _cleanup_uncommitted_documents(created_document_ids)
            if idempotency_key and fingerprint:
                await _idempotency_service.release_pending_operation(
                    scoped_idempotency_key, placeholder_id, fingerprint,
                )
            raise HTTPException(500, "Audit log failed; extraction was rolled back")

    # Persist canonical response for idempotency cache hits (separate from document data)
    if not _durable_mode_enabled():
        _canonical_responses[stored_doc.id] = response
    promote_ok = True
    if idempotency_key and fingerprint and not durable_idempotency:
        promote_ok = await _idempotency_service.mark_operation_completed(
            scoped_idempotency_key, placeholder_id, fingerprint,
        )
        if not promote_ok:
            logger.error(
                "Idempotency promote failed for key=%s; rolling back extraction",
                idempotency_key,
            )
            await _cleanup_uncommitted_documents(created_document_ids)
            raise HTTPException(
                503, "Idempotency service error; extraction was rolled back",
            )

    # Best-effort: fire-and-forget webhook + search so they never block the response.
    if not _durable_mode_enabled():
        asyncio.create_task(_dispatch_webhook_background(stored_doc, extraction_result))
        asyncio.create_task(_index_search_background(results))

    return response


@router.post("/extract:async")
async def extract_invoice_jp_async(
    file: UploadFile = File(...),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
    principal: AuthenticatedPrincipal = Depends(require_operator),
):
    """Durably queue JP invoice extraction and return a pollable job ID."""
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported content type: {file.content_type}")

    content = await _read_upload_with_limit(file)
    if len(content) == 0:
        raise HTTPException(400, "Empty file")

    content_type = file.content_type or ""
    if not _durable_mode_enabled():
        job_store = get_job_store()
        encoded_image = base64.b64encode(content).decode("ascii")
        fingerprint: str | None = None
        scoped_idempotency_key: str | None = None
        if idempotency_key:
            fingerprint = _request_fingerprint(content, content_type, x_lang)
            scoped_idempotency_key = f"{principal.tenant_id}:{idempotency_key}"
            recovered_job = job_store.find_job_by_idempotency(
                principal.tenant_id,
                scoped_idempotency_key,
                fingerprint,
            )
            if recovered_job is not None and recovered_job.get("status") not in {
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                return {"job_id": recovered_job["job_id"], "status": "received"}
        job_info = job_store.create_job(
            images=[encoded_image],
            lang=x_lang or "ja",
            tenant_id=principal.tenant_id,
            idempotency_key=scoped_idempotency_key,
            request_fingerprint=fingerprint,
        )
        job_id = job_info["job_id"]
        if idempotency_key:
            assert fingerprint is not None
            assert scoped_idempotency_key is not None
            claim_result = await _idempotency_service.claim_or_get_operation(
                scoped_idempotency_key,
                job_id,
                fingerprint,
            )
            if claim_result is None:
                job_store.delete_job(job_id)
                raise HTTPException(503, "Idempotency service unavailable")
            claimed, existing_id, payload_conflict, _state = claim_result
            if not claimed:
                job_store.delete_job(job_id)
                if payload_conflict:
                    raise HTTPException(409, "Idempotency key already used with a different payload")
                existing_job = job_store.get_job(existing_id or "")
                if existing_job is None or existing_job.get("tenant_id") != principal.tenant_id:
                    raise HTTPException(409, "Idempotency resource is no longer available")
                return {"job_id": existing_id, "status": "received"}

        async def run_legacy_job() -> None:
            created_document_ids: set[str] = set()
            try:
                if not job_store.update_job(
                    job_id,
                    status=JobStatus.RUNNING,
                    expected_statuses=(JobStatus.QUEUED,),
                ):
                    return
                results = await _run_extraction_pages(
                    content,
                    content_type,
                    x_lang,
                    quality_gate=QualityGate(),
                    storage_adapter=get_storage_adapter(),
                    raw_content_type=content_type,
                    created_document_ids=created_document_ids,
                    tenant_id=principal.tenant_id,
                    actor=principal.user_id,
                )
                payload_results = [
                    {
                        "status": "success",
                        "document_id": document.id,
                        "document_type": document.document_type,
                        "confidence": document.confidence,
                        "needs_review": document.needs_review,
                    }
                    for document, _, _ in results
                ]
                if job_store.update_job(
                    job_id,
                    status=JobStatus.COMPLETED,
                    results=payload_results,
                    progress={"processed": len(results), "total": len(results)},
                    expected_statuses=(JobStatus.RUNNING,),
                ) and idempotency_key and fingerprint:
                    await _idempotency_service.mark_operation_completed(
                        scoped_idempotency_key,
                        job_id,
                        fingerprint,
                    )
            except HTTPException as exc:
                await _cleanup_uncommitted_documents(created_document_ids)
                job_store.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    error=str(exc.detail),
                    expected_statuses=(JobStatus.RUNNING,),
                )
            except Exception as exc:
                logger.exception("Legacy async extraction failed for job %s", job_id)
                await _cleanup_uncommitted_documents(created_document_ids)
                job_store.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    error=str(exc),
                    expected_statuses=(JobStatus.RUNNING,),
                )

        task = asyncio.create_task(run_legacy_job())
        background_tasks = getattr(extract_invoice_jp_async, "_bg_tasks", set())
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        extract_invoice_jp_async._bg_tasks = background_tasks
        return {"job_id": job_id, "status": "received"}

    job_id = f"job_{uuid.uuid4().hex}"
    source_key = f"jobs/{job_id}/source"
    fingerprint = _request_fingerprint(content, content_type, x_lang)
    durable_key = idempotency_key or f"async-job:{job_id}"
    response = {"job_id": job_id, "status": "received"}
    repository = get_invoice_repository()
    claimed, existing = repository.claim_idempotency_record(
        tenant_id=principal.tenant_id,
        idempotency_key=durable_key,
        request_fingerprint=fingerprint,
        resource_id=job_id,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=_IDEMPOTENCY_LEASE_SECONDS),
    )
    if not claimed:
        if existing["request_fingerprint"] != fingerprint:
            raise HTTPException(409, "Idempotency key already used with a different payload")
        if existing["state"] == "completed" and existing["canonical_response_json"]:
            return existing["canonical_response_json"]
        return {"job_id": existing["resource_id"], "status": "received"}

    storage_adapter = get_storage_adapter()
    try:
        await storage_adapter.put(source_key, content, content_type=content_type)
    except Exception as exc:
        repository.release_idempotency_record(
            tenant_id=principal.tenant_id,
            idempotency_key=durable_key,
            request_fingerprint=fingerprint,
            resource_id=job_id,
        )
        raise HTTPException(503, "Artifact storage failed; extraction was not queued") from exc

    try:
        repository.create_extraction_job_and_complete_idempotency(
            job_id=job_id,
            tenant_id=principal.tenant_id,
            source_key=source_key,
            source_file_hash=hashlib.sha256(content).hexdigest(),
            content_type=content_type,
            ocr_lang=x_lang or "ja",
            idempotency_key=durable_key,
            request_fingerprint=fingerprint,
            canonical_response=response,
        )
    except Exception as exc:
        try:
            await storage_adapter.delete(source_key)
        except Exception:
            logger.warning("Failed to clean queued extraction artifact %s", source_key, exc_info=True)
        repository.release_idempotency_record(
            tenant_id=principal.tenant_id,
            idempotency_key=durable_key,
            request_fingerprint=fingerprint,
            resource_id=job_id,
        )
        raise HTTPException(503, "Durable extraction queue unavailable") from exc

    return response


@router.get("/{document_id}")
async def get_invoice_jp(
    document_id: str,
    principal: AuthenticatedPrincipal = Depends(require_operator),
):
    """Fetch a JP invoice document by ID."""
    doc = (
        get_durable_invoice_service().get(document_id, tenant_id=principal.tenant_id)
        if _durable_mode_enabled()
        else get_document_store().get(document_id, principal.tenant_id)
    )
    if doc is None:
        raise HTTPException(404, f"Document not found: {document_id}")
    # Filter out internal system keys (e.g. _canonical_response, _page_count)
    fields = {k: v for k, v in (doc.structured_json or {}).items() if not k.startswith("_")}
    return {
        "document_id": doc.id,
        "document_type": doc.document_type,
        "status": doc.review_status,
        "fields": fields,
        "confidence": doc.confidence,
        "needs_review": doc.needs_review,
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


@router.post("/{document_id}/approve")
async def approve_invoice_jp(
    document_id: str,
    x_reason: Optional[str] = Header(None, alias="X-Reason"),
    principal: AuthenticatedPrincipal = Depends(require_document_reviewer),
):
    """Approve a JP invoice."""
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
                principal.user_id,
                x_reason,
                tenant_id=principal.tenant_id,
            )
        )
    except ValueError:
        raise HTTPException(404, f"Document not found: {document_id}")
    except PermissionError as exc:
        raise HTTPException(409, str(exc))
    except RuntimeError:
        raise HTTPException(409, "Document review changed; retry with the latest document")
    return {"document_id": doc.id, "status": "approved", "actor": principal.user_id}


@router.post("/{document_id}/reject")
async def reject_invoice_jp(
    document_id: str,
    x_reason: Optional[str] = Header(None, alias="X-Reason"),
    principal: AuthenticatedPrincipal = Depends(require_document_reviewer),
):
    """Reject a JP invoice."""
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
                principal.user_id,
                x_reason,
                tenant_id=principal.tenant_id,
            )
        )
    except ValueError:
        raise HTTPException(404, f"Document not found: {document_id}")
    except PermissionError as exc:
        raise HTTPException(409, str(exc))
    except RuntimeError:
        raise HTTPException(409, "Document review changed; retry with the latest document")
    return {
        "document_id": doc.id,
        "status": "rejected",
        "actor": principal.user_id,
        "reason": x_reason,
    }


@router.patch("/{document_id}/fields")
async def patch_invoice_jp_fields(
    document_id: str,
    body: dict,
    x_reason: Optional[str] = Header(None, alias="X-Reason"),
    x_force: Optional[str] = Header(None, alias="X-Force"),
    principal: AuthenticatedPrincipal = Depends(require_document_reviewer),
):
    """Patch fields on a JP invoice (with audit)."""
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
                body,
                principal.user_id,
                x_reason,
                force=force,
                tenant_id=principal.tenant_id,
            )
        )
    except PermissionError as exc:
        raise HTTPException(409, str(exc))
    except ValueError:
        raise HTTPException(404, f"Document not found: {document_id}")
    response = {
        "document_id": result.id if _durable_mode_enabled() else result.document.id,
        "status": "patched",
        "actor": principal.user_id,
    }
    if not _durable_mode_enabled() and result.warnings:
        response["warnings"] = result.warnings
    return response
