"""Tests for IdempotencyService."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.idempotency import IdempotencyService


@pytest.fixture
def service():
    return IdempotencyService(redis_url="redis://localhost:6379/0")


@pytest.fixture
def mock_redis():
    """Create a mock async Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    return redis


class TestCheckAndStore:
    @pytest.mark.asyncio
    async def test_new_key_returns_not_duplicate(self, service, mock_redis):
        mock_redis.get.return_value = None
        service._redis = mock_redis

        is_dup, existing = await service.check_and_store("key-1", "job-abc")

        assert is_dup is False
        assert existing is None
        mock_redis.get.assert_awaited_once_with("idempotency:key-1")
        mock_redis.setex.assert_awaited_once_with("idempotency:key-1", 86400, "job-abc")

    @pytest.mark.asyncio
    async def test_existing_key_returns_duplicate(self, service, mock_redis):
        mock_redis.get.return_value = "job-existing"
        service._redis = mock_redis

        is_dup, existing = await service.check_and_store("key-1", "job-new")

        assert is_dup is True
        assert existing == "job-existing"
        mock_redis.setex.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_custom_ttl(self, service, mock_redis):
        mock_redis.get.return_value = None
        service._redis = mock_redis

        await service.check_and_store("key-1", "job-abc", ttl_seconds=300)

        mock_redis.setex.assert_awaited_once_with("idempotency:key-1", 300, "job-abc")

    @pytest.mark.asyncio
    async def test_redis_unavailable_graceful_degradation(self, service):
        """When Redis is unavailable, check_and_store should allow the request through."""
        service._redis = None

        with patch.object(service, "_get_redis", return_value=None):
            is_dup, existing = await service.check_and_store("key-1", "job-abc")

        assert is_dup is False
        assert existing is None


class TestGet:
    @pytest.mark.asyncio
    async def test_get_returns_stored_job_id(self, service, mock_redis):
        mock_redis.get.return_value = "job-abc"
        service._redis = mock_redis

        result = await service.get("key-1")

        assert result == "job-abc"
        mock_redis.get.assert_awaited_once_with("idempotency:key-1")

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, service, mock_redis):
        mock_redis.get.return_value = None
        service._redis = mock_redis

        result = await service.get("missing-key")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_redis_unavailable_returns_none(self, service):
        service._redis = None

        with patch.object(service, "_get_redis", return_value=None):
            result = await service.get("key-1")

        assert result is None


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_existing_key(self, service, mock_redis):
        mock_redis.delete.return_value = 1
        service._redis = mock_redis

        result = await service.delete("key-1")

        assert result is True
        mock_redis.delete.assert_awaited_once_with("idempotency:key-1")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key(self, service, mock_redis):
        mock_redis.delete.return_value = 0
        service._redis = mock_redis

        result = await service.delete("missing-key")

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_redis_unavailable(self, service):
        service._redis = None

        with patch.object(service, "_get_redis", return_value=None):
            result = await service.delete("key-1")

        assert result is False


class TestClaimOrGetChecked:
    @pytest.mark.asyncio
    async def test_new_key_claims_successfully(self, service, mock_redis):
        mock_redis.eval.return_value = [
            1,
            json.dumps(
                {
                    "resource_id": "job-abc",
                    "fingerprint": "fp-abc",
                    "state": "pending",
                }
            ),
        ]
        service._redis = mock_redis

        result = await service.claim_or_get_checked("key-1", "job-abc", "fp-abc")

        assert result == (True, "job-abc", False)
        mock_redis.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_same_fingerprint_no_conflict(self, service, mock_redis):
        mock_redis.eval.return_value = [
            0,
            json.dumps(
                {
                    "resource_id": "job-existing",
                    "fingerprint": "fp-abc",
                    "state": "pending",
                }
            ),
        ]
        service._redis = mock_redis

        result = await service.claim_or_get_checked("key-1", "job-new", "fp-abc")

        assert result == (False, "job-existing", False)

    @pytest.mark.asyncio
    async def test_different_fingerprint_returns_conflict(self, service, mock_redis):
        mock_redis.eval.return_value = [
            0,
            json.dumps(
                {
                    "resource_id": "job-existing",
                    "fingerprint": "fp-abc",
                    "state": "pending",
                }
            ),
        ]
        service._redis = mock_redis

        result = await service.claim_or_get_checked("key-1", "job-new", "fp-DIFFERENT")

        assert result == (False, "job-existing", True)

    @pytest.mark.asyncio
    async def test_legacy_value_without_separator(self, service, mock_redis):
        """If stored value is plain job_id (no #), treat as no fingerprint."""
        mock_redis.eval.return_value = [0, "job-existing"]
        service._redis = mock_redis

        result = await service.claim_or_get_checked("key-1", "job-new", "fp-abc")

        assert result == (False, "job-existing", False)

    @pytest.mark.asyncio
    async def test_redis_unavailable_fail_closed(self, service):
        service._fail_closed = True
        service._redis = None

        with patch.object(service, "_get_redis", return_value=None):
            result = await service.claim_or_get_checked("key-1", "job-abc", "fp-abc")

        assert result is None


class TestOperationLease:
    @pytest.mark.asyncio
    async def test_renew_pending_operation_extends_only_owned_lease(self, service, mock_redis):
        mock_redis.eval.return_value = 1
        service._redis = mock_redis

        result = await service.renew_pending_operation(
            "key-1",
            "job-abc",
            "fp-abc",
            ttl_seconds=300,
        )

        assert result is True
        mock_redis.eval.assert_awaited_once()
