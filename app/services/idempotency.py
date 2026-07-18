"""Redis-backed idempotency key service for job deduplication."""

from __future__ import annotations

import logging
import json

logger = logging.getLogger(__name__)

_KEY_PREFIX = "idempotency:"
_DEFAULT_TTL = 86400  # 24 hours
_PENDING_TTL = 300  # 5 minutes


class IdempotencyService:
    """Redis-backed idempotency key service for job deduplication."""

    def __init__(self, redis_url: str, *, fail_closed: bool = False) -> None:
        self._redis_url = redis_url
        self._fail_closed = fail_closed
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

        NOTE: Race-prone when called with a freshly generated job_id; prefer
        `claim_or_get` which uses SET NX for atomic claim.
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

    async def claim_or_get(
        self, key: str, job_id: str, ttl_seconds: int = _DEFAULT_TTL
    ) -> tuple[bool, str | None] | None:
        """Atomically claim the key for `job_id` using SET NX EX.

        Returns (claimed, existing_job_id).
        - If claimed: returns (True, job_id) — caller should proceed.
        - If key already existed: returns (False, existing_job_id).
        - If Redis is unavailable and fail_closed is True: returns None.

        Race-safe: two concurrent callers with the same key get exactly one
        True and one False. Without Redis and fail_closed=False, falls back
        to (True, job_id) so the caller proceeds (with a warning).
        """
        r = await self._get_redis()
        if r is None:
            if self._fail_closed:
                logger.error("Redis unavailable; fail-closed rejects idempotency claim for key=%s", key)
                return None
            logger.warning("Redis unavailable; claim-or-get falls through (proceed) for key=%s", key)
            return (True, job_id)

        redis_key = f"{_KEY_PREFIX}{key}"
        try:
            ok = await r.set(redis_key, job_id, nx=True, ex=ttl_seconds)
            if ok:
                return (True, job_id)
            existing = await r.get(redis_key)
            return (False, existing)
        except Exception:
            logger.warning("Redis error during claim-or-get for key=%s", key, exc_info=True)
            if self._fail_closed:
                return None
            return (True, job_id)

    async def claim_or_get_checked(
        self, key: str, job_id: str, fingerprint: str, ttl_seconds: int = _DEFAULT_TTL
    ) -> tuple[bool, str | None, bool] | None:
        """Atomically claim the key with fingerprint binding.

        Returns (claimed, existing_job_id, payload_conflict).
        - If claimed: returns (True, job_id, False).
        - If key already existed with same fingerprint: returns (False, existing_job_id, False).
        - If key already existed with different fingerprint: returns (False, existing_job_id, True).
        - If Redis is unavailable and fail_closed is True: returns None.

        The stored value format is ``{job_id}#{fingerprint}`` so callers
        of the original ``claim_or_get`` (which stores plain job_id) are
        unaffected.
        """
        operation = await self.claim_or_get_operation(
            key, job_id, fingerprint, pending_ttl_seconds=ttl_seconds,
        )
        if operation is None:
            return None
        claimed, existing_id, conflict, _state = operation
        return (claimed, existing_id, conflict)

    async def claim_or_get_operation(
        self,
        key: str,
        resource_id: str,
        fingerprint: str,
        *,
        pending_ttl_seconds: int = _PENDING_TTL,
    ) -> tuple[bool, str | None, bool, str] | None:
        """Claim an idempotency key with an expiring pending operation lease.

        Returns ``(claimed, resource_id, payload_conflict, state)``. Duplicate
        callers must retain the owner resource; they must never delete-reclaim a
        pending operation.
        """
        r = await self._get_redis()
        if r is None:
            if self._fail_closed:
                logger.error("Redis unavailable; fail-closed rejects operation claim for key=%s", key)
                return None
            logger.warning("Redis unavailable; operation claim falls through for key=%s", key)
            return (True, resource_id, False, "pending")

        redis_key = f"{_KEY_PREFIX}{key}"
        stored_value = json.dumps({
            "resource_id": resource_id,
            "fingerprint": fingerprint,
            "state": "pending",
        }, separators=(",", ":"))
        try:
            result = await r.eval(
                """
                local existing = redis.call('GET', KEYS[1])
                if existing then
                    return {0, existing}
                end
                redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
                return {1, ARGV[1]}
                """,
                1,
                redis_key,
                stored_value,
                str(pending_ttl_seconds),
            )
            claimed = bool(result[0])
            existing_raw = result[1]
            if claimed:
                return (True, resource_id, False, "pending")
            try:
                existing = json.loads(existing_raw)
            except (TypeError, json.JSONDecodeError):
                if "#" in existing_raw:
                    existing_id, existing_fp = existing_raw.rsplit("#", 1)
                else:
                    existing_id, existing_fp = existing_raw, None
                return (False, existing_id, existing_fp not in (None, fingerprint), "completed")
            existing_id = existing.get("resource_id")
            existing_fp = existing.get("fingerprint")
            state = existing.get("state", "pending")
            return (False, existing_id, existing_fp != fingerprint, state)
        except Exception:
            logger.warning("Redis error during operation claim for key=%s", key, exc_info=True)
            if self._fail_closed:
                return None
            return (True, resource_id, False, "pending")

    async def mark_operation_completed(
        self,
        key: str,
        resource_id: str,
        fingerprint: str,
        *,
        ttl_seconds: int = _DEFAULT_TTL,
    ) -> bool:
        """Promote an owned pending operation to a completed idempotency record."""
        r = await self._get_redis()
        if r is None:
            return not self._fail_closed
        redis_key = f"{_KEY_PREFIX}{key}"
        pending_value = json.dumps({
            "resource_id": resource_id,
            "fingerprint": fingerprint,
            "state": "pending",
        }, separators=(",", ":"))
        completed_value = json.dumps({
            "resource_id": resource_id,
            "fingerprint": fingerprint,
            "state": "completed",
        }, separators=(",", ":"))
        try:
            result = await r.eval(
                """
                if redis.call('GET', KEYS[1]) ~= ARGV[1] then
                    return 0
                end
                redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
                return 1
                """,
                1,
                redis_key,
                pending_value,
                completed_value,
                str(ttl_seconds),
            )
            return bool(result)
        except Exception:
            logger.warning("Redis error completing operation for key=%s", key, exc_info=True)
            return False

    async def renew_pending_operation(
        self,
        key: str,
        resource_id: str,
        fingerprint: str,
        *,
        ttl_seconds: int = _PENDING_TTL,
    ) -> bool:
        """Renew an owned pending operation lease without reviving a completed key."""
        r = await self._get_redis()
        if r is None:
            return not self._fail_closed
        redis_key = f"{_KEY_PREFIX}{key}"
        pending_value = json.dumps({
            "resource_id": resource_id,
            "fingerprint": fingerprint,
            "state": "pending",
        }, separators=(",", ":"))
        try:
            result = await r.eval(
                """
                if redis.call('GET', KEYS[1]) ~= ARGV[1] then
                    return 0
                end
                return redis.call('EXPIRE', KEYS[1], ARGV[2])
                """,
                1,
                redis_key,
                pending_value,
                str(ttl_seconds),
            )
            return bool(result)
        except Exception:
            logger.warning("Redis error renewing operation for key=%s", key, exc_info=True)
            return False

    async def release_pending_operation(
        self, key: str, resource_id: str, fingerprint: str
    ) -> bool:
        """Release only the caller's failed pending operation."""
        r = await self._get_redis()
        if r is None:
            return False
        redis_key = f"{_KEY_PREFIX}{key}"
        pending_value = json.dumps({
            "resource_id": resource_id,
            "fingerprint": fingerprint,
            "state": "pending",
        }, separators=(",", ":"))
        try:
            result = await r.eval(
                """
                if redis.call('GET', KEYS[1]) ~= ARGV[1] then
                    return 0
                end
                return redis.call('DEL', KEYS[1])
                """,
                1,
                redis_key,
                pending_value,
            )
            return bool(result)
        except Exception:
            logger.warning("Redis error releasing operation for key=%s", key, exc_info=True)
            return False

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
