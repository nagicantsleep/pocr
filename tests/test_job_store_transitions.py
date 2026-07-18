import threading
from unittest.mock import MagicMock

from app.services.job_store import JobStatus, JobStore


def test_redis_update_uses_atomic_compare_and_set():
    store = JobStore.__new__(JobStore)
    store.backend = "redis"
    store.settings = MagicMock(JOB_TTL_HOURS=24)
    store.redis_client = MagicMock()
    store.redis_client.eval.return_value = 1

    updated = store.update_job(
        "job-123",
        status=JobStatus.COMPLETED,
        expected_statuses=(JobStatus.RUNNING,),
    )

    assert updated is True
    store.redis_client.eval.assert_called_once()


def test_find_job_by_idempotency_recovers_completed_filesystem_job(tmp_path):
    store = JobStore.__new__(JobStore)
    store.backend = "filesystem"
    store.job_dir = tmp_path
    store.settings = MagicMock(JOB_TTL_HOURS=24)
    store._transition_lock = threading.RLock()

    created = store.create_job(
        images=["encoded"],
        tenant_id="tenant-a",
        idempotency_key="tenant-a:retry-key",
        request_fingerprint="fingerprint",
    )
    assert store.update_job(
        created["job_id"],
        status=JobStatus.COMPLETED,
        expected_statuses=(JobStatus.QUEUED,),
    )

    recovered = store.find_job_by_idempotency(
        "tenant-a",
        "tenant-a:retry-key",
        "fingerprint",
    )

    assert recovered is not None
    assert recovered["job_id"] == created["job_id"]
    assert recovered["status"] == JobStatus.COMPLETED


def test_idempotency_recovery_retains_terminal_status_for_retry_policy(tmp_path):
    store = JobStore.__new__(JobStore)
    store.backend = "filesystem"
    store.job_dir = tmp_path
    store.settings = MagicMock(JOB_TTL_HOURS=24)
    store._transition_lock = threading.RLock()

    created = store.create_job(
        images=["encoded"],
        tenant_id="tenant-a",
        idempotency_key="tenant-a:retry-after-failure",
        request_fingerprint="fingerprint",
    )
    assert store.update_job(
        created["job_id"],
        status=JobStatus.FAILED,
        expected_statuses=(JobStatus.QUEUED,),
    )

    recovered = store.find_job_by_idempotency(
        "tenant-a",
        "tenant-a:retry-after-failure",
        "fingerprint",
    )

    assert recovered is not None
    assert recovered["status"] in {JobStatus.FAILED, JobStatus.CANCELLED}
