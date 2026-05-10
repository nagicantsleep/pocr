"""Jobs router for async OCR processing."""

import asyncio
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header
from fastapi.responses import JSONResponse

from app.auth import verify_api_key

from app.config import get_settings
from app.schemas.requests import JobCreateRequest
from app.schemas.responses import (
    ErrorResponse,
    ImageOCRResult,
    JobCreateResponse,
    JobProgress,
    JobResponse,
)
from app.services.job_store import JobStatus, get_job_store
from app.utils.image_utils import base64_to_bytes, validate_and_preprocess
from app.utils.metrics import decrement_queue_depth, increment_queue_depth, record_request
from app.services.ocr_engine import run_ocr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ocr/jobs", tags=["Jobs"], dependencies=[Depends(verify_api_key)])

# Thread pool for background OCR processing
settings = get_settings()
_executor = ThreadPoolExecutor(max_workers=settings.ASYNC_WORKERS or 4)


def process_image_for_job(
    image_bytes: bytes,
    lang: str,
    min_confidence: float,
    include_polygon: bool,
) -> dict:
    """
    Process a single image for job.

    Args:
        image_bytes: Raw image bytes
        lang: Language code
        min_confidence: Minimum confidence threshold
        include_polygon: Include polygon points

    Returns:
        OCR result dictionary or error dict
    """
    try:
        # Preprocess and validate
        processed_bytes, was_resized = validate_and_preprocess(image_bytes)

        # Run OCR
        result = run_ocr(
            processed_bytes,
            lang=lang,
            min_confidence=min_confidence,
            include_polygon=include_polygon,
        )

        if "error" in result:
            return {"status": "error", "error": result.get("message", "OCR failed")}

        return {
            "status": "success",
            "data": result,
            "was_resized": was_resized,
        }

    except ValueError as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        logger.error(f"Job image processing failed: {e}")
        return {"status": "error", "error": f"Processing failed: {str(e)}"}


async def process_job_async(job_id: str, images: list, lang: str, min_confidence: float, layout_analysis: bool):
    """
    Process a job asynchronously.

    Args:
        job_id: Job identifier
        images: List of base64-encoded images
        lang: Language code
        min_confidence: Minimum confidence threshold
        layout_analysis: Enable layout analysis
    """
    settings = get_settings()
    job_store = get_job_store()
    start_time = time.time()

    logger.info(f"Starting async job {job_id} processing")

    # Update job status to running
    job_store.update_job(job_id, status=JobStatus.RUNNING)

    results = []
    success_count = 0
    error_count = 0
    processed = 0

    try:
        for idx, image_data in enumerate(images):
            # Check if job was cancelled
            job = job_store.get_job(job_id)
            if job and job.get("status") == JobStatus.CANCELLED:
                logger.info(f"Job {job_id} was cancelled")
                decrement_queue_depth()
                return

            try:
                # Decode base64 image
                image_bytes = base64_to_bytes(image_data)

                # Run OCR in thread pool
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    _executor,
                    process_image_for_job,
                    image_bytes,
                    lang,
                    min_confidence,
                    settings.INCLUDE_POLYGON,
                )

                if result.get("status") == "success":
                    results.append(
                        ImageOCRResult(
                            filename=f"image_{idx}",
                            status="success",
                            data=result.get("data"),
                            error=None,
                        )
                    )
                    success_count += 1
                else:
                    results.append(
                        ImageOCRResult(
                            filename=f"image_{idx}",
                            status="error",
                            data=None,
                            error=result.get("error", "Unknown error"),
                        )
                    )
                    error_count += 1

                processed += 1

                # Update progress
                job_store.update_job(
                    job_id,
                    results=results.copy(),
                    progress={"processed": processed, "total": len(images)},
                )

            except Exception as e:
                logger.error(f"Failed to process image {idx} in job {job_id}: {e}")
                results.append(
                    ImageOCRResult(
                        filename=f"image_{idx}",
                        status="error",
                        data=None,
                        error=f"Processing error: {str(e)}",
                    )
                )
                error_count += 1
                processed += 1

        # Mark job as completed
        status = JobStatus.COMPLETED if error_count == 0 else JobStatus.FAILED
        job_store.update_job(
            job_id,
            status=status,
            results=results,
            progress={"processed": processed, "total": len(images)},
        )

        duration = time.time() - start_time
        job_status_str = "success" if error_count == 0 else "partial" if success_count > 0 else "error"
        record_request("/ocr/jobs", lang, job_status_str, duration, batch_size=len(images), job_type="async")

        logger.info(f"Job {job_id} completed with status {status}")
        decrement_queue_depth()

    except Exception as e:
        logger.error(f"Job {job_id} failed with error: {e}")
        job_store.update_job(
            job_id,
            status=JobStatus.FAILED,
            error=str(e),
        )
        decrement_queue_depth()


