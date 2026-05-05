"""Image validation and preprocessing utilities."""

import io
import logging
from enum import Enum
from typing import Tuple

from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)

# Supported image formats
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}

# Magic bytes for format detection
IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": "jpeg",  # JPEG
    b"\x89PNG": "png",  # PNG
    b"BM": "bmp",  # BMP
    b"II\x2a\x00": "tiff",  # TIFF little-endian
    b"MM\x00\x2a": "tiff",  # TIFF big-endian
    b"RIFF": "webp",  # WebP (need to verify full signature)
}

# MIME type to extension mapping
MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/webp": ".webp",
}


class ImageError(Enum):
    """Image validation error codes."""

    IMAGE_EMPTY = "image_empty"
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_FORMAT = "unsupported_format"
    UNREADABLE_IMAGE = "unreadable_image"


def detect_image_format(image_bytes: bytes) -> str | None:
    """
    Detect image format from magic bytes.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Detected format string or None if unknown
    """
    for signature, format_name in IMAGE_SIGNATURES.items():
        if image_bytes.startswith(signature):
            # WebP needs additional check
            if format_name == "webp":
                if len(image_bytes) >= 12 and image_bytes[8:12] == b"WEBP":
                    return format_name
                return None  # Invalid WebP
            return format_name
    return None


def validate_and_preprocess(
    image_bytes: bytes,
) -> Tuple[bytes, bool]:
    """
    Validate and preprocess image bytes for OCR.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Tuple of (processed_bytes, was_resized)

    Raises:
        ValueError: If image is invalid or unsupported
    """
    settings = get_settings()

    # Check for empty image
    if not image_bytes or len(image_bytes) == 0:
        raise ValueError(ImageError.IMAGE_EMPTY.value)

    # Check file size
    if len(image_bytes) > settings.max_image_size_bytes:
        raise ValueError(
            f"{ImageError.FILE_TOO_LARGE.value}: "
            f"size {len(image_bytes)} exceeds {settings.max_image_size_bytes}"
        )

    # Detect format from magic bytes
    format_name = detect_image_format(image_bytes)
    if format_name is None:
        raise ValueError(ImageError.UNSUPPORTED_FORMAT.value)

    try:
        # Load image
        image = Image.open(io.BytesIO(image_bytes))

        # Store original dimensions
        original_width, original_height = image.size
        total_pixels = original_width * original_height

        was_resized = False

        # Resize if exceeds max pixels
        if total_pixels > settings.MAX_IMAGE_PIXELS:
            # Calculate scaling factor to fit within limit
            scale = (settings.MAX_IMAGE_PIXELS / total_pixels) ** 0.5
            new_width = int(original_width * scale)
            new_height = int(original_height * scale)

            # Use Lanczos resampling (Image.LANCZOS = filter 9)
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            was_resized = True
            logger.info(
                f"Resized image from {original_width}x{original_height} "
                f"to {new_width}x{new_height}"
            )

        # Convert RGBA to RGB (strip alpha channel)
        if image.mode == "RGBA":
            # Create white background for alpha blending
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])
            image = background
            logger.debug("Converted RGBA to RGB")
        elif image.mode not in ("RGB", "L", "1"):
            # Convert other modes to RGB
            image = image.convert("RGB")

        # Save processed image to bytes
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=95)
        processed_bytes = output.getvalue()

        return processed_bytes, was_resized

    except Exception as e:
        logger.error(f"Failed to process image: {e}")
        raise ValueError(f"{ImageError.UNREADABLE_IMAGE.value}: {str(e)}")


def detect_empty_or_blank(image: Image.Image) -> bool:
    """
    Check if image is empty or blank (all white/near-white).

    Args:
        image: PIL Image object

    Returns:
        True if image is blank, False otherwise
    """
    # Convert to grayscale for analysis
    if image.mode != "L":
        image = image.convert("L")

    # Get pixel statistics
    extrema = image.getextrema()
    min_val, max_val = extrema[0] if isinstance(extrema, tuple) else extrema

    # If all pixels are near white (max close to 255), consider blank
    if max_val >= 250:
        # Check if histogram is concentrated at high values
        histogram = image.histogram()

        # For a blank image, most pixels should be at or near max value
        # Blank white image will have high count at 255
        white_threshold = 240
        white_pixels = sum(histogram[white_threshold:])

        if white_pixels / sum(histogram) > 0.95:
            return True

    return False


def get_image_dimensions(image_bytes: bytes) -> Tuple[int, int] | None:
    """
    Get image dimensions without full processing.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Tuple of (width, height) or None if invalid
    """
    try:
        image = Image.open(io.BytesIO(image_bytes))
        return image.size
    except Exception:
        return None


def base64_to_bytes(base64_data: str) -> bytes:
    """
    Convert base64 string (with or without data URI prefix) to bytes.

    Args:
        base64_data: Base64 encoded string, optionally with data URI prefix

    Returns:
        Raw image bytes

    Raises:
        ValueError: If base64 data is invalid
    """
    # Strip data URI prefix if present
    if "base64," in base64_data:
        base64_data = base64_data.split("base64,")[1]

    # Clean whitespace
    base64_data = base64_data.strip()

    try:
        import base64 as b64

        return b64.b64decode(base64_data)
    except Exception as e:
        raise ValueError(f"Invalid base64 data: {str(e)}")


def bytes_to_base64(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """
    Convert image bytes to base64 string with data URI prefix.

    Args:
        image_bytes: Raw image bytes
        mime_type: MIME type for the data URI

    Returns:
        Base64 string with data URI prefix
    """
    import base64 as b64

    b64_data = b64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{b64_data}"
