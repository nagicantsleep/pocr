"""PaddleOCR engine wrapper with lazy initialization."""

import io
import logging
import time
from typing import Any, Dict, List, Optional

from PIL import Image

from app.config import get_settings
from app.utils.image_utils import base64_to_bytes
from app.utils.metrics import record_inference

logger = logging.getLogger(__name__)

# Global engine instance (lazy initialized)
_ocr_engine: Optional[Any] = None
_engine_initialized: bool = False


def get_ocr_engine() -> Any:
    """
    Get or create the PaddleOCR engine instance.
    Lazy initialization - engine is created on first request.

    Returns:
        PaddleOCR engine instance
    """
    global _ocr_engine, _engine_initialized

    if not _engine_initialized:
        settings = get_settings()

        logger.info(f"Initializing PaddleOCR with device={settings.PADDLE_DEVICE}")

        # Import PaddleOCR here for lazy loading
        from paddleocr import PaddleOCR

        # Build OCR parameters from settings
        ocr_params = {
            "lang": settings.MODEL_LANG,
            "use_angle_cls": settings.USE_ANGLE_CLS,
            "det_db_thresh": settings.DET_DB_THRESH,
            "det_db_box_thresh": settings.DET_DB_BOX_THRESH,
            "rec_batch_num": settings.REC_BATCH_NUM,
        }

        # Set device
        device = settings.paddle_device
        if settings.paddle_device_id is not None:
            device = f"gpu:{settings.paddle_device_id}"
        ocr_params["use_gpu"] = device.startswith("gpu")

        # Model download URL if provided
        if settings.MODEL_DOWNLOAD_URL:
            ocr_params["model_storage_dir"] = settings.MODEL_DOWNLOAD_URL

        logger.info(f"PaddleOCR parameters: {ocr_params}")

        # Initialize engine
        _ocr_engine = PaddleOCR(**ocr_params)
        _engine_initialized = True

        logger.info("PaddleOCR engine initialized successfully")

    return _ocr_engine


def is_engine_ready() -> bool:
    """Check if OCR engine is initialized and ready."""
    return _engine_initialized and _ocr_engine is not None


def run_ocr(
    image_bytes: bytes,
    lang: str = "auto",
    min_confidence: float = 0.0,
    include_polygon: bool = True,
) -> Dict[str, Any]:
    """
    Run OCR on image bytes.

    Args:
        image_bytes: Raw image bytes
        lang: Language code for OCR
        min_confidence: Minimum confidence threshold
        include_polygon: Whether to include polygon points

    Returns:
        Normalized OCR results dictionary
    """
    settings = get_settings()
    start_time = time.time()

    try:
        # Get engine (lazy initialization)
        engine = get_ocr_engine()

        # Load image for dimension info
        image = Image.open(io.BytesIO(image_bytes))
        original_width, original_height = image.size
        image.close()

        # Run OCR
        results = engine.ocr(image_bytes, cls=settings.USE_ANGLE_CLS)

        # Calculate inference time
        inference_time_ms = int((time.time() - start_time) * 1000)

        # Record metrics
        record_inference(
            model=f"ch_PP-OCRv4_{lang}",
            device=settings.PADDLE_DEVICE,
            duration=time.time() - start_time,
        )

        # Normalize results
        normalized = normalize_ocr_results(
            raw_results=results,
            original_width=original_width,
            original_height=original_height,
            lang=lang,
            min_confidence=min_confidence,
            include_polygon=include_polygon,
            inference_time_ms=inference_time_ms,
        )

        return normalized

    except Exception as e:
        logger.error(f"OCR processing failed: {e}")
        return create_error_response(
            error_code="ocr_failed",
            error_message=str(e),
            lang=lang,
        )


