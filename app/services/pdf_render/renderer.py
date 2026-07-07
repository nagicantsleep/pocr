"""PDF to image renderer using PyMuPDF."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import fitz

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class PageImage:
    """A rendered PDF page."""

    page_number: int
    image_bytes: bytes
    width: int
    height: int


class PDFRenderer:
    """Converts PDF documents to page images."""

    def render_pages(
        self, pdf_bytes: bytes, dpi: int | None = None
    ) -> list[PageImage]:
        """
        Render all pages of a PDF to images.

        Args:
            pdf_bytes: Raw PDF file bytes
            dpi: Rendering resolution (default from settings)

        Returns:
            List of PageImage objects, one per page

        Raises:
            ValueError: If PDF is empty, encrypted, or invalid
        """
        settings = get_settings()
        if dpi is None:
            dpi = settings.PDF_RENDER_DPI

        if not pdf_bytes:
            raise ValueError("PDF bytes are empty")

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except fitz.FileDataError as e:
            raise ValueError(f"Invalid PDF data: {e}") from e

        try:
            if doc.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported")

            if doc.page_count == 0:
                raise ValueError("PDF has no pages")

            max_pages = settings.PDF_MAX_PAGES
            if doc.page_count > max_pages:
                raise ValueError(
                    f"PDF has {doc.page_count} pages, exceeding the limit of {max_pages}"
                )

            pages: list[PageImage] = []
            for page_num in range(doc.page_count):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(dpi=dpi)
                png_bytes = pix.tobytes(output="png")

                pages.append(
                    PageImage(
                        page_number=page_num,
                        image_bytes=png_bytes,
                        width=pix.width,
                        height=pix.height,
                    )
                )
                logger.debug(
                    "Rendered page %d at %dx%d (DPI=%d)",
                    page_num,
                    pix.width,
                    pix.height,
                    dpi,
                )

            return pages
        finally:
            doc.close()
