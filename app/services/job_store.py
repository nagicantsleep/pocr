"""Job store service for async OCR processing."""

import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


class JobStatus:
    """Job status constants."""

    QUEUED = "queued"
    RUNNING = "running"
    COMMITTING = "committing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStore:
    """
    Job store for async OCR processing.
    Supports filesystem backend (JSON files) and Redis backend.
    """

    def __init__(self, backend: str = "filesystem"):
        """
        Initialize job store.

        Args:
            backend: Storage backend ("filesystem" or "redis")
        """
        self.settings = get_settings()
        self.backend = backend.lower()
        # ponytail: serializes transitions in this in-process slice. Replace
        # with a transactional persistent job repository before multi-process workers.
        self._transition_lock = threading.RLock()

        if self.backend == "filesystem":
            self._init_filesystem()
        elif self.backend == "redis":
            self._init_redis()
        else:
            raise ValueError(f"Unknown job backend: {backend}")

    def _init_filesystem(self) -> None:
        """Initialize filesystem backend."""
        self.job_dir = Path(self.settings.JOB_DIR)
        self.job_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Job store initialized at {self.job_dir}")

    def _init_redis(self) -> None:
        """Initialize Redis backend."""
        try:
            import redis

            self.redis_client = redis.from_url(
                self.settings.REDIS_URL,
                decode_responses=True,
            )
            logger.info(f"Job store connected to Redis at {self.settings.REDIS_URL}")
        except ImportError:
            logger.warning("Redis not installed, falling back to filesystem")
            self.backend = "filesystem"
            self._init_filesystem()
        except Exception as e:
            logger.warning(f"Redis connection failed, falling back to filesystem: {e}")
            self.backend = "filesystem"
            self._init_filesystem()

    def _get_job_file(self, job_id: str) -> Path:
        """Get the file path for a job."""
        return self.job_dir / f"{job_id}.json"

    def _load_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Load a job from storage."""
        if self.backend == "filesystem":
            job_file = self._get_job_file(job_id)
            if job_file.exists():
                try:
                    with open(job_file, "r") as f:
                        return json.load(f)
                except Exception as e:
                    logger.error(f"Failed to load job {job_id}: {e}")
                    return None
        elif self.backend == "redis":
            try:
                data = self.redis_client.get(f"ocr_job:{job_id}")
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.error(f"Failed to load job {job_id} from Redis: {e}")
        return None

    def _save_job(self, job_id: str, job_data: Dict[str, Any]) -> bool:
        """Save a job to storage."""
        if self.backend == "filesystem":
            job_file = self._get_job_file(job_id)
            temporary_file = job_file.with_suffix(".tmp")
            try:
                with open(temporary_file, "w") as f:
                    json.dump(job_data, f, indent=2, default=str)
                os.replace(temporary_file, job_file)
                return True
            except Exception as e:
                logger.error(f"Failed to save job {job_id}: {e}")
                temporary_file.unlink(missing_ok=True)
                return False
        elif self.backend == "redis":
            try:
                ttl_seconds = self.settings.JOB_TTL_HOURS * 3600
                self.redis_client.setex(
                    f"ocr_job:{job_id}",
                    ttl_seconds,
                    json.dumps(job_data, default=str),
                )
                return True
            except Exception as e:
                logger.error(f"Failed to save job {job_id} to Redis: {e}")
                return False
        return False

    @contextmanager
    def _job_transition_guard(self, job_id: str):
        """Serialize a filesystem job transition across worker processes."""
        with self._transition_lock:
            if self.backend != "filesystem":
                yield
                return

            lock_path = self.job_dir / f"{job_id}.lock"
            with open(lock_path, "a+b") as lock_file:
                lock_file.seek(0)
                lock_file.write(b"\0")
                lock_file.flush()
                if os.name == "nt":
                    import msvcrt

                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if os.name == "nt":
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _delete_job_file(self, job_id: str) -> bool:
        """Delete a job file."""
        if self.backend == "filesystem":
            job_file = self._get_job_file(job_id)
            try:
                if job_file.exists():
                    job_file.unlink()
                return True
            except Exception as e:
                logger.error(f"Failed to delete job {job_id}: {e}")
                return False
        elif self.backend == "redis":
            try:
                self.redis_client.delete(f"ocr_job:{job_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete job {job_id} from Redis: {e}")
                return False
        return False

    def create_job(
        self,
        images: List[str],
        lang: str = "auto",
        min_confidence: float = 0.0,
        layout_analysis: bool = False,
        tenant_id: str | None = "development",
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> Dict[str, Any]:
        """
        Create a new async OCR job.

        Args:
            images: List of base64-encoded images
            lang: Language code for OCR
            min_confidence: Minimum confidence threshold
            layout_analysis: Enable layout analysis

        Returns:
            Job creation response dictionary
        """
        # Generate job ID
        job_id = f"job_{uuid.uuid4().hex[:12]}"

        # Create job data
        created_at = datetime.utcnow()
        job_data = {
            "job_id": job_id,
            "status": JobStatus.QUEUED,
            "created_at": created_at.isoformat() + "Z",
            "images": images,
            "lang": lang,
            "min_confidence": min_confidence,
            "layout_analysis": layout_analysis,
            "results": [],
            "progress": {
                "processed": 0,
                "total": len(images),
            },
        }
        if tenant_id is not None:
            job_data["tenant_id"] = tenant_id
        if idempotency_key is not None:
            job_data["idempotency_key"] = idempotency_key
            job_data["request_fingerprint"] = request_fingerprint

        # Save job
        if not self._save_job(job_id, job_data):
            raise RuntimeError("Failed to create job")

        logger.info(f"Created job {job_id} with {len(images)} images")

        return {
            "job_id": job_id,
            "status": JobStatus.QUEUED,
            "created_at": job_data["created_at"],
            "status_url": f"/ocr/jobs/{job_id}",
            "estimated_completion": (
                created_at + timedelta(minutes=len(images) * 2)
            ).isoformat() + "Z",
        }

    def find_job_by_idempotency(
        self,
        tenant_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Optional[Dict[str, Any]]:
        """Recover the job created for an idempotent request after a lease loss."""
        if self.backend == "filesystem":
            for job_file in self.job_dir.glob("job_*.json"):
                job = self._load_job(job_file.stem)
                if (
                    job
                    and job.get("tenant_id") == tenant_id
                    and job.get("idempotency_key") == idempotency_key
                    and job.get("request_fingerprint") == request_fingerprint
                ):
                    return job
            return None

        try:
            for redis_key in self.redis_client.scan_iter(match="ocr_job:*"):
                raw = self.redis_client.get(redis_key)
                if not raw:
                    continue
                job = json.loads(raw)
                if (
                    job.get("tenant_id") == tenant_id
                    and job.get("idempotency_key") == idempotency_key
                    and job.get("request_fingerprint") == request_fingerprint
                ):
                    return job
        except Exception as exc:
            logger.error("Failed to recover idempotent job: %s", exc)
        return None

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get job status and results.

        Args:
            job_id: Job identifier

        Returns:
            Job data dictionary or None if not found
        """
        job_data = self._load_job(job_id)
        if job_data is None:
            return None

        # Check for expired job
        if self.backend == "filesystem":
            created_at = datetime.fromisoformat(job_data["created_at"].replace("Z", "+00:00"))
            if datetime.utcnow() - created_at.replace(tzinfo=None) > timedelta(hours=self.settings.JOB_TTL_HOURS):
                self._delete_job_file(job_id)
                return None

        return job_data

    def update_job(
        self,
        job_id: str,
        status: Optional[str] = None,
        results: Optional[List[Dict[str, Any]]] = None,
        progress: Optional[Dict[str, int]] = None,
        error: Optional[str] = None,
        expected_statuses: tuple[str, ...] | None = None,
    ) -> bool:
        """
        Update job status and results.

        Args:
            job_id: Job identifier
            status: New job status
            results: Processing results
            progress: Progress information
            error: Error message if failed

        Returns:
            True if updated successfully
        """
        if self.backend == "redis":
            return self._update_redis_job(
                job_id,
                status=status,
                results=results,
                progress=progress,
                error=error,
                expected_statuses=expected_statuses,
            )

        with self._job_transition_guard(job_id):
            job_data = self._load_job(job_id)
            if job_data is None:
                return False
            if expected_statuses and job_data.get("status") not in expected_statuses:
                return False

            if status:
                job_data["status"] = status

            if results is not None:
                job_data["results"] = results

            if progress:
                job_data["progress"] = progress

            if error:
                job_data["error"] = error

            if status == JobStatus.RUNNING and "started_at" not in job_data:
                job_data["started_at"] = datetime.utcnow().isoformat() + "Z"

            if status in (JobStatus.COMPLETED, JobStatus.FAILED):
                job_data["completed_at"] = datetime.utcnow().isoformat() + "Z"

            return self._save_job(job_id, job_data)

    def _update_redis_job(
        self,
        job_id: str,
        *,
        status: Optional[str],
        results: Optional[List[Dict[str, Any]]],
        progress: Optional[Dict[str, int]],
        error: Optional[str],
        expected_statuses: tuple[str, ...] | None,
    ) -> bool:
        """Atomically compare and update a Redis-backed job."""
        updates: dict[str, Any] = {}
        if status:
            updates["status"] = status
        if results is not None:
            updates["results"] = results
        if progress:
            updates["progress"] = progress
        if error:
            updates["error"] = error

        try:
            result = self.redis_client.eval(
                """
                local raw = redis.call('GET', KEYS[1])
                if not raw then
                    return 0
                end
                local job = cjson.decode(raw)
                local expected = cjson.decode(ARGV[1])
                if #expected > 0 then
                    local allowed = false
                    for _, value in ipairs(expected) do
                        if job.status == value then
                            allowed = true
                            break
                        end
                    end
                    if not allowed then
                        return 0
                    end
                end
                local updates = cjson.decode(ARGV[2])
                for key, value in pairs(updates) do
                    job[key] = value
                end
                if updates.status == 'running' and not job.started_at then
                    job.started_at = ARGV[3]
                end
                if updates.status == 'completed' or updates.status == 'failed' then
                    job.completed_at = ARGV[3]
                end
                redis.call('SETEX', KEYS[1], ARGV[4], cjson.encode(job))
                return 1
                """,
                1,
                f"ocr_job:{job_id}",
                json.dumps(list(expected_statuses or ())),
                json.dumps(updates, default=str),
                datetime.utcnow().isoformat() + "Z",
                str(self.settings.JOB_TTL_HOURS * 3600),
            )
            return bool(result)
        except Exception as exc:
            logger.error("Failed to atomically update Redis job %s: %s", job_id, exc)
            return False

    def delete_job(self, job_id: str) -> bool:
        """
        Delete a job completely.

        Args:
            job_id: Job identifier

        Returns:
            True if deleted successfully
        """
        return self._delete_job_file(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a pending or running job.

        Args:
            job_id: Job identifier

        Returns:
            True if cancelled successfully
        """
        return self.update_job(
            job_id,
            status=JobStatus.CANCELLED,
            expected_statuses=(JobStatus.QUEUED, JobStatus.RUNNING),
        )

    def fail_stale_jobs(self, stale_statuses: tuple[str, ...] = ("running", "committing")) -> int:
        """Mark jobs in transient statuses as failed on startup recovery.

        Called during application startup to handle jobs that were interrupted
        by a process restart. Returns the number of jobs transitioned.
        """
        count = 0
        jobs = self.list_jobs()
        for job in jobs:
            if job.get("status") in stale_statuses:
                job_id = job["job_id"]
                ok = self.update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    error="Process restarted while job was in progress; marked failed by startup recovery",
                    expected_statuses=stale_statuses,
                )
                if ok:
                    logger.warning("Startup recovery: marked job %s as failed (was %s)", job_id, job.get("status"))
                    count += 1
        return count

    def list_jobs(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List jobs with optional status filter.

        Args:
            status: Filter by status (optional)
            limit: Maximum number of jobs to return

        Returns:
            List of job data dictionaries
        """
        jobs = []

        if self.backend == "filesystem":
            try:
                for job_file in sorted(self.job_dir.glob("*.json"), reverse=True)[:limit]:
                    try:
                        with open(job_file, "r") as f:
                            job = json.load(f)
                            if status is None or job.get("status") == status:
                                jobs.append(job)
                    except Exception:
                        continue
            except Exception as e:
                logger.error(f"Failed to list jobs: {e}")

        return jobs[:limit]


# Global job store instance
_job_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    """Get or create the job store instance."""
    global _job_store
    if _job_store is None:
        settings = get_settings()
        _job_store = JobStore(backend=settings.JOB_BACKEND)
    return _job_store
