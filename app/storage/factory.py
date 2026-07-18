from __future__ import annotations

import logging

from app.config import get_settings
from app.storage.base import StorageAdapter
from app.storage.local import LocalStorageAdapter
from app.storage.s3_stub import S3StorageAdapter

logger = logging.getLogger(__name__)


def get_storage_adapter() -> StorageAdapter:
    """Create a storage adapter based on the current configuration."""
    settings = get_settings()
    backend = settings.STORAGE_BACKEND.lower()
    if backend == "s3":
        return S3StorageAdapter(
            bucket=settings.STORAGE_S3_BUCKET or "",
            endpoint_url=settings.STORAGE_S3_ENDPOINT_URL,
            region=settings.STORAGE_S3_REGION,
            access_key_id=settings.STORAGE_S3_ACCESS_KEY_ID,
            secret_access_key=settings.STORAGE_S3_SECRET_ACCESS_KEY,
            force_path_style=settings.STORAGE_S3_FORCE_PATH_STYLE,
        )
    if backend != "local":
        raise ValueError(f"Unsupported STORAGE_BACKEND: {settings.STORAGE_BACKEND}")
    return LocalStorageAdapter(base_path=settings.STORAGE_PATH)
