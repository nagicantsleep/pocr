from __future__ import annotations

import asyncio
from typing import Any

from app.storage.base import StorageAdapter


class S3StorageAdapter(StorageAdapter):
    """S3-compatible object storage adapter."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        region: str = "us-east-1",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        force_path_style: bool = False,
        client: Any | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("STORAGE_S3_BUCKET must be set for STORAGE_BACKEND=s3")
        self.bucket = bucket
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                region_name=region,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                config=Config(s3={"addressing_style": "path"}) if force_path_style else None,
            )
        self._client = client

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
        return code in {"404", "NoSuchKey", "NotFound"}

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return f"s3://{self.bucket}/{key}"

    async def get(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self.bucket,
                Key=key,
            )
        except Exception as exc:
            if self._is_not_found(exc):
                raise FileNotFoundError(f"Storage key not found: {key}") from exc
            raise
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, key: str) -> bool:
        await asyncio.to_thread(
            self._client.delete_object,
            Bucket=self.bucket,
            Key=key,
        )
        return True

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(
                self._client.head_object,
                Bucket=self.bucket,
                Key=key,
            )
            return True
        except Exception as exc:
            if self._is_not_found(exc):
                return False
            raise

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
