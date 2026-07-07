"""Tests for PDF rendering service."""

from __future__ import annotations

import io

import fitz
import pytest
from PIL import Image

from app.config import get_settings
from app.services.pdf_render import PDFRenderer, PageImage


def create_test_pdf(
    num_pages: int,
    page_width: float = 595,
    page_height: float = 842,
    text: str = "Test Page",
) -> bytes:
    """Create a simple PDF with text on each page."""
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=page_width, height=page_height)
        page.insert_text((72, 72), f"{text} {i + 1}")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture
def renderer():
    return PDFRenderer()


class TestPDFRenderer:
    def test_single_page(self, renderer: PDFRenderer):
        pdf_bytes = create_test_pdf(1)
        pages = renderer.render_pages(pdf_bytes)

        assert len(pages) == 1
        page = pages[0]
        assert page.page_number == 0
        assert page.width > 0
        assert page.height > 0
        assert isinstance(page, PageImage)

    def test_multi_page(self, renderer: PDFRenderer):
        pdf_bytes = create_test_pdf(5)
        pages = renderer.render_pages(pdf_bytes)

        assert len(pages) == 5
        for i, page in enumerate(pages):
            assert page.page_number == i
            assert page.width > 0
            assert page.height > 0

    def test_empty_pdf_raises(self, renderer: PDFRenderer):
        # PyMuPDF won't serialize a 0-page doc, so craft minimal raw PDF bytes
        # with an empty Pages tree (0 kids).
        raw = (
            b"%PDF-1.0\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
            b"xref\n0 3\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"trailer<</Size 3/Root 1 0 R>>\n"
            b"startxref\n108\n%%EOF\n"
        )
        with pytest.raises(ValueError, match="no pages"):
            renderer.render_pages(raw)

    def test_empty_bytes_raises(self, renderer: PDFRenderer):
        with pytest.raises(ValueError, match="empty"):
            renderer.render_pages(b"")

    def test_page_images_are_valid_png(self, renderer: PDFRenderer):
        pdf_bytes = create_test_pdf(3)
        pages = renderer.render_pages(pdf_bytes)

        for page in pages:
            img = Image.open(io.BytesIO(page.image_bytes))
            assert img.format == "PNG"
            assert img.size == (page.width, page.height)

    def test_dpi_affects_dimensions(self, renderer: PDFRenderer):
        pdf_bytes = create_test_pdf(1)

        pages_low = renderer.render_pages(pdf_bytes, dpi=100)
        pages_high = renderer.render_pages(pdf_bytes, dpi=300)

        assert pages_high[0].width > pages_low[0].width
        assert pages_high[0].height > pages_low[0].height

    def test_default_dpi_from_settings(self, renderer: PDFRenderer):
        pdf_bytes = create_test_pdf(1)
        settings = get_settings()

        pages_default = renderer.render_pages(pdf_bytes)
        pages_explicit = renderer.render_pages(pdf_bytes, dpi=settings.PDF_RENDER_DPI)

        assert pages_default[0].width == pages_explicit[0].width
        assert pages_default[0].height == pages_explicit[0].height

    def test_encrypted_pdf_raises(self, renderer: PDFRenderer):
        doc = fitz.open()
        doc.new_page()
        pdf_bytes = doc.tobytes(garbage=4, deflate=True, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret")
        doc.close()

        with pytest.raises(ValueError):
            renderer.render_pages(pdf_bytes)
