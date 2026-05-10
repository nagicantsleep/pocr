"""OCR router for single and batch image processing."""

import io
import logging
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.schemas.requests import BatchOCRRequest, OCRRequest, StructuredOCRRequest
from app.schemas.responses import (
    BatchOCRResponse,
    ErrorResponse,
    ImageOCRResult,
    OCRResponse,
    StructuredJobCreateResponse,
    StructuredJobResponse,
    StructuredOCRResponse,
)
from app.services.job_store import get_job_store
from app.services.structured_extraction import StandardizerError, build_structured_response
from app.services.structured_job_store import get_structured_job_repository
from app.services.structured_queue import get_structured_job_publisher
from app.utils.image_utils import base64_to_bytes, validate_and_preprocess
from app.utils.metrics import record_request
from app.auth import verify_api_key
from app.services.ocr_engine import run_ocr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ocr", tags=["OCR"])


def process_single_image(
    image_bytes: bytes,
    lang: str,
    min_confidence: float,
    include_polygon: bool = True,
) -> dict:
    """
    Process a single image with OCR.

    Args:
        image_bytes: Raw image bytes
        lang: Language code
        min_confidence: Minimum confidence threshold
        include_polygon: Include polygon points

    Returns:
        OCR result dictionary
    """
    # Preprocess image
    processed_bytes, was_resized = validate_and_preprocess(image_bytes)

    # Update OCR meta if resized
    result = run_ocr(
        processed_bytes,
        lang=lang,
        min_confidence=min_confidence,
        include_polygon=include_polygon,
    )
    # Update was_resized in meta
    if "meta" in result:
        result["meta"]["was_resized"] = was_resized

    return result


def _build_ocr_results(result: dict) -> list:
    from app.schemas.responses import BBox, OCRResult

    ocr_results = []
    for r in result.get("results", []):
        bbox_data = r.get("bbox", {"top_left": [0, 0], "bottom_right": [0, 0]})
        normalized_data = r.get(
            "bbox_normalized",
            {"top_left": [0.0, 0.0], "bottom_right": [0.0, 0.0]},
        )

        ocr_results.append(
            OCRResult(
                text=r.get("text", ""),
                confidence=r.get("confidence", 0.0),
                bbox=BBox(
                    top_left=bbox_data.get("top_left", [0, 0]),
                    bottom_right=bbox_data.get("bottom_right", [0, 0]),
                ),
                bbox_normalized=BBox(
                    top_left=normalized_data.get("top_left", [0.0, 0.0]),
                    bottom_right=normalized_data.get("bottom_right", [0.0, 0.0]),
                ),
                type=r.get("type", "text"),
                polygon=r.get("polygon", []),
            )
        )
    return ocr_results


def build_ocr_response(
    result: dict,
    request_id: str,
    status: str = "success",
) -> OCRResponse:
    """Build OCR response from result dictionary."""
    from app.schemas.responses import OCRMeta, OCRSummary

    meta_data = result.get("meta", {})
    summary_data = result.get("summary", {})

    return OCRResponse(
        request_id=request_id,
        status=status,
        meta=OCRMeta(
            engine=meta_data.get("engine", "paddleocr"),
            engine_version=meta_data.get("engine_version", "3.5.0"),
            model=meta_data.get("model", "unknown"),
            lang=meta_data.get("lang", "en"),
            inference_time_ms=meta_data.get("inference_time_ms", 0),
            image_width=meta_data.get("image_width"),
            image_height=meta_data.get("image_height"),
            was_resized=meta_data.get("was_resized", False),
        ),
        results=_build_ocr_results(result),
        summary=OCRSummary(
            total_lines=summary_data.get("total_lines", 0),
            total_characters=summary_data.get("total_characters", 0),
            avg_confidence=summary_data.get("avg_confidence", 0.0),
        ),
    )


def build_structured_ocr_response(
    result: dict,
    request_id: str,
    image_url: str | None = None,
) -> StructuredOCRResponse:
    return build_structured_response(
        raw_result=result,
        raw_ocr_results=_build_ocr_results(result),
        request_id=request_id,
        image_url=image_url,
    )


