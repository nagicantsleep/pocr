"""Kafka worker for queued structured OCR standardization."""

import json
import logging
import re
import time
from typing import Any

from app.config import get_settings
from app.schemas.responses import BBox, OCRResult
from app.services.structured_extraction import StandardizerError, get_standardizer
from app.services.structured_job_store import get_structured_job_repository
from app.services.structured_queue import get_structured_job_publisher

logger = logging.getLogger(__name__)


def _retryable_status_codes() -> set[int]:
    settings = get_settings()
    return {
        int(code.strip())
        for code in settings.STANDARDIZER_RETRYABLE_STATUS_CODES.split(",")
        if code.strip()
    }


def _status_code_from_error(error: Exception) -> int | None:
    match = re.search(r"standardizer_http_error:\s*(\d+)", str(error))
    return int(match.group(1)) if match else None


def _retry_message(message: dict[str, Any], error: str, base_delay_seconds: int = 60) -> dict[str, Any]:
    attempt = int(message.get("attempt", 0)) + 1
    backoff_seconds = min(base_delay_seconds * (2 ** (attempt - 1)), 900)
    return {
        **message,
        "attempt": attempt,
        "backoff_seconds": backoff_seconds,
        "available_at": time.time() + backoff_seconds,
        "last_error": error,
    }


def _build_ocr_results(raw_result: dict[str, Any]) -> list[OCRResult]:
    results: list[OCRResult] = []
    for item in raw_result.get("results", []):
        bbox = item.get("bbox") or {"top_left": [0, 0], "bottom_right": [0, 0]}
        normalized = item.get("bbox_normalized") or {"top_left": [0, 0], "bottom_right": [0, 0]}
        results.append(
            OCRResult(
                text=item.get("text", ""),
                confidence=item.get("confidence", 0.0),
                bbox=BBox(
                    top_left=bbox.get("top_left", [0, 0]),
                    bottom_right=bbox.get("bottom_right", [0, 0]),
                ),
                bbox_normalized=BBox(
                    top_left=normalized.get("top_left", [0, 0]),
                    bottom_right=normalized.get("bottom_right", [0, 0]),
                ),
                type=item.get("type", "text"),
                polygon=item.get("polygon", []),
            )
        )
    return results


class RedisMinuteRateLimiter:
    def __init__(self) -> None:
        settings = get_settings()
        import redis

        self.client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.key = settings.STANDARDIZER_RATE_LIMIT_KEY
        self.limit = settings.STANDARDIZER_RATE_LIMIT
        self.ttl_seconds = settings.STANDARDIZER_RATE_LIMIT_TTL_SECONDS

    def acquire(self) -> bool:
        count = self.client.incr(self.key)
        if count == 1:
            self.client.expire(self.key, self.ttl_seconds)
        return count <= self.limit


def process_standardization_message(message: dict[str, Any]) -> None:
    settings = get_settings()
    repo = get_structured_job_repository()
    publisher = get_structured_job_publisher()
    job_id = message["job_id"]
    provider = message.get("provider", settings.STANDARDIZER_PROVIDER)

    limiter = RedisMinuteRateLimiter()
    if not limiter.acquire():
        logger.info("Rate limit reached for %s; republishing %s to retry", provider, job_id)
        publisher.publish(
            _retry_message(message, "rate_limited"),
            topic=settings.STRUCTURED_STANDARDIZE_RETRY_TOPIC,
        )
        return

    job = repo.get_job(job_id)
    if job is None:
        publisher.publish(
            {"job_id": job_id, "provider": provider, "error": "job_not_found"},
            topic=settings.STRUCTURED_STANDARDIZE_DLQ_TOPIC,
        )
        return

    if not repo.mark_running(job_id):
        logger.info("Ignoring duplicate or terminal job %s", job_id)
        return
    try:
        raw_ocr_results = _build_ocr_results(job["raw_ocr_json"])
        structured = get_standardizer().standardize(raw_ocr_results)
        repo.mark_success(job_id, structured.model_dump(by_alias=True, mode="json"))
    except StandardizerError as exc:
        status_code = _status_code_from_error(exc)
        if status_code in _retryable_status_codes():
            if repo.mark_queued_for_retry(job_id, str(exc)):
                publisher.publish(
                    _retry_message(message, str(exc)),
                    topic=settings.STRUCTURED_STANDARDIZE_RETRY_TOPIC,
                )
            return
        if repo.mark_failed(job_id, str(exc)):
            publisher.publish(
                {**message, "error": str(exc)},
                topic=settings.STRUCTURED_STANDARDIZE_DLQ_TOPIC,
            )
    except Exception as exc:
        if repo.mark_failed(job_id, str(exc)):
            publisher.publish(
                {**message, "error": str(exc)},
                topic=settings.STRUCTURED_STANDARDIZE_DLQ_TOPIC,
            )


def recover_stale_running_jobs() -> int:
    settings = get_settings()
    recovered = get_structured_job_repository().fail_stale_running_jobs(
        settings.STRUCTURED_JOB_STALE_SECONDS
    )
    if recovered:
        logger.warning("Worker restart recovery marked %d stale job(s) as failed", recovered)
    return recovered


def run_worker() -> None:
    from confluent_kafka import Consumer

    settings = get_settings()
    recover_stale_running_jobs()
    consumer = Consumer(
        {
            "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "group.id": "pocr-structured-standardizer",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([settings.STRUCTURED_STANDARDIZE_TOPIC, settings.STRUCTURED_STANDARDIZE_RETRY_TOPIC])
    try:
        while True:
            kafka_message = consumer.poll(1.0)
            if kafka_message is None:
                continue
            if kafka_message.error():
                logger.error("Kafka consumer error: %s", kafka_message.error())
                continue
            payload = json.loads(kafka_message.value().decode("utf-8"))
            available_at = payload.get("available_at")
            if available_at is not None:
                delay = float(available_at) - time.time()
                if delay > 0:
                    time.sleep(delay)
            process_standardization_message(payload)
            consumer.commit(kafka_message)
    finally:
        consumer.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            run_worker()
        except Exception as exc:
            logger.exception("Structured standardizer worker crashed: %s", exc)
            time.sleep(5)
