from __future__ import annotations

import hashlib
import hmac
import os
import time
from pathlib import Path

from app.storage.base import StorageAdapter


class LocalStorageAdapter(StorageAdapter):
    """Filesystem-backed storage adapter for local development."""

    def __init__(self, base_path: str = "./data/storage") -> None:
        self._base = Path(base_path)

    def _resolve(self, key: str) -> Path:
        return self._base / key

    def _hmac_token(self, key: str, expires_at: int) -> str:
        secret = os.environ.get("STORAGE_SIGNING_KEY", "local-dev-secret")
        payload = f"{key}:{expires_at}".encode()
        return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise FileNotFoundError(f"Storage key not found: {key}")
        return path.read_bytes()

    async def delete(self, key: str) -> bool:
        path = self._resolve(key)
        if path.exists():
            path.unlink()
            return True
        return False

    async def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        expires_at = int(time.time()) + expires_in
        token = self._hmac_token(key, expires_at)
        return f"file://{self._resolve(key)}?expires={expires_at}&token={token}"