def _error_response(status_code: int, error: str, detail: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=error,
            detail=detail,
            request_id=request_id,
        ).model_dump(),
    )


def _validate_image_size(image_bytes: bytes, request_id: str, settings, empty_detail: str) -> JSONResponse | None:
    if len(image_bytes) == 0:
        return _error_response(400, "image_empty", empty_detail, request_id)
    if len(image_bytes) > settings.max_image_size_bytes:
        return _error_response(
            413,
            "file_too_large",
            f"Image size {len(image_bytes)} exceeds maximum {settings.max_image_size_bytes}",
            request_id,
        )
    return None


def _handle_processing_error(error_msg: str, request_id: str, settings, empty_detail: str) -> JSONResponse:
    if "image_empty" in error_msg:
        return _error_response(400, "image_empty", empty_detail, request_id)
    if "file_too_large" in error_msg:
        return _error_response(
            413,
            "file_too_large",
            f"Image exceeds maximum size of {settings.MAX_IMAGE_SIZE_MB}MB",
            request_id,
        )
    if "unsupported_format" in error_msg:
        return _error_response(
            415,
            "unsupported_format",
            "Unsupported image format. Allowed: JPEG, PNG, BMP, TIFF, WebP",
            request_id,
        )
    if "Invalid base64" in error_msg:
        return _error_response(400, "invalid_base64", "Invalid base64 encoded image data", request_id)
    return _error_response(422, "unreadable_image", f"Cannot process image: {error_msg}", request_id)


def _handle_ocr_error(result: dict, request_id: str) -> JSONResponse | None:
    if "error" in result:
        return _error_response(
            500,
            result["error"],
            result.get("message", "OCR processing failed"),
            request_id,
        )
    return None


def _record_and_return(path: str, lang: str, start_time: float, payload):
    duration = time.time() - start_time
    record_request(path, lang, "success", duration)
    return JSONResponse(content=payload.model_dump(by_alias=True, mode="json", exclude_none=True))


def _record_error(path: str, lang: str, start_time: float):
    duration = time.time() - start_time
    record_request(path, lang, "error", duration)


@router.post(
    "/structured",
    response_model=StructuredJobCreateResponse,
    status_code=202,
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        413: {"model": ErrorResponse, "description": "Payload Too Large"},
        415: {"model": ErrorResponse, "description": "Unsupported Media Type"},
        422: {"model": ErrorResponse, "description": "Unprocessable Entity"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)
async def ocr_single_structured(
    file: UploadFile = File(..., description="Image file to process"),
    lang_form: Optional[str] = Form(None, alias="lang"),
    min_confidence_form: Optional[float] = Form(None, alias="min_confidence"),
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
    x_min_confidence: Optional[float] = Header(None, alias="X-Min-Confidence"),
):
    settings = get_settings()
    request_id = str(uuid.uuid4())
    start_time = time.time()
    lang = x_lang or lang_form or settings.MODEL_LANG
    min_confidence = x_min_confidence if x_min_confidence is not None else (min_confidence_form if min_confidence_form is not None else settings.MIN_CONFIDENCE)

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
        provider = settings.STANDARDIZER_PROVIDER.strip().lower() or "heuristic"
        job = get_structured_job_repository().create_job(result, provider=provider)
        get_structured_job_publisher().publish(
            {"job_id": job["job_id"], "provider": provider},
            topic=settings.STRUCTURED_STANDARDIZE_TOPIC,
        )
        duration = time.time() - start_time
        record_request("/ocr/structured", lang, "success", duration)
        return StructuredJobCreateResponse(
            job_id=job["job_id"],
            status=job["status"],
            status_url=f"/ocr/structured/jobs/{job['job_id']}",
        )
    except ValueError as e:
        _record_error("/ocr/structured", lang, start_time)
        return _handle_processing_error(str(e), request_id, settings, "Image file is empty")
    except StandardizerError as e:
        _record_error("/ocr/structured", lang, start_time)
        logger.error(f"Structured standardization failed: {e}")
        return _error_response(502, "standardizer_failed", str(e), request_id)
    except Exception as e:
        _record_error("/ocr/structured", lang, start_time)
        logger.error(f"Structured OCR request failed: {e}")
        return _error_response(500, "internal_error", "Internal server error during OCR processing", request_id)


@router.get(
    "/structured/jobs/{job_id}",
    response_model=StructuredJobResponse,
    dependencies=[Depends(verify_api_key)],
    responses={
        404: {"model": ErrorResponse, "description": "Job Not Found"},
    },
)
async def get_structured_job(job_id: str):
    job = get_structured_job_repository().get_job(job_id)
    if job is None:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error="job_not_found",
                detail=f"Structured OCR job {job_id} not found",
                request_id=job_id,
            ).model_dump(),
        )
    return StructuredJobResponse(
        job_id=job["job_id"],
        provider=job["provider"],
        status=job["status"],
        created_at=job.get("created_at"),
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        structured_json=job.get("structured_json"),
        error=job.get("error"),
    )

