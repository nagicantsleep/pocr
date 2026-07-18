"""PostgreSQL-backed structured OCR job state."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings

STRUCTURED_JOB_SCHEMA = """
CREATE TABLE IF NOT EXISTS structured_ocr_jobs (
    job_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'success', 'failed')),
    raw_ocr_json JSONB NOT NULL,
    structured_json JSONB NULL,
    error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class StructuredJobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class StructuredJobRepository:
    def __init__(self, dsn: str | None = None, min_connections: int = 1, max_connections: int = 10) -> None:
        import psycopg_pool

        self.dsn = dsn or get_settings().POSTGRES_DSN
        self._pool = psycopg_pool.ConnectionPool(
            self.dsn,
            min_size=min_connections,
            max_size=max_connections,
            open=False,
        )
        self._pool.open()

    def _conn(self):
        return self._pool.connection()

    def ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(STRUCTURED_JOB_SCHEMA)

    def create_job(self, raw_ocr_json: dict[str, Any], provider: str) -> dict[str, Any]:
        job_id = f"structured_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc)
        self.ensure_schema()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO structured_ocr_jobs
                    (job_id, provider, status, raw_ocr_json, structured_json, created_at, updated_at)
                VALUES
                    (%s, %s, %s, %s::jsonb, NULL, %s, %s)
                """,
                (
                    job_id,
                    provider,
                    StructuredJobStatus.QUEUED,
                    json.dumps(raw_ocr_json),
                    now,
                    now,
                ),
            )
        return {
            "job_id": job_id,
            "provider": provider,
            "status": StructuredJobStatus.QUEUED,
            "created_at": now.isoformat(),
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT job_id, provider, status, raw_ocr_json, structured_json, error,
                       created_at, started_at, completed_at
                FROM structured_ocr_jobs
                WHERE job_id = %s
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "job_id": row[0],
            "provider": row[1],
            "status": row[2],
            "raw_ocr_json": row[3],
            "structured_json": row[4],
            "error": row[5],
            "created_at": row[6],
            "started_at": row[7],
            "completed_at": row[8],
        }

    def mark_running(self, job_id: str) -> bool:
        now = datetime.now(timezone.utc)
        self.ensure_schema()
        with self._conn() as conn:
            result = conn.execute(
                """
                UPDATE structured_ocr_jobs
                SET status = %s, started_at = COALESCE(started_at, %s), updated_at = %s
                WHERE job_id = %s AND status = %s
                """,
                (
                    StructuredJobStatus.RUNNING,
                    now,
                    now,
                    job_id,
                    StructuredJobStatus.QUEUED,
                ),
            )
        return result.rowcount == 1

    def mark_success(self, job_id: str, structured_json: dict[str, Any]) -> bool:
        now = datetime.now(timezone.utc)
        self.ensure_schema()
        with self._conn() as conn:
            result = conn.execute(
                """
                UPDATE structured_ocr_jobs
                SET status = %s, structured_json = %s::jsonb, error = NULL,
                    completed_at = %s, updated_at = %s
                WHERE job_id = %s AND status = %s
                """,
                (
                    StructuredJobStatus.SUCCESS,
                    json.dumps(structured_json),
                    now,
                    now,
                    job_id,
                    StructuredJobStatus.RUNNING,
                ),
            )
        return result.rowcount == 1

    def mark_failed(self, job_id: str, error: str) -> bool:
        now = datetime.now(timezone.utc)
        self.ensure_schema()
        with self._conn() as conn:
            result = conn.execute(
                """
                UPDATE structured_ocr_jobs
                SET status = %s, error = %s, completed_at = %s, updated_at = %s
                WHERE job_id = %s AND status = %s
                """,
                (
                    StructuredJobStatus.FAILED,
                    error,
                    now,
                    now,
                    job_id,
                    StructuredJobStatus.RUNNING,
                ),
            )
        return result.rowcount == 1

    def mark_queued_for_retry(self, job_id: str, error: str) -> bool:
        now = datetime.now(timezone.utc)
        self.ensure_schema()
        with self._conn() as conn:
            result = conn.execute(
                """
                UPDATE structured_ocr_jobs
                SET status = %s, error = %s, updated_at = %s
                WHERE job_id = %s AND status = %s
                """,
                (
                    StructuredJobStatus.QUEUED,
                    error,
                    now,
                    job_id,
                    StructuredJobStatus.RUNNING,
                ),
            )
        return result.rowcount == 1

    def fail_stale_running_jobs(self, stale_after_seconds: int) -> int:
        """Fail work abandoned by a restarted standardizer worker."""
        if stale_after_seconds < 1:
            raise ValueError("stale_after_seconds must be positive")
        now = datetime.now(timezone.utc)
        self.ensure_schema()
        with self._conn() as conn:
            result = conn.execute(
                """
                UPDATE structured_ocr_jobs
                SET status = %s, error = %s, completed_at = %s, updated_at = %s
                WHERE status = %s
                  AND updated_at <= now() - make_interval(secs => %s)
                """,
                (
                    StructuredJobStatus.FAILED,
                    "Worker restarted while job was running; marked failed by recovery",
                    now,
                    now,
                    StructuredJobStatus.RUNNING,
                    stale_after_seconds,
                ),
            )
        return result.rowcount

    def close(self) -> None:
        """Close the connection pool. Call on application shutdown."""
        self._pool.close()

    def reset(self) -> None:
        """Reset the module singleton. Useful for tests."""
        global _structured_job_repository
        _structured_job_repository = None


_structured_job_repository: StructuredJobRepository | None = None


def get_structured_job_repository() -> StructuredJobRepository:
    global _structured_job_repository
    if _structured_job_repository is None:
        _structured_job_repository = StructuredJobRepository()
    return _structured_job_repository
