"""Invoice extraction router."""

import io
import json
import logging
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.auth import verify_api_key
from app.config import get_settings
from app.routers.ocr import (
    _handle_processing_error,
    _handle_ocr_error,
    _validate_image_size,
    process_single_image,
)
from app.schemas.invoice import (
    InvoiceBatchResponse,
    InvoiceBatchItem,
    InvoiceData,
    InvoiceDebugResponse,
    InvoiceExtractResponse,
    InvoiceValidationResult,
)
from app.schemas.responses import ErrorResponse
from app.services.ocr_engine import run_ocr
from app.utils.image_utils import base64_to_bytes
from app.utils.metrics import record_request, record_invoice_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoice", tags=["Invoice"])


def _check_extraction_enabled(settings, request_id: str):
    """Return 503 JSONResponse if invoice extraction is disabled."""
    if not settings.INVOICE_ENABLE_EXTRACTION:
        return JSONResponse(
            status_code=503,
            content=ErrorResponse(
                error="extraction_disabled",
                detail="Invoice extraction is disabled by configuration",
                request_id=request_id,
            ).model_dump(),
        )
    return None


def _build_invoice_response(
    result: dict,
    request_id: str,
    include_debug: bool = False,
) -> InvoiceExtractResponse:
    """Build InvoiceExtractResponse from OCR result."""
    summary = result.get("summary", {})
    return InvoiceExtractResponse(
        request_id=request_id,
        status="success",
        invoice=InvoiceData(),
        line_items_status="not_extracted",
        validation=InvoiceValidationResult(is_valid=True),
        ocr={
            "summary": {
                "total_lines": summary.get("total_lines", 0),
                "total_characters": summary.get("total_characters", 0),
                "avg_confidence": summary.get("avg_confidence", 0.0),
            }
        },
    )


def _build_debug_response(
    result: dict,
    request_id: str,
) -> InvoiceDebugResponse:
    """Build InvoiceDebugResponse from OCR result."""
    base = _build_invoice_response(result, request_id)
    return InvoiceDebugResponse(
        request_id=base.request_id,
        status=base.status,
        invoice=base.invoice,
        line_items_status=base.line_items_status,
        validation=base.validation,
        ocr=base.ocr,
    )


def _error_response(status_code: int, error: str, detail: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=error, detail=detail, request_id=request_id).model_dump(),
    )