@router.post(
    "/structured/json",
    response_model=StructuredOCRResponse,
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        413: {"model": ErrorResponse, "description": "Payload Too Large"},
        415: {"model": ErrorResponse, "description": "Unsupported Media Type"},
        422: {"model": ErrorResponse, "description": "Unprocessable Entity"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)
async def ocr_single_structured_json(
    request: StructuredOCRRequest,
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
    x_min_confidence: Optional[float] = Header(None, alias="X-Min-Confidence"),
):
    settings = get_settings()
    request_id = str(uuid.uuid4())
    start_time = time.time()
    lang = x_lang or request.lang or settings.MODEL_LANG
    min_confidence = x_min_confidence or request.min_confidence

    try:
        image_bytes = base64_to_bytes(request.image)
        size_error = _validate_image_size(image_bytes, request_id, settings, "Image data is empty")
        if size_error:
            return size_error
        result = process_single_image(
            image_bytes,
            lang=lang,
            min_confidence=min_confidence,
            include_polygon=request.include_polygon,
        )
        ocr_error = _handle_ocr_error(result, request_id)
        if ocr_error:
            return ocr_error
        response = build_structured_ocr_response(result, request_id, image_url=request.image_url)
        return _record_and_return("/ocr/structured/json", lang, start_time, response)
    except ValueError as e:
        _record_error("/ocr/structured/json", lang, start_time)
        return _handle_processing_error(str(e), request_id, settings, "Image data is empty")
    except StandardizerError as e:
        _record_error("/ocr/structured/json", lang, start_time)
        logger.error(f"Structured JSON standardization failed: {e}")
        return _error_response(502, "standardizer_failed", str(e), request_id)
    except Exception as e:
        _record_error("/ocr/structured/json", lang, start_time)
        logger.error(f"Structured OCR JSON request failed: {e}")
        return _error_response(500, "internal_error", "Internal server error during OCR processing", request_id)


@router.post(
    "",
    response_model=OCRResponse,
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        413: {"model": ErrorResponse, "description": "Payload Too Large"},
        415: {"model": ErrorResponse, "description": "Unsupported Media Type"},
        422: {"model": ErrorResponse, "description": "Unprocessable Entity"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)
async def ocr_single(
    file: UploadFile = File(..., description="Image file to process"),
    lang_form: Optional[str] = Form(None, alias="lang"),
    min_confidence_form: Optional[float] = Form(None, alias="min_confidence"),
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
    x_min_confidence: Optional[float] = Header(None, alias="X-Min-Confidence"),
    x_layout_analysis: Optional[bool] = Header(None, alias="X-Layout-Analysis"),
):
    """
    Process a single image with OCR.

    Accepts image file upload with optional headers for configuration.
    """
    settings = get_settings()
    request_id = str(uuid.uuid4())
    start_time = time.time()
    lang = x_lang or lang_form or settings.MODEL_LANG
    min_confidence = x_min_confidence if x_min_confidence is not None else (min_confidence_form if min_confidence_form is not None else settings.MIN_CONFIDENCE)

    try:
        # Read file content
        image_bytes = await file.read()

        # Validate file size
        if len(image_bytes) == 0:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="image_empty",
                    detail="Image file is empty",
                    request_id=request_id,
                ).model_dump(),
            )

        if len(image_bytes) > settings.max_image_size_bytes:
            return JSONResponse(
                status_code=413,
                content=ErrorResponse(
                    error="file_too_large",
                    detail=f"Image size {len(image_bytes)} exceeds maximum {settings.max_image_size_bytes}",
                    request_id=request_id,
                ).model_dump(),
            )

        # Process image
        result = process_single_image(
            image_bytes,
            lang=lang,
            min_confidence=min_confidence,
            include_polygon=settings.INCLUDE_POLYGON,
        )

        # Check for error
        if "error" in result:
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error=result["error"],
                    detail=result.get("message", "OCR processing failed"),
                    request_id=request_id,
                ).model_dump(),
            )

        # Build response
        response = build_ocr_response(result, request_id)

        # Record metrics
        duration = time.time() - start_time
        record_request("/ocr", lang, "success", duration)

        return response

    except ValueError as e:
        error_msg = str(e)
        duration = time.time() - start_time

        if "image_empty" in error_msg:
            record_request("/ocr", lang, "error", duration)
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="image_empty",
                    detail="Image file is empty",
                    request_id=request_id,
                ).model_dump(),
            )
        elif "file_too_large" in error_msg:
            record_request("/ocr", lang, "error", duration)
            return JSONResponse(
                status_code=413,
                content=ErrorResponse(
                    error="file_too_large",
                    detail=f"Image exceeds maximum size of {settings.MAX_IMAGE_SIZE_MB}MB",
                    request_id=request_id,
                ).model_dump(),
            )
        elif "unsupported_format" in error_msg:
            record_request("/ocr", lang, "error", duration)
            return JSONResponse(
                status_code=415,
                content=ErrorResponse(
                    error="unsupported_format",
                    detail="Unsupported image format. Allowed: JPEG, PNG, BMP, TIFF, WebP",
                    request_id=request_id,
                ).model_dump(),
            )
        else:
            record_request("/ocr", lang, "error", duration)
            return JSONResponse(
                status_code=422,
                content=ErrorResponse(
                    error="unreadable_image",
                    detail=f"Cannot process image: {error_msg}",
                    request_id=request_id,
                ).model_dump(),
            )
    except Exception as e:
        duration = time.time() - start_time
        record_request("/ocr", lang, "error", duration)
        logger.error(f"OCR request failed: {e}")
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="internal_error",
                detail="Internal server error during OCR processing",
                request_id=request_id,
            ).model_dump(),
        )


