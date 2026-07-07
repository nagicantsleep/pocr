from __future__ import annotations

from abc import ABC, abstractmethod


class StorageAdapter(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        """Store data at the given key and return a storage reference."""
        ...

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieve data stored at the given key."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete data at the given key. Returns True if deleted."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check whether data exists at the given key."""
        ...

    @abstractmethod
    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a URL or path that grants temporary access to the key."""
        ...
