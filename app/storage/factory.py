from __future__ import annotations

from app.config import get_settings
from app.storage.base import StorageAdapter
from app.storage.local import LocalStorageAdapter
from app.storage.s3_stub import S3StorageAdapter


def get_storage_adapter() -> StorageAdapter:
    """Create a storage adapter based on the current configuration."""
    settings = get_settings()
    backend = settings.STORAGE_BACKEND.lower()
    if backend == "s3":
        return S3StorageAdapter()
    return LocalStorageAdapter(base_path=settings.STORAGE_PATH)