@router.post(
    "/json",
    response_model=OCRResponse,
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        422: {"model": ErrorResponse, "description": "Unprocessable Entity"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)
async def ocr_single_json(
    request: OCRRequest,
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
    x_min_confidence: Optional[float] = Header(None, alias="X-Min-Confidence"),
    x_layout_analysis: Optional[bool] = Header(None, alias="X-Layout-Analysis"),
):
    """
    Process a single base64-encoded image with OCR.

    Alternative endpoint accepting JSON body with base64 image data.
    """
    settings = get_settings()
    request_id = str(uuid.uuid4())
    start_time = time.time()
    lang = x_lang or request.lang or settings.MODEL_LANG
    min_confidence = x_min_confidence or request.min_confidence

    try:
        # Decode base64 image
        image_bytes = base64_to_bytes(request.image)

        # Validate file size
        if len(image_bytes) == 0:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="image_empty",
                    detail="Image data is empty",
                    request_id=request_id,
                ).model_dump(),
            )

        if len(image_bytes) > settings.max_image_size_bytes:
            return JSONResponse(
                status_code=413,
                content=ErrorResponse(
                    error="file_too_large",
                    detail=f"Image size exceeds maximum {settings.MAX_IMAGE_SIZE_MB}MB",
                    request_id=request_id,
                ).model_dump(),
            )

        # Process image
        result = process_single_image(
            image_bytes,
            lang=lang,
            min_confidence=min_confidence,
            include_polygon=request.include_polygon,
        )

        # Check for error
        if "error" in result:
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error=result["error"],
                    detail=result.get("message", "OCR processing failed"),
                    request_id=request_id,
                ).model_dump(),
            )

        # Build response
        response = build_ocr_response(result, request_id)

        # Record metrics
        duration = time.time() - start_time
        record_request("/ocr/json", lang, "success", duration)

        return response

    except ValueError as e:
        duration = time.time() - start_time
        error_msg = str(e)

        if "image_empty" in error_msg:
            record_request("/ocr/json", lang, "error", duration)
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="image_empty",
                    detail="Image data is empty",
                    request_id=request_id,
                ).model_dump(),
            )
        elif "Invalid base64" in error_msg:
            record_request("/ocr/json", lang, "error", duration)
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error="invalid_base64",
                    detail="Invalid base64 encoded image data",
                    request_id=request_id,
                ).model_dump(),
            )
        else:
            record_request("/ocr/json", lang, "error", duration)
            return JSONResponse(
                status_code=422,
                content=ErrorResponse(
                    error="unreadable_image",
                    detail=f"Cannot process image: {error_msg}",
                    request_id=request_id,
                ).model_dump(),
            )
    except Exception as e:
        duration = time.time() - start_time
        record_request("/ocr/json", lang, "error", duration)
        logger.error(f"OCR JSON request failed: {e}")
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="internal_error",
                detail="Internal server error during OCR processing",
                request_id=request_id,
            ).model_dump(),
        )