@router.post(
    "/extract",
    response_model=InvoiceExtractResponse,
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def extract_invoice(
    file: UploadFile = File(..., description="Image file to process"),
    lang_form: Optional[str] = Form(None, alias="lang"),
    min_confidence_form: Optional[float] = Form(None, alias="min_confidence"),
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
    x_min_confidence: Optional[float] = Header(None, alias="X-Min-Confidence"),
):
    """Extract invoice data from an uploaded image file."""
    settings = get_settings()
    request_id = str(uuid.uuid4())
    start_time = time.time()

    disabled = _check_extraction_enabled(settings, request_id)
    if disabled:
        return disabled

    lang = x_lang or lang_form or settings.MODEL_LANG
    min_confidence = (
        x_min_confidence
        if x_min_confidence is not None
        else (min_confidence_form if min_confidence_form is not None else settings.MIN_CONFIDENCE)
    )

    try:
        image_bytes = await file.read()
        size_error = _validate_image_size(image_bytes, request_id, settings, "Image file is empty")
        if size_error:
            return size_error

        result = process_single_image(
            image_bytes,
            lang=lang,
            min_confidence=min_confidence,
            include_polygon=settings.INCLUDE_POLYGON,
        )
        ocr_error = _handle_ocr_error(result, request_id)
        if ocr_error:
            return ocr_error

        response = _build_invoice_response(result, request_id)

        # Store invoice if postgres backend enabled
        invoice_id = None
        if settings.INVOICE_STORAGE_BACKEND == "postgres":
            try:
                from app.repositories.invoice_repository import get_invoice_repository
                repo = get_invoice_repository()
                invoice_id = repo.save_invoice({
                    "source": {"file_path": file.filename},
                    "raw_ocr": result,
                    "extracted": response.invoice.model_dump(),
                    "validation": response.validation.model_dump(),
                })
                response.request_id = invoice_id
            except Exception:
                logger.exception("Failed to store invoice")

        duration = time.time() - start_time
        record_request("/invoice/extract", lang, "success", duration)
        return response

    except ValueError as e:
        record_request("/invoice/extract", lang, "error", time.time() - start_time)
        return _handle_processing_error(str(e), request_id, settings, "Image file is empty")
    except Exception as e:
        record_request("/invoice/extract", lang, "error", time.time() - start_time)
        logger.error(f"Invoice extract request failed: {e}")
        return _error_response(500, "internal_error", "Internal server error during invoice processing", request_id)


@router.post(
    "/extract/json",
    response_model=InvoiceExtractResponse,
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def extract_invoice_json(
    image: str = Form(..., description="Base64-encoded image data"),
    lang_form: Optional[str] = Form(None, alias="lang"),
    min_confidence_form: Optional[float] = Form(None, alias="min_confidence"),
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
    x_min_confidence: Optional[float] = Header(None, alias="X-Min-Confidence"),
):
    """Extract invoice data from a base64-encoded image."""
    settings = get_settings()
    request_id = str(uuid.uuid4())
    start_time = time.time()

    disabled = _check_extraction_enabled(settings, request_id)
    if disabled:
        return disabled

    lang = x_lang or lang_form or settings.MODEL_LANG
    min_confidence = (
        x_min_confidence
        if x_min_confidence is not None
        else (min_confidence_form if min_confidence_form is not None else settings.MIN_CONFIDENCE)
    )

    try:
        image_bytes = base64_to_bytes(image)
        size_error = _validate_image_size(image_bytes, request_id, settings, "Image data is empty")
        if size_error:
            return size_error

        result = process_single_image(
            image_bytes,
            lang=lang,
            min_confidence=min_confidence,
            include_polygon=settings.INCLUDE_POLYGON,
        )
        ocr_error = _handle_ocr_error(result, request_id)
        if ocr_error:
            return ocr_error

        response = _build_invoice_response(result, request_id)

        # Store invoice if postgres backend enabled
        if settings.INVOICE_STORAGE_BACKEND == "postgres":
            try:
                from app.repositories.invoice_repository import get_invoice_repository
                repo = get_invoice_repository()
                invoice_id = repo.save_invoice({
                    "source": {},
                    "raw_ocr": result,
                    "extracted": response.invoice.model_dump(),
                    "validation": response.validation.model_dump(),
                })
                response.request_id = invoice_id
            except Exception:
                logger.exception("Failed to store invoice")

        duration = time.time() - start_time
        record_request("/invoice/extract/json", lang, "success", duration)
        return response

    except ValueError as e:
        record_request("/invoice/extract/json", lang, "error", time.time() - start_time)
        return _handle_processing_error(str(e), request_id, settings, "Image data is empty")
    except Exception as e:
        record_request("/invoice/extract/json", lang, "error", time.time() - start_time)
        logger.error(f"Invoice extract JSON request failed: {e}")
        return _error_response(500, "internal_error", "Internal server error during invoice processing", request_id)


@router.post(
    "/debug",
    response_model=InvoiceDebugResponse,
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def debug_invoice(
    file: UploadFile = File(..., description="Image file to process"),
    lang_form: Optional[str] = Form(None, alias="lang"),
    min_confidence_form: Optional[float] = Form(None, alias="min_confidence"),
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
    x_min_confidence: Optional[float] = Header(None, alias="X-Min-Confidence"),
):
    """Debug endpoint: returns invoice extraction with additional diagnostic fields."""
    settings = get_settings()
    request_id = str(uuid.uuid4())
    start_time = time.time()

    disabled = _check_extraction_enabled(settings, request_id)
    if disabled:
        return disabled

    lang = x_lang or lang_form or settings.MODEL_LANG
    min_confidence = (
        x_min_confidence
        if x_min_confidence is not None
        else (min_confidence_form if min_confidence_form is not None else settings.MIN_CONFIDENCE)
    )

    try:
        image_bytes = await file.read()
        size_error = _validate_image_size(image_bytes, request_id, settings, "Image file is empty")
        if size_error:
            return size_error

        result = process_single_image(
            image_bytes,
            lang=lang,
            min_confidence=min_confidence,
            include_polygon=settings.INCLUDE_POLYGON,
        )
        ocr_error = _handle_ocr_error(result, request_id)
        if ocr_error:
            return ocr_error

        response = _build_debug_response(result, request_id)
        duration = time.time() - start_time
        record_request("/invoice/debug", lang, "success", duration)
        return response

    except ValueError as e:
        record_request("/invoice/debug", lang, "error", time.time() - start_time)
        return _handle_processing_error(str(e), request_id, settings, "Image file is empty")
    except Exception as e:
        record_request("/invoice/debug", lang, "error", time.time() - start_time)
        logger.error(f"Invoice debug request failed: {e}")
        return _error_response(500, "internal_error", "Internal server error during invoice processing", request_id)


@router.post(
    "/batch",
    response_model=InvoiceBatchResponse,
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def invoice_batch(
    files: List[UploadFile] = File(..., description="Image files to process"),
    mode: str = Form("strict"),
    lang_form: Optional[str] = Form(None, alias="lang"),
    min_confidence_form: Optional[float] = Form(None, alias="min_confidence"),
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
    x_min_confidence: Optional[float] = Header(None, alias="X-Min-Confidence"),
):
    """Process multiple invoice images synchronously."""
    settings = get_settings()
    request_id = str(uuid.uuid4())
    start_time = time.time()

    disabled = _check_extraction_enabled(settings, request_id)
    if disabled:
        return disabled

    lang = x_lang or lang_form or settings.MODEL_LANG
    min_confidence = (
        x_min_confidence
        if x_min_confidence is not None
        else (min_confidence_form if min_confidence_form is not None else settings.MIN_CONFIDENCE)
    )

    if len(files) > settings.MAX_BATCH_SIZE:
        return _error_response(
            400,
            "batch_too_large",
            f"Batch size {len(files)} exceeds maximum {settings.MAX_BATCH_SIZE}",
            request_id,
        )

    if len(files) == 0:
        return _error_response(400, "empty_batch", "No files provided", request_id)

    results: list[InvoiceBatchItem] = []
    success_count = 0
    error_count = 0

    for idx, file in enumerate(files):
        filename = file.filename or f"image_{idx}"
        try:
            image_bytes = await file.read()

            if len(image_bytes) == 0:
                results.append(InvoiceBatchItem(
                    filename=filename, status="error", error="Image file is empty",
                ))
                error_count += 1
                continue

            if len(image_bytes) > settings.max_image_size_bytes:
                results.append(InvoiceBatchItem(
                    filename=filename, status="error",
                    error=f"Image exceeds maximum size of {settings.MAX_IMAGE_SIZE_MB}MB",
                ))
                error_count += 1
                continue

            result = process_single_image(
                image_bytes,
                lang=lang,
                min_confidence=min_confidence,
                include_polygon=settings.INCLUDE_POLYGON,
            )
            ocr_error = _handle_ocr_error(result, request_id)
            if ocr_error:
                results.append(InvoiceBatchItem(
                    filename=filename, status="error",
                    error=f"OCR processing failed",
                ))
                error_count += 1
                continue

            response = _build_invoice_response(result, request_id)
            results.append(InvoiceBatchItem(
                filename=filename, status="success", invoice=response.invoice,
            ))
            success_count += 1

        except ValueError as e:
            results.append(InvoiceBatchItem(
                filename=filename, status="error",
                error=f"Image processing error: {e}",
            ))
            error_count += 1
        except Exception as e:
            results.append(InvoiceBatchItem(
                filename=filename, status="error",
                error=f"Unexpected error: {e}",
            ))
            error_count += 1

    duration = time.time() - start_time
    status = "success" if error_count == 0 else "partial" if success_count > 0 else "error"
    record_request("/invoice/batch", lang, status, duration, batch_size=len(files), job_type="sync")

    return InvoiceBatchResponse(
        request_id=request_id,
        status=status,
        results=results,
    )


def _get_repository():
    from app.repositories.invoice_repository import get_invoice_repository
    return get_invoice_repository()


def _row_to_response(row: dict) -> InvoiceExtractResponse:
    """Convert a repository row dict to InvoiceExtractResponse."""
    extracted = row.get("extracted_json") or {}
    validation = row.get("validation_json") or {}
    return InvoiceExtractResponse(
        request_id=row["id"],
        status="success",
        invoice=InvoiceData(**extracted) if extracted else InvoiceData(),
        confidence=extracted.get("confidence"),
        line_items_status="extracted" if extracted.get("line_items") else "not_extracted",
        validation=InvoiceValidationResult(**validation) if validation else InvoiceValidationResult(is_valid=True),
        needs_review=row.get("review_status") == "needs_review",
        ocr=None,
    )


@router.get(
    "/{invoice_id}",
    response_model=InvoiceExtractResponse,
    dependencies=[Depends(verify_api_key)],
    responses={404: {"model": ErrorResponse}},
)
async def get_invoice(invoice_id: str, api_key: str = Depends(verify_api_key)):
    """Fetch stored invoice by ID."""
    repo = _get_repository()
    row = repo.get_invoice(invoice_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _row_to_response(row)


@router.patch(
    "/{invoice_id}/fields",
    response_model=InvoiceExtractResponse,
    dependencies=[Depends(verify_api_key)],
    responses={404: {"model": ErrorResponse}},
)
async def update_invoice_fields(
    invoice_id: str,
    updates: dict,
    reason: str = "",
    api_key: str = Depends(verify_api_key),
):
    """Update specific invoice fields. Creates audit log entry."""
    repo = _get_repository()
    row = repo.get_invoice(invoice_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    ok = repo.update_invoice(invoice_id, updates, actor="api", reason=reason)
    if not ok:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    row = repo.get_invoice(invoice_id)
    return _row_to_response(row)


@router.post(
    "/{invoice_id}/approve",
    response_model=InvoiceExtractResponse,
    dependencies=[Depends(verify_api_key)],
    responses={404: {"model": ErrorResponse}},
)
async def approve_invoice(invoice_id: str, api_key: str = Depends(verify_api_key)):
    """Approve invoice for export."""
    from app.repositories.invoice_repository import ReviewStatus
    repo = _get_repository()
    row = repo.get_invoice(invoice_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    repo.update_invoice(invoice_id, {"review_status": ReviewStatus.REVIEWED}, actor="api", reason="approved")
    row = repo.get_invoice(invoice_id)
    return _row_to_response(row)


@router.post(
    "/{invoice_id}/reject",
    response_model=InvoiceExtractResponse,
    dependencies=[Depends(verify_api_key)],
    responses={404: {"model": ErrorResponse}},
)
async def reject_invoice(invoice_id: str, reason: str = "", api_key: str = Depends(verify_api_key)):
    """Reject invoice."""
    from app.repositories.invoice_repository import ReviewStatus
    repo = _get_repository()
    row = repo.get_invoice(invoice_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    repo.update_invoice(invoice_id, {"review_status": ReviewStatus.REJECTED}, actor="api", reason=reason or "rejected")
    row = repo.get_invoice(invoice_id)
    return _row_to_response(row)
