from __future__ import annotations

from app.storage.base import StorageAdapter


class S3StorageAdapter(StorageAdapter):
    """Stub for future S3-compatible object storage.

    This adapter implements the StorageAdapter interface but raises
    NotImplementedError for all operations. Replace with a real S3
    client (e.g. boto3/aioboto3) when S3 support is needed.
    """

    _MSG = (
        "S3StorageAdapter is a stub. Install aioboto3 and implement "
        "S3 operations when S3 backend support is required."
    )

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        raise NotImplementedError(self._MSG)

    async def get(self, key: str) -> bytes:
        raise NotImplementedError(self._MSG)

    async def delete(self, key: str) -> bool:
        raise NotImplementedError(self._MSG)

    async def exists(self, key: str) -> bool:
        raise NotImplementedError(self._MSG)

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        raise NotImplementedError(self._MSG)