@router.post(
    "/batch",
    response_model=BatchOCRResponse,
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        413: {"model": ErrorResponse, "description": "Payload Too Large"},
        415: {"model": ErrorResponse, "description": "Unsupported Media Type"},
        422: {"model": ErrorResponse, "description": "Unprocessable Entity"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)
async def ocr_batch(
    files: List[UploadFile] = File(..., description="Image files to process"),
    lang_form: Optional[str] = Form(None, alias="lang"),
    min_confidence_form: Optional[float] = Form(None, alias="min_confidence"),
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
    x_min_confidence: Optional[float] = Header(None, alias="X-Min-Confidence"),
):
    """
    Process multiple images with OCR in batch.

    Accepts multiple image file uploads.
    """
    settings = get_settings()
    request_id = str(uuid.uuid4())
    start_time = time.time()
    lang = x_lang or lang_form or settings.MODEL_LANG
    min_confidence = x_min_confidence if x_min_confidence is not None else (min_confidence_form if min_confidence_form is not None else settings.MIN_CONFIDENCE)

    # Check batch size limit
    if len(files) > settings.MAX_BATCH_SIZE:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="batch_too_large",
                detail=f"Batch size {len(files)} exceeds maximum {settings.MAX_BATCH_SIZE}",
                request_id=request_id,
            ).model_dump(),
        )

    results = []
    success_count = 0
    error_count = 0

    for idx, file in enumerate(files):
        try:
            filename = file.filename or f"image_{idx}"

            # Read file content
            image_bytes = await file.read()

            # Validate
            if len(image_bytes) == 0:
                results.append(
                    ImageOCRResult(
                        filename=filename,
                        status="error",
                        data=None,
                        error="Image file is empty",
                    )
                )
                error_count += 1
                continue

            if len(image_bytes) > settings.max_image_size_bytes:
                results.append(
                    ImageOCRResult(
                        filename=filename,
                        status="error",
                        data=None,
                        error=f"Image exceeds maximum size of {settings.MAX_IMAGE_SIZE_MB}MB",
                    )
                )
                error_count += 1
                continue

            # Process image
            ocr_result = process_single_image(
                image_bytes,
                lang=lang,
                min_confidence=min_confidence,
                include_polygon=settings.INCLUDE_POLYGON,
            )

            if "error" in ocr_result:
                results.append(
                    ImageOCRResult(
                        filename=filename,
                        status="error",
                        data=None,
                        error=ocr_result.get("message", "OCR failed"),
                    )
                )
                error_count += 1
            else:
                response = build_ocr_response(ocr_result, request_id)
                results.append(
                    ImageOCRResult(
                        filename=filename,
                        status="success",
                        data=response.model_dump(),
                        error=None,
                    )
                )
                success_count += 1

        except ValueError as e:
            error_msg = str(e)
            results.append(
                ImageOCRResult(
                    filename=file.filename or f"image_{idx}",
                    status="error",
                    data=None,
                    error=f"Image processing error: {error_msg}",
                )
            )
            error_count += 1
        except Exception as e:
            results.append(
                ImageOCRResult(
                    filename=file.filename or f"image_{idx}",
                    status="error",
                    data=None,
                    error=f"Unexpected error: {str(e)}",
                )
            )
            error_count += 1

    # Record metrics
    duration = time.time() - start_time
    status = "success" if error_count == 0 else "partial" if success_count > 0 else "error"
    record_request("/ocr/batch", lang, status, duration, batch_size=len(files), job_type="sync")

    return BatchOCRResponse(
        request_id=request_id,
        status=status,
        results=results,
    )


