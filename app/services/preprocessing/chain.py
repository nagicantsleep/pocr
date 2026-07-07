"""Image preprocessing chain for OCR: deskew, denoise, binarize."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PreprocessConfig:
    """Configuration for preprocessing steps."""

    deskew: bool = True
    denoise: bool = True
    binarize: bool = True
    max_skew_angle: float = 15.0
    denoise_strength: int = 10


@dataclass
class PreprocessResult:
    """Result of image preprocessing."""

    image_bytes: bytes
    original_size: tuple[int, int]
    processed_size: tuple[int, int]
    skew_angle: float
    applied_steps: list[str] = field(default_factory=list)


class PreprocessingChain:
    """Image preprocessing pipeline for OCR."""

    def process(
        self,
        image_bytes: bytes,
        config: PreprocessConfig | None = None,
    ) -> PreprocessResult:
        """Run the full preprocessing chain on an image.

        Steps:
            1. Decode image (bytes -> numpy array)
            2. Convert to grayscale
            3. Detect and correct skew (deskew)
            4. Denoise (bilateral filter)
            5. Binarize (adaptive threshold)
            6. Encode back to PNG bytes
        """
        if not image_bytes:
            raise ValueError("image_bytes must not be empty")

        config = config or PreprocessConfig()
        applied_steps: list[str] = []

        # 1. Decode
        img = cv2.imdecode(
            np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR
        )
        if img is None:
            raise ValueError("Failed to decode image bytes")
        applied_steps.append("decode")

        original_h, original_w = img.shape[:2]
        original_size = (original_w, original_h)

        # 2. Grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        applied_steps.append("grayscale")

        # 3. Deskew
        skew_angle = 0.0
        if config.deskew:
            skew_angle = self._detect_skew(gray)
            if abs(skew_angle) > 0.1 and abs(skew_angle) <= config.max_skew_angle:
                gray = self._rotate_image(gray, -skew_angle)
                applied_steps.append("deskew")
                logger.info("Deskewed by %.2f degrees", skew_angle)

        # 4. Denoise
        if config.denoise:
            gray = cv2.bilateralFilter(
                gray,
                d=config.denoise_strength,
                sigmaColor=75,
                sigmaSpace=75,
            )
            applied_steps.append("denoise")

        # 5. Binarize
        if config.binarize:
            gray = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                11,
                2,
            )
            applied_steps.append("binarize")

        # 6. Encode to PNG
        _, encoded = cv2.imencode(".png", gray)
        result_bytes = encoded.tobytes()
        applied_steps.append("encode")

        processed_h, processed_w = gray.shape[:2]
        processed_size = (processed_w, processed_h)

        return PreprocessResult(
            image_bytes=result_bytes,
            original_size=original_size,
            processed_size=processed_size,
            skew_angle=skew_angle,
            applied_steps=applied_steps,
        )

    @staticmethod
    def _detect_skew(gray: np.ndarray) -> float:
        """Detect skew angle using Hough line transform."""
        edges = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        lines = cv2.HoughLinesP(
            edges, rho=1, theta=np.pi / 180, threshold=100,
            minLineLength=100, maxLineGap=10,
        )
        if lines is None:
            return 0.0

        angles = []
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
            # Only consider near-horizontal lines
            if abs(angle) < 45:
                angles.append(angle)

        if not angles:
            return 0.0

        return float(np.median(angles))

    @staticmethod
    def _rotate_image(gray: np.ndarray, angle: float) -> np.ndarray:
        """Rotate image by the given angle, expanding canvas to avoid cropping."""
        h, w = gray.shape[:2]
        center = (w / 2, h / 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

        # Compute new bounding dimensions
        cos_a = abs(matrix[0, 0])
        sin_a = abs(matrix[0, 1])
        new_w = int(h * sin_a + w * cos_a)
        new_h = int(h * cos_a + w * sin_a)

        # Adjust the rotation matrix for the new canvas
        matrix[0, 2] += (new_w - w) / 2
        matrix[1, 2] += (new_h - h) / 2

        return cv2.warpAffine(
            gray, matrix, (new_w, new_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
