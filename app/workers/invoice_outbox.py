"""Transactional invoice outbox publisher and idempotent Kafka consumer."""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings
from app.repositories.invoice_repository import get_invoice_repository
from app.services.search.chunker import chunk_document
from app.services.search.factory import build_search_service
from app.services.webhook_dispatch import WebhookEvent, get_webhook_dispatcher

logger = logging.getLogger(__name__)

_SEARCH_EVENT_TYPES = {
    "document.extraction_completed",
    "document.fields_patched",
    "document.review_completed",
}
_PROJECTION_LEASE_SECONDS = 120
_RECEIPT_COMPLETED = object()
_RETRY_ATTEMPT_KEY = "delivery_attempt"
_RETRY_NOT_BEFORE_KEY = "not_before"
_RETRY_ERROR_KEY = "last_error"


def _event_envelope(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload_json") or {}
    if not isinstance(payload, dict):
        raise ValueError("outbox payload_json must be an object")
    envelope = {
        "event_id": str(event["id"]),
        "event_type": str(event["event_type"]),
        "tenant_id": str(event["tenant_id"]),
        "invoice_id": str(event["invoice_id"]) if event.get("invoice_id") is not None else None,
        "payload": payload,
    }
    if isinstance(event.get(_RETRY_ATTEMPT_KEY), int) and event[_RETRY_ATTEMPT_KEY] > 0:
        envelope[_RETRY_ATTEMPT_KEY] = event[_RETRY_ATTEMPT_KEY]
    if isinstance(event.get(_RETRY_NOT_BEFORE_KEY), str):
        envelope[_RETRY_NOT_BEFORE_KEY] = event[_RETRY_NOT_BEFORE_KEY]
    if isinstance(event.get(_RETRY_ERROR_KEY), str):
        envelope[_RETRY_ERROR_KEY] = event[_RETRY_ERROR_KEY]
    return envelope


def _retry_attempt(event: dict[str, Any]) -> int:
    value = event.get(_RETRY_ATTEMPT_KEY, 0)
    return value if isinstance(value, int) and value >= 0 else 0


def _wait_until_retry_due(event: dict[str, Any]) -> None:
    value = event.get(_RETRY_NOT_BEFORE_KEY)
    if not isinstance(value, str):
        return
    try:
        due_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Ignoring malformed invoice retry deadline for event %s", event.get("event_id"))
        return
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    delay = (due_at - datetime.now(timezone.utc)).total_seconds()
    if delay > 0:
        time.sleep(delay)


class InvoiceOutboxPublisher:
    """Publish claimed outbox rows, marking delivery only after Kafka confirms it."""

    def __init__(
        self,
        repository: Any | None = None,
        producer: Any | None = None,
        topic: str | None = None,
    ) -> None:
        settings = get_settings()
        self.repository = repository or get_invoice_repository()
        self.topic = topic or settings.INVOICE_OUTBOX_TOPIC
        self.batch_size = settings.INVOICE_OUTBOX_BATCH_SIZE
        if producer is None:
            from confluent_kafka import Producer

            producer = Producer({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
        self._producer = producer

    def _publish(self, event: dict[str, Any]) -> None:
        delivery_error: list[str] = []
        envelope = _event_envelope(event)

        def on_delivery(error: Any, _message: Any) -> None:
            if error is not None:
                delivery_error.append(str(error))

        self._producer.produce(
            self.topic,
            key=envelope["event_id"],
            value=json.dumps(envelope, default=str).encode("utf-8"),
            on_delivery=on_delivery,
        )
        remaining = self._producer.flush()
        if remaining:
            raise TimeoutError(f"Kafka delivery incomplete: {remaining} message(s) pending")
        if delivery_error:
            raise RuntimeError(f"Kafka delivery failed: {delivery_error[0]}")

    def publish_pending(self) -> int:
        """Drain one claimed batch. Failed rows are released for retry."""
        published = 0
        for event in self.repository.claim_pending_outbox(limit=self.batch_size):
            event_id = str(event["id"])
            lease_token = event.get("lease_token")
            if not isinstance(lease_token, str) or not lease_token:
                logger.error("Claimed invoice outbox row %s has no lease token", event_id)
                continue
            try:
                self._publish(event)
                if not self.repository.mark_outbox_published(event_id, lease_token):
                    raise RuntimeError("outbox row could not be marked published")
                published += 1
            except Exception as exc:
                logger.exception("Invoice outbox publish failed for %s", event_id)
                self.repository.release_outbox_claim(event_id, lease_token, str(exc))
        return published


class InvoiceEventRetryPublisher:
    """Publish a failed consumer envelope to the delayed retry topic or terminal DLQ."""

    def __init__(
        self,
        producer: Any | None = None,
        *,
        retry_topic: str | None = None,
        dlq_topic: str | None = None,
        max_retries: int | None = None,
        retry_delay_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self.retry_topic = retry_topic or settings.INVOICE_OUTBOX_RETRY_TOPIC
        self.dlq_topic = dlq_topic or settings.INVOICE_OUTBOX_DLQ_TOPIC
        self.max_retries = max(0, settings.INVOICE_OUTBOX_MAX_RETRIES if max_retries is None else max_retries)
        self.retry_delay_seconds = max(
            0.0,
            settings.INVOICE_OUTBOX_RETRY_DELAY_SECONDS
            if retry_delay_seconds is None
            else retry_delay_seconds,
        )
        if producer is None:
            from confluent_kafka import Producer

            producer = Producer({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
        self._producer = producer

    def publish_retry_or_dlq(self, event: dict[str, Any], error: Exception) -> str:
        """Persist retry metadata in Kafka before the source record is committed."""
        attempt = _retry_attempt(event) + 1
        target_topic = self.dlq_topic if attempt > self.max_retries else self.retry_topic
        envelope = {
            **event,
            _RETRY_ATTEMPT_KEY: attempt,
            _RETRY_ERROR_KEY: str(error)[:2000],
        }
        if target_topic == self.retry_topic:
            envelope[_RETRY_NOT_BEFORE_KEY] = (
                datetime.now(timezone.utc)
                + timedelta(seconds=self.retry_delay_seconds)
            ).isoformat()
        else:
            envelope.pop(_RETRY_NOT_BEFORE_KEY, None)

        delivery_error: list[str] = []

        def on_delivery(delivery_error_value: Any, _message: Any) -> None:
            if delivery_error_value is not None:
                delivery_error.append(str(delivery_error_value))

        event_id = envelope.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("event_id is required for retry or DLQ publication")
        self._producer.produce(
            target_topic,
            key=event_id,
            value=json.dumps(envelope, default=str).encode("utf-8"),
            on_delivery=on_delivery,
        )
        remaining = self._producer.flush()
        if remaining:
            raise TimeoutError(f"Kafka retry delivery incomplete: {remaining} message(s) pending")
        if delivery_error:
            raise RuntimeError(f"Kafka retry delivery failed: {delivery_error[0]}")
        return target_topic


def process_invoice_event(
    event: dict[str, Any],
    repository: Any | None = None,
    consumer_name: str | None = None,
    handler: Callable[[dict[str, Any], str], object] | None = None,
) -> bool:
    """Run a retry-safe, idempotent local projection for one Kafka event."""
    settings = get_settings()
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("event_id is required")

    repository = repository or get_invoice_repository()
    consumer_name = consumer_name or settings.INVOICE_OUTBOX_CONSUMER_GROUP
    lease_token = repository.claim_consumer_receipt(
        event_id,
        consumer_name,
        lease_seconds=_PROJECTION_LEASE_SECONDS,
    )
    if lease_token is None:
        if repository.has_active_consumer_receipt(event_id, consumer_name):
            logger.info("Deferring invoice event %s while another consumer lease is active", event_id)
            return None
        logger.info("Ignoring duplicate invoice event %s", event_id)
        return False

    try:
        if handler is not None:
            if handler(event, lease_token) is _RECEIPT_COMPLETED:
                return True
        if not repository.complete_consumer_receipt(event_id, consumer_name, lease_token):
            raise RuntimeError("consumer receipt could not be completed")
    except Exception as exc:
        repository.release_consumer_receipt(event_id, consumer_name, lease_token, str(exc))
        raise
    return True


def _process_until_consumer_lease_clears(
    process: Callable[[], bool | None],
    *,
    retry_seconds: float,
) -> bool:
    """Keep the current Kafka record uncommitted while its effect is leased elsewhere."""
    result = process()
    while result is None:
        time.sleep(retry_seconds)
        result = process()
    return result


def _retry_pending_webhooks(repository: Any, webhook_dispatcher: Any) -> None:
    """Retry durable webhook deliveries without replaying search projection effects."""
    dispatch_outbox = getattr(webhook_dispatcher, "dispatch_outbox", None)
    if dispatch_outbox is None:
        return
    for event in repository.list_pending_webhook_events():
        created_at = event.get("created_at")
        timestamp = created_at if isinstance(created_at, datetime) else datetime.now(timezone.utc)
        try:
            asyncio.run(
                dispatch_outbox(
                    event["event_id"],
                    WebhookEvent(
                        event_type=event["event_type"],
                        document_id=event["invoice_id"],
                        payload=event.get("payload") or {},
                        timestamp=timestamp,
                        tenant_id=event["tenant_id"],
                    ),
                )
            )
        except Exception:
            logger.exception("Pending webhook retry failed for invoice event %s", event["event_id"])


async def project_invoice_event(
    event: dict[str, Any],
    repository: Any | None = None,
    search_service: Any | None = None,
    webhook_dispatcher: Any | None = None,
    consumer_name: str | None = None,
    lease_token: str | None = None,
) -> object | None:
    """Build durable tenant-scoped search and webhook effects from one event."""
    if event.get("event_type") == "document.extraction_requested":
        return

    invoice_id = event.get("invoice_id")
    tenant_id = event.get("tenant_id")
    event_id = event.get("event_id")
    if not all(isinstance(value, str) and value for value in (invoice_id, tenant_id, event_id)):
        raise ValueError("event_id, invoice_id, and tenant_id are required")

    repository = repository or get_invoice_repository()
    invoice = repository.get_invoice(invoice_id, tenant_id)
    if invoice is None:
        raise ValueError(f"invoice {invoice_id} is not available for tenant {tenant_id}")

    durable_search_chunks: list[dict] | None = None
    if event.get("event_type") in _SEARCH_EVENT_TYPES:
        search_service = search_service or build_search_service()
        raw_ocr = invoice.get("raw_ocr_json") or {}
        durable_search_repository = getattr(getattr(search_service, "_repo", None), "_repository", None)
        if (
            consumer_name is not None
            and lease_token is not None
            and durable_search_repository is repository
            and hasattr(repository, "complete_consumer_receipt_and_save_search_chunks")
        ):
            chunks = chunk_document(
                invoice_id,
                invoice.get("extracted_json") or {},
                raw_ocr.get("results") if isinstance(raw_ocr, dict) else None,
            )
            for chunk in chunks:
                chunk.metadata["tenant_id"] = tenant_id
            embeddings = await search_service._embed.embed_batch([chunk.text for chunk in chunks])
            for chunk, embedding in zip(chunks, embeddings):
                chunk.embedding = embedding
            durable_search_chunks = [
                {
                    "content": chunk.text,
                    "metadata": {
                        **chunk.metadata,
                        "_chunk_id": chunk.chunk_id,
                        "_chunk_type": chunk.chunk_type,
                        "_embedding": chunk.embedding,
                    },
                }
                for chunk in chunks
            ]
        else:
            await search_service.index_document(
                invoice_id,
                invoice.get("extracted_json") or {},
                ocr_lines=raw_ocr.get("results") if isinstance(raw_ocr, dict) else None,
                tenant_id=tenant_id,
            )

    receipt_completed = False
    if durable_search_chunks is not None:
        if not repository.complete_consumer_receipt_and_save_search_chunks(
            event_id,
            consumer_name,
            lease_token,
            invoice_id=invoice_id,
            tenant_id=tenant_id,
            event_type=event["event_type"],
            chunks=durable_search_chunks,
        ):
            raise RuntimeError("consumer receipt could not be completed with search projection")
        receipt_completed = True

    webhook_dispatcher = webhook_dispatcher or get_webhook_dispatcher()
    webhook_event = WebhookEvent(
        event_type=event["event_type"],
        document_id=invoice_id,
        payload=event.get("payload") or {},
        timestamp=datetime.now(timezone.utc),
        tenant_id=tenant_id,
    )
    dispatch_outbox = getattr(webhook_dispatcher, "dispatch_outbox", None)
    try:
        if dispatch_outbox is not None:
            await dispatch_outbox(event_id, webhook_event)
        else:
            await webhook_dispatcher.dispatch_or_raise(webhook_event)
    except Exception:
        if not receipt_completed:
            raise
        logger.exception(
            "Webhook dispatch failed after durable search projection for invoice event %s",
            event_id,
        )
    if receipt_completed:
        return _RECEIPT_COMPLETED
    return None


def run_worker() -> None:
    """Publish database intents then consume the resulting durable event stream."""
    from confluent_kafka import Consumer

    settings = get_settings()
    publisher = InvoiceOutboxPublisher()
    retry_publisher = InvoiceEventRetryPublisher()
    repository = get_invoice_repository()
    webhook_dispatcher = get_webhook_dispatcher()
    consumer = Consumer(
        {
            "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "group.id": settings.INVOICE_OUTBOX_CONSUMER_GROUP,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([settings.INVOICE_OUTBOX_TOPIC, settings.INVOICE_OUTBOX_RETRY_TOPIC])
    try:
        while True:
            publisher.publish_pending()
            _retry_pending_webhooks(repository, webhook_dispatcher)
            kafka_message = consumer.poll(settings.INVOICE_OUTBOX_POLL_SECONDS)
            if kafka_message is None:
                continue
            if kafka_message.error():
                logger.error("Kafka consumer error: %s", kafka_message.error())
                continue
            event = json.loads(kafka_message.value().decode("utf-8"))
            _wait_until_retry_due(event)
            try:
                _process_until_consumer_lease_clears(
                    lambda: process_invoice_event(
                        event,
                        repository=repository,
                        consumer_name=settings.INVOICE_OUTBOX_CONSUMER_GROUP,
                        handler=lambda payload, lease_token: asyncio.run(
                            project_invoice_event(
                                payload,
                                repository=repository,
                                consumer_name=settings.INVOICE_OUTBOX_CONSUMER_GROUP,
                                lease_token=lease_token,
                            )
                        )
                    ),
                    retry_seconds=max(0.1, settings.INVOICE_OUTBOX_POLL_SECONDS),
                )
            except Exception as exc:
                target_topic = retry_publisher.publish_retry_or_dlq(event, exc)
                logger.warning(
                    "Invoice event %s moved to %s after attempt %s",
                    event.get("event_id"),
                    target_topic,
                    _retry_attempt(event) + 1,
                )
            consumer.commit(kafka_message)
    finally:
        consumer.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            run_worker()
        except Exception as exc:
            logger.exception("Invoice outbox worker crashed: %s", exc)
            time.sleep(5)
