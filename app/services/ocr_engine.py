"""PaddleOCR engine wrapper with lazy initialization."""

import io
import logging
import time
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image

from app.config import get_settings
from app.utils.image_utils import base64_to_bytes
from app.utils.metrics import record_inference

logger = logging.getLogger(__name__)

# Global engines by language (lazy initialized)
_ocr_engines: Dict[str, Any] = {}


def get_ocr_engine(lang: str = "en") -> Any:
    """
    Get or create the PaddleOCR engine instance.
    Lazy initialization - engine is created on first request.

    Returns:
        PaddleOCR engine instance
    """
    settings = get_settings()
    engine_lang = (lang or settings.MODEL_LANG or "en").strip().lower()
    if engine_lang == "auto":
        engine_lang = settings.MODEL_LANG

    if engine_lang not in _ocr_engines:
        logger.info(f"Initializing PaddleOCR with device={settings.PADDLE_DEVICE}, lang={engine_lang}")

        # Import PaddleOCR here for lazy loading
        from paddleocr import PaddleOCR

        # PaddleOCR 3.x: keep init args minimal and compatible
        ocr_params = {
            "lang": engine_lang,
        }

        logger.info(f"PaddleOCR parameters: {ocr_params}")

        # Initialize engine for this language
        _ocr_engines[engine_lang] = PaddleOCR(**ocr_params)

        logger.info("PaddleOCR engine initialized successfully")

    return _ocr_engines[engine_lang]


def is_engine_ready() -> bool:
    """Check if at least one OCR engine is initialized and ready."""
    return len(_ocr_engines) > 0


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
        # Get language-specific engine (lazy initialization)
        engine = get_ocr_engine(lang=lang)

        # Load image for dimension info
        image = Image.open(io.BytesIO(image_bytes))
        original_width, original_height = image.size
        image.close()

        # Run OCR
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image_array = np.array(image)
        results = engine.ocr(image_array)
        image.close()

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
                "engine_version": get_settings().PADDLEOCR_VERSION,
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

    def normalize_polygon(polygon: Any) -> List[List[float]]:
        if polygon is None:
            return []
        if isinstance(polygon, np.ndarray):
            polygon = polygon.tolist()
        points = []
        for point in polygon:
            if isinstance(point, np.ndarray):
                point = point.tolist()
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            points.append([float(point[0]), float(point[1])])
        return points

    def build_geometry(polygon: Any) -> tuple[dict, dict, list]:
        points = normalize_polygon(polygon)
        if len(points) < 4:
            return (
                {"top_left": [0, 0], "bottom_right": [0, 0]},
                {"top_left": [0.0, 0.0], "bottom_right": [0.0, 0.0]},
                [],
            )

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        bbox = {"top_left": [min(xs), min(ys)], "bottom_right": [max(xs), max(ys)]}
        bbox_normalized = {
            "top_left": [min(xs) / original_width, min(ys) / original_height],
            "bottom_right": [max(xs) / original_width, max(ys) / original_height],
        }
        return bbox, bbox_normalized, points

    for line_result in raw_results:
        if not line_result:
            continue

        # PaddleOCR 3.x may return dict entries with batched arrays
        if isinstance(line_result, dict):
            texts = line_result.get("rec_texts") or []
            scores = line_result.get("rec_scores") or []
            polys = line_result.get("rec_polys") or line_result.get("dt_polys") or []
            for i, text in enumerate(texts):
                confidence = float(scores[i]) if i < len(scores) else 1.0
                if confidence < min_confidence:
                    continue
                polygon = polys[i] if i < len(polys) else []
                bbox, bbox_normalized, polygon_points = build_geometry(polygon)

                result_item = {
                    "text": str(text),
                    "confidence": confidence,
                    "bbox": bbox,
                    "bbox_normalized": bbox_normalized,
                    "type": "text",
                }
                if include_polygon:
                    result_item["polygon"] = polygon_points

                results_list.append(result_item)
                total_characters += len(str(text))
                confidence_sum += confidence
                confidence_count += 1
            continue

        # Legacy PaddleOCR item shape: [polygon, (text, confidence)]
        items = line_result if isinstance(line_result, list) else [line_result]
        for item in items:
            if not item or len(item) < 2:
                continue

            if not isinstance(item, (list, tuple)):
                continue

            polygon = item[0]
            text_info = item[1]

            # Extract text and confidence
            if isinstance(text_info, tuple):
                text = text_info[0]
                confidence = float(text_info[1])
            elif isinstance(text_info, list) and len(text_info) >= 2:
                text = text_info[0]
                confidence = float(text_info[1])
            else:
                text = str(text_info)
                confidence = 1.0

            # Filter by confidence threshold
            if confidence < min_confidence:
                continue

            # Calculate bounding box from polygon
            bbox, bbox_normalized, polygon_points = build_geometry(polygon)

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
            "engine_version": get_settings().PADDLEOCR_VERSION,
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
            "engine_version": get_settings().PADDLEOCR_VERSION,
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

    Note: run_ocr catches all exceptions internally and returns error dicts,
    so the OOM fallback path below is rarely reached in practice.

    Args:
        image_bytes: Raw image bytes
        lang: Language code for OCR
        min_confidence: Minimum confidence threshold

    Returns:
        Normalized OCR results dictionary
    """
    try:
        return run_ocr(image_bytes, lang, min_confidence)
    except Exception as e:
        error_str = str(e).lower()

        # Check for GPU OOM
        if "oom" in error_str or "out of memory" in error_str:
            logger.warning(
                f"GPU OOM detected, falling back to CPU. Error: {e}"
            )

            try:
                engine_lang = (lang or "en").strip().lower()
                if engine_lang in _ocr_engines:
                    from paddleocr import PaddleOCR
                    original_engine = _ocr_engines[engine_lang]
                    ocr_params = {"lang": engine_lang}
                    _ocr_engines[engine_lang] = PaddleOCR(**ocr_params)
                    result = run_ocr(image_bytes, lang, min_confidence)
                    _ocr_engines[engine_lang] = original_engine
                    return result
                else:
                    return run_ocr(image_bytes, lang, min_confidence)
            except Exception:
                raise
        else:
            raise
