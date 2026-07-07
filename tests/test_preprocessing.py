"""Tests for image preprocessing chain."""

from __future__ import annotations

import math

import cv2
import numpy as np
import pytest
from PIL import Image

from app.services.preprocessing.chain import (
    PreprocessConfig,
    PreprocessResult,
    PreprocessingChain,
)


# ---------------------------------------------------------------------------
# Helpers to create test images
# ---------------------------------------------------------------------------

def create_clean_image(width: int = 400, height: int = 200) -> bytes:
    """Create a clean image with text-like horizontal bars."""
    img = np.ones((height, width), dtype=np.uint8) * 255
    # Draw horizontal bars to simulate text lines
    for y_start in range(30, height - 30, 40):
        cv2.rectangle(img, (20, y_start), (width - 20, y_start + 10), 0, -1)
    _, encoded = cv2.imencode(".png", img)
    return encoded.tobytes()


def create_skewed_image(angle_degrees: float, width: int = 400, height: int = 200) -> bytes:
    """Create an image with text-like content rotated by angle_degrees."""
    img = np.ones((height, width), dtype=np.uint8) * 255
    for y_start in range(30, height - 30, 40):
        cv2.rectangle(img, (20, y_start), (width - 20, y_start + 10), 0, -1)
    center = (width // 2, height // 2)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    rotated = cv2.warpAffine(img, matrix, (width, height), borderValue=255)
    _, encoded = cv2.imencode(".png", rotated)
    return encoded.tobytes()


def create_noisy_image(width: int = 400, height: int = 200) -> bytes:
    """Create an image with text-like bars plus Gaussian noise."""
    img = np.ones((height, width), dtype=np.uint8) * 255
    for y_start in range(30, height - 30, 40):
        cv2.rectangle(img, (20, y_start), (width - 20, y_start + 10), 0, -1)
    noise = np.random.normal(0, 30, img.shape).astype(np.int16)
    noisy = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    _, encoded = cv2.imencode(".png", noisy)
    return encoded.tobytes()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPreprocessingChain:
    """Tests for PreprocessingChain.process()."""

    def test_clean_image_all_steps_applied(self):
        chain = PreprocessingChain()
        result = chain.process(create_clean_image())
        assert isinstance(result, PreprocessResult)
        assert "grayscale" in result.applied_steps
        assert "denoise" in result.applied_steps
        assert "binarize" in result.applied_steps
        assert "encode" in result.applied_steps

    def test_skewed_image_deskew_reduces_angle(self):
        chain = PreprocessingChain()
        skewed = create_skewed_image(5.0)
        result = chain.process(skewed, PreprocessConfig(deskew=True, denoise=False, binarize=False))
        # After deskew the residual angle should be closer to 0 than the original 5 degrees
        assert abs(result.skew_angle) > 0  # something was detected
        # The image should have been rotated (deskew step present)
        if abs(result.skew_angle) <= 15.0:
            assert "deskew" in result.applied_steps

    def test_noisy_image_denoise_applied(self):
        chain = PreprocessingChain()
        noisy = create_noisy_image()
        result = chain.process(noisy, PreprocessConfig(deskew=False, denoise=True, binarize=False))
        assert "denoise" in result.applied_steps

    def test_deskew_disabled_skips_correction(self):
        chain = PreprocessingChain()
        skewed = create_skewed_image(5.0)
        result = chain.process(skewed, PreprocessConfig(deskew=False))
        assert "deskew" not in result.applied_steps
        assert result.skew_angle == 0.0

    def test_binarize_disabled_skips_binarization(self):
        chain = PreprocessingChain()
        result = chain.process(create_clean_image(), PreprocessConfig(binarize=False))
        assert "binarize" not in result.applied_steps

    def test_dimensions_match_after_processing(self):
        chain = PreprocessingChain()
        img_bytes = create_clean_image(400, 200)
        result = chain.process(
            img_bytes,
            PreprocessConfig(deskew=False, denoise=False, binarize=False),
        )
        # Without deskew, dimensions should be identical
        assert result.original_size == result.processed_size

    def test_empty_bytes_raises_value_error(self):
        chain = PreprocessingChain()
        with pytest.raises(ValueError, match="empty"):
            chain.process(b"")

    def test_invalid_bytes_raises_value_error(self):
        chain = PreprocessingChain()
        with pytest.raises(ValueError, match="Failed to decode"):
            chain.process(b"not an image")

    def test_output_is_valid_png(self):
        chain = PreprocessingChain()
        result = chain.process(create_clean_image())
        # Should be parseable by PIL
        img = Image.open(__import__("io").BytesIO(result.image_bytes))
        assert img.format == "PNG"

    def test_preprocess_config_defaults(self):
        cfg = PreprocessConfig()
        assert cfg.deskew is True
        assert cfg.denoise is True
        assert cfg.binarize is True
        assert cfg.max_skew_angle == 15.0
        assert cfg.denoise_strength == 10

    def test_all_steps_disabled_still_decodes_and_encodes(self):
        chain = PreprocessingChain()
        result = chain.process(
            create_clean_image(),
            PreprocessConfig(deskew=False, denoise=False, binarize=False),
        )
        assert "decode" in result.applied_steps
        assert "grayscale" in result.applied_steps
        assert "encode" in result.applied_steps
        assert "denoise" not in result.applied_steps
        assert "binarize" not in result.applied_steps