@router.post(
    "",
    response_model=JobCreateResponse,
    status_code=202,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)
async def create_job(
    request: JobCreateRequest,
    background_tasks: BackgroundTasks,
    x_lang: Optional[str] = Header(None, alias="X-Lang"),
):
    """
    Create an async OCR job for batch processing.

    Returns immediately with a job ID for status polling.
    Processing happens in the background.
    """
    settings = get_settings()
    job_store = get_job_store()
    lang = x_lang or request.lang or settings.MODEL_LANG

    # Check batch size limit
    if len(request.images) > settings.MAX_BATCH_SIZE:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="batch_too_large",
                detail=f"Batch size {len(request.images)} exceeds maximum {settings.MAX_BATCH_SIZE}",
                request_id=None,
            ).model_dump(),
        )

    # Create job
    job_response = job_store.create_job(
        images=request.images,
        lang=lang,
        min_confidence=request.min_confidence,
        layout_analysis=request.layout_analysis,
    )

    # Increment queue depth
    increment_queue_depth()

    # Schedule background processing
    background_tasks.add_task(
        process_job_async,
        job_response["job_id"],
        request.images,
        lang,
        request.min_confidence,
        request.layout_analysis,
    )

    return JobCreateResponse(**job_response)


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Job Not Found"},
        410: {"model": ErrorResponse, "description": "Job Expired"},
    },
)
async def get_job_status(job_id: str):
    """
    Get the status and results of an async OCR job.

    Returns current job status, progress, and results if completed.
    """
    job_store = get_job_store()
    job = job_store.get_job(job_id)

    if job is None:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error="job_not_found",
                detail=f"Job {job_id} not found",
                request_id=job_id,
            ).model_dump(),
        )

    # Convert job results to ImageOCRResult objects
    results = None
    if "results" in job and job["results"]:
        results = [
            ImageOCRResult(**r) if isinstance(r, dict) else r
            for r in job["results"]
        ]

    # Build response
    response = JobResponse(
        job_id=job["job_id"],
        status=job["status"],
        created_at=job.get("created_at"),
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        progress=JobProgress(**job["progress"]) if "progress" in job else None,
        results=results,
        error=job.get("error"),
    )

    # Set appropriate status code
    if job["status"] == JobStatus.COMPLETED:
        return response
    elif job["status"] == JobStatus.FAILED:
        return JSONResponse(
            status_code=500,
            content=response.model_dump(),
        )
    else:
        return response


@router.delete(
    "/{job_id}",
    response_model=JobResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Job Not Found"},
        400: {"model": ErrorResponse, "description": "Cannot Cancel Job"},
    },
)
async def cancel_job(job_id: str):
    """
    Cancel a pending or running OCR job.

    Only jobs with status 'queued' or 'running' can be cancelled.
    """
    job_store = get_job_store()
    job = job_store.get_job(job_id)

    if job is None:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error="job_not_found",
                detail=f"Job {job_id} not found",
                request_id=job_id,
            ).model_dump(),
        )

    # Check if job can be cancelled
    if job["status"] not in (JobStatus.QUEUED, JobStatus.RUNNING):
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="cannot_cancel",
                detail=f"Job with status '{job['status']}' cannot be cancelled",
                request_id=job_id,
            ).model_dump(),
        )

    # Cancel the job
    success = job_store.cancel_job(job_id)
    if not success:
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="cancel_failed",
                detail="Failed to cancel job",
                request_id=job_id,
            ).model_dump(),
        )

    # Decrement queue depth
    decrement_queue_depth()

    return JobResponse(
        job_id=job_id,
        status=JobStatus.CANCELLED,
        created_at=job.get("created_at"),
    )
