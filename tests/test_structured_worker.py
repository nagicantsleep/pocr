from unittest.mock import patch

from app.schemas.responses import StructuredOCRData
from app.services.structured_extraction import StandardizerError
from app.workers.structured_standardizer import process_standardization_message


class FakeLimiter:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def acquire(self):
        return self.allowed


class FakeStandardizer:
    def standardize(self, raw_ocr_results):
        assert raw_ocr_results[0].text == "Invoice"
        return StructuredOCRData(title="Invoice")


class RetryableStandardizer:
    def standardize(self, raw_ocr_results):
        raise StandardizerError("standardizer_http_error: 429 rate limit")


class PermanentFailureStandardizer:
    def standardize(self, raw_ocr_results):
        raise StandardizerError("schema rejected")


def _job():
    return {
        "job_id": "structured_test",
        "raw_ocr_json": {
            "results": [
                {
                    "text": "Invoice",
                    "confidence": 1.0,
                    "bbox": {"top_left": [0, 0], "bottom_right": [1, 1]},
                    "bbox_normalized": {"top_left": [0, 0], "bottom_right": [1, 1]},
                    "type": "text",
                    "polygon": [],
                }
            ]
        },
    }


def test_worker_standardizes_and_marks_success():
    calls = []

    class FakeRepo:
        def get_job(self, job_id):
            return _job()

        def mark_running(self, job_id):
            calls.append(("running", job_id))

        def mark_success(self, job_id, structured_json):
            calls.append(("success", job_id, structured_json["title"]))

        def mark_failed(self, job_id, error):
            calls.append(("failed", job_id, error))

    class FakePublisher:
        def publish(self, message, topic=None):
            calls.append(("publish", topic, message))

    with patch("app.workers.structured_standardizer.get_structured_job_repository", return_value=FakeRepo()), \
        patch("app.workers.structured_standardizer.RedisMinuteRateLimiter", return_value=FakeLimiter()), \
        patch("app.workers.structured_standardizer.get_structured_job_publisher", return_value=FakePublisher()), \
        patch("app.workers.structured_standardizer.get_standardizer", return_value=FakeStandardizer()):
        process_standardization_message({"job_id": "structured_test", "provider": "openrouter"})

    assert calls == [("running", "structured_test"), ("success", "structured_test", "Invoice")]


def test_worker_republishes_retryable_provider_failure():
    calls = []

    class FakeRepo:
        def get_job(self, job_id):
            return _job()

        def mark_running(self, job_id):
            calls.append(("running", job_id))

        def mark_success(self, job_id, structured_json):
            calls.append(("success", job_id))

        def mark_failed(self, job_id, error):
            calls.append(("failed", job_id, error))

    class FakePublisher:
        def publish(self, message, topic=None):
            calls.append(
                (
                    "publish",
                    topic,
                    message["job_id"],
                    message.get("attempt"),
                    message.get("backoff_seconds"),
                    "available_at" in message,
                )
            )

    with patch("app.workers.structured_standardizer.get_structured_job_repository", return_value=FakeRepo()), \
        patch("app.workers.structured_standardizer.RedisMinuteRateLimiter", return_value=FakeLimiter()), \
        patch("app.workers.structured_standardizer.get_structured_job_publisher", return_value=FakePublisher()), \
        patch("app.workers.structured_standardizer.get_standardizer", return_value=RetryableStandardizer()):
        process_standardization_message({"job_id": "structured_test", "provider": "openrouter"})

    assert calls == [
        ("running", "structured_test"),
        ("publish", "ocr.standardize.retry", "structured_test", 1, 60, True),
    ]


def test_worker_retries_when_rate_limited_before_provider_call():
    calls = []

    class FakeRepo:
        def get_job(self, job_id):
            calls.append(("unexpected_get_job", job_id))
            return _job()

    class FakePublisher:
        def publish(self, message, topic=None):
            calls.append(
                (
                    "publish",
                    topic,
                    message["job_id"],
                    message.get("attempt"),
                    message.get("backoff_seconds"),
                    message.get("last_error"),
                )
            )

    with patch("app.workers.structured_standardizer.get_structured_job_repository", return_value=FakeRepo()), \
        patch("app.workers.structured_standardizer.RedisMinuteRateLimiter", return_value=FakeLimiter(False)), \
        patch("app.workers.structured_standardizer.get_structured_job_publisher", return_value=FakePublisher()):
        process_standardization_message({"job_id": "structured_test", "provider": "openrouter"})

    assert calls == [
        ("publish", "ocr.standardize.retry", "structured_test", 1, 60, "rate_limited"),
    ]


def test_worker_marks_failed_and_publishes_dlq_on_permanent_failure():
    calls = []

    class FakeRepo:
        def get_job(self, job_id):
            return _job()

        def mark_running(self, job_id):
            calls.append(("running", job_id))

        def mark_success(self, job_id, structured_json):
            calls.append(("success", job_id))

        def mark_failed(self, job_id, error):
            calls.append(("failed", job_id, error))

    class FakePublisher:
        def publish(self, message, topic=None):
            calls.append(("publish", topic, message["job_id"], message["error"]))

    with patch("app.workers.structured_standardizer.get_structured_job_repository", return_value=FakeRepo()), \
        patch("app.workers.structured_standardizer.RedisMinuteRateLimiter", return_value=FakeLimiter()), \
        patch("app.workers.structured_standardizer.get_structured_job_publisher", return_value=FakePublisher()), \
        patch("app.workers.structured_standardizer.get_standardizer", return_value=PermanentFailureStandardizer()):
        process_standardization_message({"job_id": "structured_test", "provider": "openrouter"})

    assert calls == [
        ("running", "structured_test"),
        ("failed", "structured_test", "schema rejected"),
        ("publish", "ocr.standardize.dlq", "structured_test", "schema rejected"),
    ]
