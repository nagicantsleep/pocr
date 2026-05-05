"""Authentication helpers."""

from fastapi import Header, HTTPException

from app.config import get_settings


async def verify_api_key(
    x_api_key: str | None = Header(None, description="API key for authentication"),
):
    """Verify API key if configured."""
    settings = get_settings()
    if settings.API_KEY:
        if not x_api_key:
            raise HTTPException(status_code=401, detail="Missing API key")
        if x_api_key != settings.API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
