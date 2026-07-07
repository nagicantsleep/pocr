from __future__ import annotations

import io
import random

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.services.quality_gate import QualityGate, QualityScore


def _make_image_bytes(image: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()


class TestQualityGate:
    def setup_method(self):
        self.gate = QualityGate()

    def test_clean_text_image_high_quality(self):
        """White background with black text-like pattern should score well."""
        img = Image.new("RGB", (400, 200), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Simulate text strokes
        for y in range(40, 160, 12):
            draw.line([(30, y), (370, y)], fill=(0, 0, 0), width=3)
        data = _make_image_bytes(img)
        score = self.gate.assess(data)
        assert isinstance(score, QualityScore)
        assert score.is_acceptable is True
        assert score.rejection_reason is None
        assert score.sharpness > 0.1
        assert score.contrast > 0.1

    def test_blank_white_image_low_quality(self):
        """All-white image should be rejected."""
        img = Image.new("RGB", (200, 200), color=(255, 255, 255))
        data = _make_image_bytes(img)
        score = self.gate.assess(data)
        assert score.is_acceptable is False
        assert score.rejection_reason is not None
        assert score.contrast < 0.05

    def test_very_dark_image(self):
        """Very dark image should have low brightness and reduced quality."""
        img = Image.new("RGB", (200, 200), color=(5, 5, 5))
        data = _make_image_bytes(img)
        score = self.gate.assess(data)
        assert score.brightness < 0.1

    def test_noisy_image_reduces_quality(self):
        """Random pixel noise should be detected and reduce quality."""
        rng = np.random.RandomState(42)
        arr = rng.randint(0, 256, (200, 200, 3), dtype=np.uint8)
        img = Image.fromarray(arr, "RGB")
        data = _make_image_bytes(img)
        score = self.gate.assess(data)
        assert score.noise_level > 0.3

    def test_configurable_threshold(self):
        """Lower threshold lets more images pass."""
        img = Image.new("RGB", (200, 200), color=(200, 200, 200))
        draw = ImageDraw.Draw(img)
        draw.rectangle([50, 50, 150, 150], fill=(50, 50, 50))
        data = _make_image_bytes(img)
        score_strict = self.gate.assess(data, threshold=0.9)
        score_lenient = self.gate.assess(data, threshold=0.1)
        assert score_lenient.is_acceptable is True
        # The image may or may not pass strict; overall should be the same
        assert score_strict.overall == score_lenient.overall

    def test_quality_score_fields_populated(self):
        """QualityScore must have all fields populated."""
        img = Image.new("RGB", (100, 100), color=(128, 128, 128))
        data = _make_image_bytes(img)
        score = self.gate.assess(data)
        assert isinstance(score.overall, float)
        assert isinstance(score.sharpness, float)
        assert isinstance(score.contrast, float)
        assert isinstance(score.brightness, float)
        assert isinstance(score.noise_level, float)
        assert isinstance(score.is_acceptable, bool)
        # rejection_reason is either None or str
        assert score.rejection_reason is None or isinstance(score.rejection_reason, str)
