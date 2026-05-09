"""Kafka publishing for structured OCR standardization jobs."""

import json
from typing import Any

from app.config import get_settings


class StructuredJobPublisher:
    def __init__(self, bootstrap_servers: str | None = None, topic: str | None = None) -> None:
        settings = get_settings()
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS
        self.topic = topic or settings.STRUCTURED_STANDARDIZE_TOPIC

    def publish(self, message: dict[str, Any], topic: str | None = None) -> None:
        from confluent_kafka import Producer

        producer = Producer({"bootstrap.servers": self.bootstrap_servers})
        producer.produce(
            topic or self.topic,
            key=str(message["job_id"]),
            value=json.dumps(message).encode("utf-8"),
        )
        producer.flush()


_structured_job_publisher: StructuredJobPublisher | None = None


def get_structured_job_publisher() -> StructuredJobPublisher:
    global _structured_job_publisher
    if _structured_job_publisher is None:
        _structured_job_publisher = StructuredJobPublisher()
    return _structured_job_publisher
