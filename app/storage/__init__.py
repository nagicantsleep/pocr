from __future__ import annotations

from app.storage.base import StorageAdapter
from app.storage.factory import get_storage_adapter

__all__ = ["StorageAdapter", "get_storage_adapter"]