@router.post(
    "/batch/json",
    response_model=BatchOCRResponse,
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        413: {"model": ErrorResponse, "description": "Payload Too Large"},
        422: {"model": ErrorResponse, "description": "Unprocessable Entity"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)
async def ocr_batch_json(
    request: BatchOCRRequest,
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
    x_min_confidence: Optional[float] = Header(None, alias="X-Min-Confidence"),
):
    """
    Process multiple base64-encoded images with OCR in batch.

    Alternative endpoint accepting JSON body with array of base64 images.
    """
    settings = get_settings()
    request_id = str(uuid.uuid4())
    start_time = time.time()
    lang = x_lang or request.lang or settings.MODEL_LANG
    min_confidence = x_min_confidence or request.min_confidence

    # Check batch size limit
    if len(request.images) > settings.MAX_BATCH_SIZE:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="batch_too_large",
                detail=f"Batch size {len(request.images)} exceeds maximum {settings.MAX_BATCH_SIZE}",
                request_id=request_id,
            ).model_dump(),
        )

    results = []
    success_count = 0
    error_count = 0

    for idx, image_data in enumerate(request.images):
        try:
            # Decode base64 image
            image_bytes = base64_to_bytes(image_data)

            # Validate
            if len(image_bytes) == 0:
                results.append(
                    ImageOCRResult(
                        filename=f"image_{idx}",
                        status="error",
                        data=None,
                        error="Image data is empty",
                    )
                )
                error_count += 1
                continue

            if len(image_bytes) > settings.max_image_size_bytes:
                results.append(
                    ImageOCRResult(
                        filename=f"image_{idx}",
                        status="error",
                        data=None,
                        error=f"Image exceeds maximum size of {settings.MAX_IMAGE_SIZE_MB}MB",
                    )
                )
                error_count += 1
                continue

            # Process image
            ocr_result = process_single_image(
                image_bytes,
                lang=lang,
                min_confidence=min_confidence,
                include_polygon=settings.INCLUDE_POLYGON,
            )

            if "error" in ocr_result:
                results.append(
                    ImageOCRResult(
                        filename=f"image_{idx}",
                        status="error",
                        data=None,
                        error=ocr_result.get("message", "OCR failed"),
                    )
                )
                error_count += 1
            else:
                response = build_ocr_response(ocr_result, request_id)
                results.append(
                    ImageOCRResult(
                        filename=f"image_{idx}",
                        status="success",
                        data=response.model_dump(),
                        error=None,
                    )
                )
                success_count += 1

        except ValueError as e:
            error_msg = str(e)
            results.append(
                ImageOCRResult(
                    filename=f"image_{idx}",
                    status="error",
                    data=None,
                    error=f"Image processing error: {error_msg}",
                )
            )
            error_count += 1
        except Exception as e:
            results.append(
                ImageOCRResult(
                    filename=f"image_{idx}",
                    status="error",
                    data=None,
                    error=f"Unexpected error: {str(e)}",
                )
            )
            error_count += 1

    # Record metrics
    duration = time.time() - start_time
    status = "success" if error_count == 0 else "partial" if success_count > 0 else "error"
    record_request("/ocr/batch/json", lang, status, duration, batch_size=len(request.images), job_type="sync")

    return BatchOCRResponse(
        request_id=request_id,
        status=status,
        results=results,
    )
