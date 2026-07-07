from __future__ import annotations

import io
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass
class QualityScore:
    """Quality assessment of an image."""

    overall: float  # 0.0 - 1.0 composite score
    sharpness: float  # Laplacian variance normalized
    contrast: float  # Histogram spread
    brightness: float  # Mean brightness (0-1, penalized if extreme)
    noise_level: float  # Estimated noise level (lower = cleaner)
    is_acceptable: bool  # True if above threshold
    rejection_reason: str | None  # Why it was rejected, if applicable


# Laplacian kernel for edge detection
_LAPLACIAN_KERNEL = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)


def _convolve2d_manual(image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Manual 2D convolution for a 3x3 kernel."""
    kh, kw = kernel.shape
    ph, pw = kh // 2, kw // 2
    padded = np.pad(image, ((ph, ph), (pw, pw)), mode="reflect")
    h, w = image.shape
    result = np.zeros_like(image, dtype=np.float64)
    for i in range(kh):
        for j in range(kw):
            result += kernel[i, j] * padded[i : i + h, j : j + w]
    return result


class QualityGate:
    """Evaluates image quality for OCR processing."""

    def assess(self, image_bytes: bytes, threshold: float = 0.40) -> QualityScore:
        """Assess image quality.

        Metrics:
        - Sharpness: Laplacian variance (higher = sharper). Normalize to 0-1.
        - Contrast: Standard deviation of pixel intensities. Normalize to 0-1.
        - Brightness: Mean pixel value. Penalize too dark or too bright.
        - Noise: Estimated via median absolute deviation of Laplacian.
        - Overall: Weighted combination of above.
        """
        image = Image.open(io.BytesIO(image_bytes))
        gray = image.convert("L")
        arr = np.asarray(gray, dtype=np.float64)

        # --- Sharpness ---
        laplacian = _convolve2d_manual(arr, _LAPLACIAN_KERNEL)
        laplacian_var = float(np.var(laplacian))
        sharpness = min(laplacian_var / 1000.0, 1.0)

        # --- Contrast ---
        contrast = min(float(np.std(arr)) / 128.0, 1.0)

        # --- Brightness ---
        mean_brightness = float(np.mean(arr)) / 255.0
        if mean_brightness < 0.2:
            brightness_score = mean_brightness / 0.2 * 0.5
        elif mean_brightness > 0.9:
            brightness_score = (1.0 - mean_brightness) / 0.1 * 0.5
        else:
            brightness_score = 0.5 + (mean_brightness - 0.2) / 0.7 * 0.5

        # --- Noise ---
        mad = float(np.median(np.abs(laplacian - np.median(laplacian))))
        noise = min(mad / 50.0, 1.0)

        # --- Overall ---
        overall = (
            0.4 * sharpness
            + 0.3 * contrast
            + 0.2 * brightness_score
            + 0.1 * (1.0 - noise)
        )
        overall = round(min(max(overall, 0.0), 1.0), 4)

        is_acceptable = overall >= threshold
        rejection_reason = None
        if not is_acceptable:
            reasons = []
            if sharpness < 0.1:
                reasons.append("too blurry")
            if contrast < 0.05:
                reasons.append("low contrast")
            if mean_brightness < 0.1:
                reasons.append("too dark")
            if mean_brightness > 0.95:
                reasons.append("too bright (blank)")
            if noise > 0.8:
                reasons.append("too noisy")
            rejection_reason = "; ".join(reasons) if reasons else "overall quality below threshold"

        return QualityScore(
            overall=overall,
            sharpness=round(sharpness, 4),
            contrast=round(contrast, 4),
            brightness=round(mean_brightness, 4),
            noise_level=round(noise, 4),
            is_acceptable=is_acceptable,
            rejection_reason=rejection_reason,
        )
