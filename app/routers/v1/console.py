"""Console routes for the review UI."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(prefix="/console", tags=["Console"])

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"


@router.get("/review", response_class=HTMLResponse)
async def review_console():
    """Serve the review console single-page app."""
    html_file = WEB_DIR / "review.html"
    return HTMLResponse(html_file.read_text(encoding="utf-8"))


@router.get("/review.css")
async def review_css():
    """Serve review console stylesheet."""
    return FileResponse(WEB_DIR / "review.css", media_type="text/css")


@router.get("/review.js")
async def review_js():
    """Serve review console JavaScript."""
    return FileResponse(WEB_DIR / "review.js", media_type="application/javascript")