def normalize_ocr_results(
    raw_results: Any,
    original_width: int,
    original_height: int,
    lang: str,
    min_confidence: float,
    include_polygon: bool,
    inference_time_ms: int,
) -> Dict[str, Any]:
    """
    Normalize PaddleOCR output to standard format.

    PaddleOCR returns:
    [[text, confidence, [polygon_points]], ...]

    Args:
        raw_results: Raw PaddleOCR output
        original_width: Original image width
        original_height: Original image height
        lang: Language code used
        min_confidence: Minimum confidence threshold
        include_polygon: Whether to include polygon points
        inference_time_ms: Inference time in milliseconds

    Returns:
        Normalized results dictionary
    """
    results_list = []
    total_characters = 0
    confidence_sum = 0.0
    confidence_count = 0

    # Handle None or empty results
    if raw_results is None or not raw_results:
        return {
            "results": [],
            "meta": {
                "engine": "paddleocr",
                "engine_version": "3.5.0",
                "model": f"ch_PP-OCRv4_{lang}",
                "lang": lang,
                "inference_time_ms": inference_time_ms,
                "image_width": original_width,
                "image_height": original_height,
                "was_resized": False,
            },
            "summary": {
                "total_lines": 0,
                "total_characters": 0,
                "avg_confidence": 0.0,
            },
        }

    # Process each detected region
    for line_result in raw_results:
        if not line_result:
            continue

        for item in line_result:
            if not item or len(item) < 2:
                continue

            # Extract data from PaddleOCR format
            # Format: [[polygon], (text, confidence)]
            if isinstance(item, list) and len(item) >= 2:
                polygon = item[0]
                text_info = item[1]
            elif isinstance(item, tuple) and len(item) >= 2:
                polygon = item[0]
                text_info = item[1]
            else:
                continue

            # Extract text and confidence
            if isinstance(text_info, tuple):
                text = text_info[0]
                confidence = float(text_info[1])
            else:
                text = str(text_info)
                confidence = 1.0

            # Filter by confidence threshold
            if confidence < min_confidence:
                continue

            # Calculate bounding box from polygon
            if polygon and len(polygon) >= 4:
                xs = [p[0] for p in polygon]
                ys = [p[1] for p in polygon]
                bbox = {
                    "top_left": [min(xs), min(ys)],
                    "bottom_right": [max(xs), max(ys)],
                }

                # Normalized bbox (0-1 range)
                bbox_normalized = {
                    "top_left": [
                        min(xs) / original_width,
                        min(ys) / original_height,
                    ],
                    "bottom_right": [
                        max(xs) / original_width,
                        max(ys) / original_height,
                    ],
                }

                # Format polygon
                polygon_points = polygon if include_polygon else []
            else:
                bbox = {"top_left": [0, 0], "bottom_right": [0, 0]}
                bbox_normalized = {
                    "top_left": [0.0, 0.0],
                    "bottom_right": [0.0, 0.0],
                }
                polygon_points = []

            # Add result
            result_item = {
                "text": text,
                "confidence": confidence,
                "bbox": bbox,
                "bbox_normalized": bbox_normalized,
                "type": "text",
            }

            if include_polygon:
                result_item["polygon"] = polygon_points

            results_list.append(result_item)

            # Update statistics
            total_characters += len(text)
            confidence_sum += confidence
            confidence_count += 1

    # Calculate summary
    avg_confidence = (
        confidence_sum / confidence_count if confidence_count > 0 else 0.0
    )

    return {
        "results": results_list,
        "meta": {
            "engine": "paddleocr",
            "engine_version": "2.7.3",
            "model": f"ch_PP-OCRv4_{lang}",
            "lang": lang,
            "inference_time_ms": inference_time_ms,
            "image_width": original_width,
            "image_height": original_height,
            "was_resized": False,
        },
        "summary": {
            "total_lines": len(results_list),
            "total_characters": total_characters,
            "avg_confidence": avg_confidence,
        },
    }


def create_error_response(
    error_code: str,
    error_message: str,
    lang: str = "en",
) -> Dict[str, Any]:
    """
    Create a normalized error response.

    Args:
        error_code: Error code identifier
        error_message: Human-readable error message
        lang: Language code used

    Returns:
        Error response dictionary
    """
    return {
        "error": error_code,
        "message": error_message,
        "results": [],
        "meta": {
            "engine": "paddleocr",
            "engine_version": "2.7.3",
            "model": f"ch_PP-OCRv4_{lang}",
            "lang": lang,
            "inference_time_ms": 0,
            "image_width": 0,
            "image_height": 0,
            "was_resized": False,
        },
        "summary": {
            "total_lines": 0,
            "total_characters": 0,
            "avg_confidence": 0.0,
        },
    }


def run_ocr_with_fallback(
    image_bytes: bytes,
    lang: str = "auto",
    min_confidence: float = 0.0,
) -> Dict[str, Any]:
    """
    Run OCR with GPU to CPU fallback on OOM.

    Args:
        image_bytes: Raw image bytes
        lang: Language code for OCR
        min_confidence: Minimum confidence threshold

    Returns:
        Normalized OCR results dictionary
    """
    settings = get_settings()

    try:
        return run_ocr(image_bytes, lang, min_confidence)
    except Exception as e:
        error_str = str(e).lower()

        # Check for GPU OOM
        if "oom" in error_str or "out of memory" in error_str:
            logger.warning(
                f"GPU OOM detected, falling back to CPU. Error: {e}"
            )

            # Use a local variable instead of mutating the singleton
            # Pass a modified config dict directly to PaddleOCR
            cpu_settings = settings  # keep reference but don't mutate

            try:
                global _ocr_engine
                # Create CPU-specific engine params
                original_engine = _ocr_engine
                if _engine_initialized:
                    from paddleocr import PaddleOCR
                    ocr_params = {
                        "lang": cpu_settings.MODEL_LANG,
                        "use_angle_cls": cpu_settings.USE_ANGLE_CLS,
                        "det_db_thresh": cpu_settings.DET_DB_THRESH,
                        "det_db_box_thresh": cpu_settings.DET_DB_BOX_THRESH,
                        "rec_batch_num": cpu_settings.REC_BATCH_NUM,
                        "use_gpu": False,
                    }
                    original_engine = _ocr_engine
                    _ocr_engine = PaddleOCR(**ocr_params)
                    result = run_ocr(image_bytes, lang, min_confidence)
                    _ocr_engine = original_engine
                    return result
                else:
                    return run_ocr(image_bytes, lang, min_confidence)
            except Exception:
                raise
        else:
            raise
