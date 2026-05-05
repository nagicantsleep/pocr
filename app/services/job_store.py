"""Job store service for async OCR processing."""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


class JobStatus:
    """Job status constants."""

    QUEUED = "queued"
    RUNNING = "running"
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
            try:
                with open(job_file, "w") as f:
                    json.dump(job_data, f, indent=2, default=str)
                return True
            except Exception as e:
                logger.error(f"Failed to save job {job_id}: {e}")
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
        job_data = self._load_job(job_id)
        if job_data is None:
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
        job_data = self._load_job(job_id)
        if job_data is None:
            return False

        # Can only cancel queued or running jobs
        if job_data["status"] not in (JobStatus.QUEUED, JobStatus.RUNNING):
            return False

        return self.update_job(job_id, status=JobStatus.CANCELLED)

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
