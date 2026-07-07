"""Redis-backed idempotency key service for job deduplication."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_KEY_PREFIX = "idempotency:"
_DEFAULT_TTL = 86400  # 24 hours


class IdempotencyService:
    """Redis-backed idempotency key service for job deduplication."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis = None  # lazy connect

    async def _get_redis(self):
        """Lazily connect to Redis."""
        if self._redis is None:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(
                    self._redis_url, decode_responses=True
                )
            except Exception:
                logger.warning("Failed to connect to Redis; idempotency checks disabled")
                return None
        return self._redis

    async def check_and_store(
        self, key: str, job_id: str, ttl_seconds: int = _DEFAULT_TTL
    ) -> tuple[bool, str | None]:
        """
        Check if idempotency key exists. If not, store it with the job_id.

        Returns (is_duplicate, existing_job_id).
        - If key is new: stores key -> job_id, returns (False, None)
        - If key exists: returns (True, existing_job_id)
        """
        r = await self._get_redis()
        if r is None:
            logger.warning("Redis unavailable; bypassing idempotency check for key=%s", key)
            return (False, None)

        redis_key = f"{_KEY_PREFIX}{key}"
        try:
            existing = await r.get(redis_key)
            if existing is not None:
                return (True, existing)
            await r.setex(redis_key, ttl_seconds, job_id)
            return (False, None)
        except Exception:
            logger.warning("Redis error during idempotency check for key=%s", key, exc_info=True)
            return (False, None)

    async def get(self, key: str) -> str | None:
        """Get job_id for an idempotency key, or None if not found."""
        r = await self._get_redis()
        if r is None:
            return None

        redis_key = f"{_KEY_PREFIX}{key}"
        try:
            return await r.get(redis_key)
        except Exception:
            logger.warning("Redis error during idempotency get for key=%s", key, exc_info=True)
            return None

    async def delete(self, key: str) -> bool:
        """Delete an idempotency key."""
        r = await self._get_redis()
        if r is None:
            return False

        redis_key = f"{_KEY_PREFIX}{key}"
        try:
            return bool(await r.delete(redis_key))
        except Exception:
            logger.warning("Redis error during idempotency delete for key=%s", key, exc_info=True)
            return False
