"""Visual table detection using OpenCV with text-based fallback."""

from app.services.table_visual.detector import (
    CellRegion,
    TableRegion,
    VisualTableDetector,
)

__all__ = ["CellRegion", "TableRegion", "VisualTableDetector"]
