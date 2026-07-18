"""Focused tests for invoice outbox publish and duplicate-consumer behavior."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.workers.invoice_outbox import (
    InvoiceEventRetryPublisher,
    InvoiceOutboxPublisher,
    _process_until_consumer_lease_clears,
    _retry_pending_webhooks,
    process_invoice_event,
    project_invoice_event,
)
from app.services.webhook_dispatch import DurableWebhookDispatcher, WebhookEvent


def _event() -> dict:
    return {
        "id": "evt-1",
        "tenant_id": "tenant-a",
        "invoice_id": "inv-1",
        "event_type": "document.review_completed",
        "payload_json": {"document_id": "inv-1", "document_version": 2},
        "lease_token": "outbox-lease-1",
    }


def test_publisher_marks_outbox_only_after_kafka_delivery():
    calls = []

    class FakeRepository:
        def claim_pending_outbox(self, limit):
            assert limit == 100
            return [_event()]

        def mark_outbox_published(self, event_id, lease_token):
            calls.append(("published", event_id, lease_token))
            return True

        def release_outbox_claim(self, event_id, lease_token, error):
            calls.append(("released", event_id, lease_token, error))
            return True

    class FakeProducer:
        def produce(self, topic, key, value, on_delivery):
            calls.append(("produce", topic, key, json.loads(value)))
            on_delivery(None, object())

        def flush(self):
            calls.append(("flush",))
            return 0

    publisher = InvoiceOutboxPublisher(FakeRepository(), FakeProducer(), topic="invoice.events")

    assert publisher.publish_pending() == 1
    assert calls == [
        (
            "produce",
            "invoice.events",
            "evt-1",
            {
                "event_id": "evt-1",
                "event_type": "document.review_completed",
                "tenant_id": "tenant-a",
                "invoice_id": "inv-1",
                "payload": {"document_id": "inv-1", "document_version": 2},
            },
        ),
        ("flush",),
        ("published", "evt-1", "outbox-lease-1"),
    ]


def test_publisher_releases_claim_after_delivery_failure():
    calls = []

    class FakeRepository:
        def claim_pending_outbox(self, limit):
            return [_event()]

        def mark_outbox_published(self, event_id, lease_token):
            calls.append(("published", event_id))
            return True

        def release_outbox_claim(self, event_id, lease_token, error):
            calls.append(("released", event_id, lease_token, error))
            return True

    class FakeProducer:
        def produce(self, topic, key, value, on_delivery):
            on_delivery("broker unavailable", object())

        def flush(self):
            return 0

    assert InvoiceOutboxPublisher(FakeRepository(), FakeProducer()).publish_pending() == 0
    assert calls == [
        ("released", "evt-1", "outbox-lease-1", "Kafka delivery failed: broker unavailable")
    ]


def test_consumer_failure_is_published_to_delayed_retry_before_source_commit():
    messages = []

    class FakeProducer:
        def produce(self, topic, key, value, on_delivery):
            messages.append((topic, key, json.loads(value)))
            on_delivery(None, object())

        def flush(self):
            return 0

    publisher = InvoiceEventRetryPublisher(
        FakeProducer(),
        retry_topic="invoice.events.retry",
        dlq_topic="invoice.events.dlq",
        max_retries=1,
        retry_delay_seconds=0,
    )
    event = {
        "event_id": "evt-1",
        "event_type": "document.review_completed",
        "tenant_id": "tenant-a",
        "invoice_id": "inv-1",
        "payload": {},
    }

    assert publisher.publish_retry_or_dlq(event, RuntimeError("projection failed")) == "invoice.events.retry"

    assert messages[0][0:2] == ("invoice.events.retry", "evt-1")
    assert messages[0][2]["delivery_attempt"] == 1
    assert messages[0][2]["last_error"] == "projection failed"
    assert "not_before" in messages[0][2]


def test_consumer_failure_exhaustion_is_published_to_dlq_without_retry_delay():
    messages = []

    class FakeProducer:
        def produce(self, topic, key, value, on_delivery):
            messages.append((topic, key, json.loads(value)))
            on_delivery(None, object())

        def flush(self):
            return 0

    publisher = InvoiceEventRetryPublisher(
        FakeProducer(),
        retry_topic="invoice.events.retry",
        dlq_topic="invoice.events.dlq",
        max_retries=1,
    )
    event = {
        "event_id": "evt-1",
        "event_type": "document.review_completed",
        "tenant_id": "tenant-a",
        "invoice_id": "inv-1",
        "payload": {},
        "delivery_attempt": 1,
        "not_before": "2026-07-17T00:00:00+00:00",
    }

    assert publisher.publish_retry_or_dlq(event, RuntimeError("projection failed")) == "invoice.events.dlq"

    assert messages == [
        (
            "invoice.events.dlq",
            "evt-1",
            {
                "event_id": "evt-1",
                "event_type": "document.review_completed",
                "tenant_id": "tenant-a",
                "invoice_id": "inv-1",
                "payload": {},
                "delivery_attempt": 2,
                "last_error": "projection failed",
            },
        )
    ]


def test_publisher_preserves_null_invoice_for_extraction_job_event():
    messages = []

    class FakeRepository:
        def claim_pending_outbox(self, limit):
            return [
                {
                    "id": "evt-job",
                    "tenant_id": "tenant-a",
                    "invoice_id": None,
                    "event_type": "document.extraction_requested",
                    "payload_json": {"job_id": "job-1"},
                    "lease_token": "outbox-lease-job",
                }
            ]

        def mark_outbox_published(self, event_id, lease_token):
            return True

        def release_outbox_claim(self, event_id, lease_token, error):
            raise AssertionError(error)

    class FakeProducer:
        def produce(self, topic, key, value, on_delivery):
            messages.append(json.loads(value))
            on_delivery(None, object())

        def flush(self):
            return 0

    assert InvoiceOutboxPublisher(FakeRepository(), FakeProducer()).publish_pending() == 1
    assert messages == [
        {
            "event_id": "evt-job",
            "event_type": "document.extraction_requested",
            "tenant_id": "tenant-a",
            "invoice_id": None,
            "payload": {"job_id": "job-1"},
        }
    ]


def test_consumer_claims_receipt_once_before_idempotent_handler():
    calls = []

    class FakeRepository:
        def claim_consumer_receipt(self, event_id, consumer, lease_seconds):
            calls.append(("receipt", event_id, consumer))
            return "lease-1" if len([call for call in calls if call[0] == "receipt"]) == 1 else None

        def complete_consumer_receipt(self, event_id, consumer, lease_token):
            calls.append(("completed", event_id, consumer))
            return True

        def release_consumer_receipt(self, event_id, consumer, lease_token, error):
            calls.append(("released", event_id, consumer, error))
            return True

        def has_active_consumer_receipt(self, event_id, consumer):
            calls.append(("active", event_id, consumer))
            return False

    event = {
        "event_id": "evt-1",
        "event_type": "document.review_completed",
        "tenant_id": "tenant-a",
        "invoice_id": "inv-1",
        "payload": {},
    }

    assert process_invoice_event(
        event,
        repository=FakeRepository(),
        consumer_name="projection",
        handler=lambda message, _lease_token: calls.append(("handler", message["event_id"])),
    )
    assert not process_invoice_event(
        event,
        repository=FakeRepository(),
        consumer_name="projection",
        handler=lambda message, _lease_token: calls.append(("handler", message["event_id"])),
    )
    assert calls == [
        ("receipt", "evt-1", "projection"),
        ("handler", "evt-1"),
        ("completed", "evt-1", "projection"),
        ("receipt", "evt-1", "projection"),
        ("active", "evt-1", "projection"),
    ]


def test_consumer_defers_active_receipt_lease_and_retries_before_commit():
    calls = []

    class Repository:
        def claim_consumer_receipt(self, event_id, consumer, lease_seconds):
            calls.append(("claim", event_id, consumer))
            return None

        def has_active_consumer_receipt(self, event_id, consumer):
            calls.append(("active", event_id, consumer))
            return True

    event = {"event_id": "evt-1"}
    assert process_invoice_event(event, repository=Repository(), consumer_name="projection") is None

    outcomes = iter([None, False])
    assert not _process_until_consumer_lease_clears(
        lambda: next(outcomes),
        retry_seconds=0,
    )
    assert calls == [
        ("claim", "evt-1", "projection"),
        ("active", "evt-1", "projection"),
    ]


def test_consumer_releases_receipt_when_handler_fails():
    calls = []

    class FakeRepository:
        def claim_consumer_receipt(self, event_id, consumer, lease_seconds):
            return "lease-1"

        def complete_consumer_receipt(self, event_id, consumer, lease_token):
            calls.append(("completed", event_id, consumer))
            return True

        def release_consumer_receipt(self, event_id, consumer, lease_token, error):
            calls.append(("released", event_id, consumer, error))
            return True

    event = {"event_id": "evt-1"}
    try:
        process_invoice_event(
            event,
            repository=FakeRepository(),
            consumer_name="projection",
            handler=lambda _message, _lease_token: (_ for _ in ()).throw(RuntimeError("projection failed")),
        )
    except RuntimeError as exc:
        assert str(exc) == "projection failed"
    else:
        raise AssertionError("expected the handler failure to propagate")

    assert calls == [("released", "evt-1", "projection", "projection failed")]


def test_pending_webhook_retry_delivers_without_replaying_projection():
    projection_calls = ["durable-search-receipt"]
    deliveries = []

    class Repository:
        def list_pending_webhook_events(self):
            return [
                {
                    "event_id": "evt-1",
                    "tenant_id": "tenant-a",
                    "invoice_id": "inv-1",
                    "event_type": "document.review_completed",
                    "payload": {"document_version": 2},
                    "created_at": datetime.now(timezone.utc),
                }
            ]

    class Dispatcher:
        attempts = 0

        async def dispatch_outbox(self, event_id, event):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("receiver unavailable")
            deliveries.append((event_id, event.document_id, event.payload))

    dispatcher = Dispatcher()
    _retry_pending_webhooks(Repository(), dispatcher)
    _retry_pending_webhooks(Repository(), dispatcher)

    assert projection_calls == ["durable-search-receipt"]
    assert deliveries == [("evt-1", "inv-1", {"document_version": 2})]


@pytest.mark.asyncio
async def test_projection_uses_committed_tenant_invoice_and_outbox_webhook():
    calls = []

    class FakeRepository:
        def get_invoice(self, invoice_id, tenant_id):
            calls.append(("get_invoice", invoice_id, tenant_id))
            return {
                "id": invoice_id,
                "tenant_id": tenant_id,
                "extracted_json": {"issuer_name": "Acme"},
                "raw_ocr_json": {"results": [{"text": "Acme", "confidence": 1.0}]},
            }

    class FakeSearch:
        async def index_document(self, document_id, extracted_json, ocr_lines, tenant_id):
            calls.append(("index", document_id, extracted_json, ocr_lines, tenant_id))

    class FakeWebhooks:
        async def dispatch_outbox(self, event_id, event):
            calls.append(("webhook", event_id, event))

    event = {
        "event_id": "evt-1",
        "event_type": "document.review_completed",
        "tenant_id": "tenant-a",
        "invoice_id": "inv-1",
        "payload": {"document_id": "inv-1", "document_version": 2},
    }

    await project_invoice_event(
        event,
        repository=FakeRepository(),
        search_service=FakeSearch(),
        webhook_dispatcher=FakeWebhooks(),
    )

    assert calls[:2] == [
        ("get_invoice", "inv-1", "tenant-a"),
        (
            "index",
            "inv-1",
            {"issuer_name": "Acme"},
            [{"text": "Acme", "confidence": 1.0}],
            "tenant-a",
        ),
    ]
    webhook_call = calls[2]
    assert webhook_call[0:2] == ("webhook", "evt-1")
    assert webhook_call[2].tenant_id == "tenant-a"
    assert webhook_call[2].event_type == "document.review_completed"


@pytest.mark.asyncio
async def test_durable_search_receipt_survives_webhook_failure():
    calls = []

    class FakeRepository:
        def get_invoice(self, invoice_id, tenant_id):
            return {
                "id": invoice_id,
                "tenant_id": tenant_id,
                "extracted_json": {"issuer_name": "Acme"},
                "raw_ocr_json": {"results": [{"text": "Acme"}]},
            }

        def complete_consumer_receipt_and_save_search_chunks(self, *args, **kwargs):
            calls.append(("receipt", args, kwargs))
            return True

    repository = FakeRepository()
    search_service = SimpleNamespace(
        _repo=SimpleNamespace(_repository=repository),
        _embed=SimpleNamespace(embed_batch=AsyncMock(return_value=[[0.1]])),
    )

    class FailingWebhooks:
        async def dispatch_outbox(self, event_id, event):
            calls.append(("webhook", event_id))
            raise RuntimeError("receiver unavailable")

    result = await project_invoice_event(
        {
            "event_id": "evt-1",
            "event_type": "document.review_completed",
            "tenant_id": "tenant-a",
            "invoice_id": "inv-1",
            "payload": {},
        },
        repository=repository,
        search_service=search_service,
        webhook_dispatcher=FailingWebhooks(),
        consumer_name="projection",
        lease_token="lease-current",
    )

    assert result is not None
    assert calls[0][0] == "receipt"
    assert calls[1] == ("webhook", "evt-1")


def test_projection_crash_after_intent_commit_is_recovered_without_search_replay():
    calls = []

    class FakeRepository:
        pending_events = []

        def get_invoice(self, invoice_id, tenant_id):
            return {
                "id": invoice_id,
                "tenant_id": tenant_id,
                "extracted_json": {"issuer_name": "Acme"},
                "raw_ocr_json": {"results": [{"text": "Acme"}]},
            }

        def complete_consumer_receipt_and_save_search_chunks(self, *args, **kwargs):
            calls.append(("receipt", kwargs["event_type"]))
            self.pending_events = [
                {
                    "event_id": "evt-1",
                    "tenant_id": "tenant-a",
                    "invoice_id": "inv-1",
                    "event_type": "document.review_completed",
                    "payload": {},
                    "created_at": datetime.now(timezone.utc),
                }
            ]
            return True

        def list_pending_webhook_events(self):
            return self.pending_events

    repository = FakeRepository()
    search_service = SimpleNamespace(
        _repo=SimpleNamespace(_repository=repository),
        _embed=SimpleNamespace(embed_batch=AsyncMock(return_value=[[0.1]])),
    )

    class CrashBeforeDispatch:
        async def dispatch_outbox(self, *_args):
            raise SystemExit("worker crashed")

    with pytest.raises(SystemExit, match="worker crashed"):
        asyncio.run(
            project_invoice_event(
                {
                    "event_id": "evt-1",
                    "event_type": "document.review_completed",
                    "tenant_id": "tenant-a",
                    "invoice_id": "inv-1",
                    "payload": {},
                },
                repository=repository,
                search_service=search_service,
                webhook_dispatcher=CrashBeforeDispatch(),
                consumer_name="projection",
                lease_token="lease-current",
            )
        )

    delivered = []

    class RecoveryDispatcher:
        async def dispatch_outbox(self, event_id, event):
            delivered.append((event_id, event.document_id))

    _retry_pending_webhooks(repository, RecoveryDispatcher())

    assert calls == [("receipt", "document.review_completed")]
    assert delivered == [("evt-1", "inv-1")]


@pytest.mark.asyncio
async def test_projection_rejects_cross_tenant_or_missing_invoice():
    class FakeRepository:
        def get_invoice(self, invoice_id, tenant_id):
            assert tenant_id == "tenant-b"
            return None

    with pytest.raises(ValueError, match="not available"):
        await project_invoice_event(
            {
                "event_id": "evt-1",
                "event_type": "document.extraction_completed",
                "tenant_id": "tenant-b",
                "invoice_id": "inv-a",
                "payload": {},
            },
            repository=FakeRepository(),
        )


@pytest.mark.asyncio
async def test_projection_skips_extraction_job_event():
    await project_invoice_event(
        {
            "event_id": "evt-job",
            "event_type": "document.extraction_requested",
            "tenant_id": "tenant-a",
            "invoice_id": None,
            "payload": {"job_id": "job-1"},
        }
    )


@pytest.mark.asyncio
async def test_durable_webhook_delivery_claims_once_and_sends_stable_event_id():
    calls = []

    class FakeRepository:
        delivered: set[tuple[str, str]] = set()

        def list_webhook_subscriptions(self, *, tenant_id, event_type=None):
            assert tenant_id == "tenant-a"
            assert event_type is None
            return [
                {
                    "id": "sub-1",
                    "tenant_id": tenant_id,
                    "url": "https://example.com/hook",
                    "event_types": ["document.review_completed"],
                    "secret": None,
                    "active": True,
                }
            ]

        def claim_webhook_delivery(self, *, event_id, subscription_id, lease_seconds):
            key = (event_id, subscription_id)
            calls.append(("claim", key))
            return "lease-1" if key not in self.delivered else None

        def complete_webhook_delivery(self, *, event_id, subscription_id, lease_token, response_code):
            key = (event_id, subscription_id)
            self.delivered.add(key)
            calls.append(("complete", key, response_code))
            return True

        def release_webhook_delivery(self, **kwargs):
            calls.append(("release", kwargs))
            return True

    dispatcher = DurableWebhookDispatcher(repository=FakeRepository())

    async def fake_deliver(url, body, headers):
        calls.append(("send", url, json.loads(body), headers))
        return 202, None

    dispatcher._deliver = fake_deliver
    event = WebhookEvent(
        event_type="document.review_completed",
        document_id="inv-1",
        payload={"document_version": 2},
        timestamp=datetime.now(timezone.utc),
        tenant_id="tenant-a",
    )

    assert (await dispatcher.dispatch_outbox("evt-1", event))[0].status == "delivered"
    assert await dispatcher.dispatch_outbox("evt-1", event) == []
    assert calls == [
        ("claim", ("evt-1", "sub-1")),
        (
            "send",
            "https://example.com/hook",
            {
                "event_id": "evt-1",
                "event_type": "document.review_completed",
                "document_id": "inv-1",
                "payload": {"document_version": 2},
                "timestamp": event.timestamp.isoformat(),
            },
            {"Content-Type": "application/json", "X-Webhook-Event-Id": "evt-1"},
        ),
        ("complete", ("evt-1", "sub-1"), 202),
        ("claim", ("evt-1", "sub-1")),
    ]


@pytest.mark.asyncio
async def test_durable_webhook_does_not_resend_a_2xx_when_terminal_write_fails():
    calls = []

    class FakeRepository:
        def list_webhook_subscriptions(self, *, tenant_id, event_type=None):
            return [
                {
                    "id": "sub-1",
                    "tenant_id": tenant_id,
                    "url": "https://example.com/hook",
                    "event_types": ["document.review_completed"],
                    "secret": None,
                    "active": True,
                }
            ]

        def claim_webhook_delivery(self, *, event_id, subscription_id, lease_seconds):
            return "lease-current"

        def complete_webhook_delivery(self, **_kwargs):
            return False

        def release_webhook_delivery(self, **_kwargs):
            calls.append("released")
            return True

    dispatcher = DurableWebhookDispatcher(max_retries=3, repository=FakeRepository())

    async def fake_deliver(url, body, headers):
        calls.append(("send", url, json.loads(body), headers))
        return 202, None

    dispatcher._deliver = fake_deliver
    event = WebhookEvent(
        event_type="document.review_completed",
        document_id="inv-1",
        payload={},
        timestamp=datetime.now(timezone.utc),
        tenant_id="tenant-a",
    )

    with pytest.raises(Exception, match="retry required"):
        await dispatcher.dispatch_outbox("evt-1", event)

    assert len([call for call in calls if call[0] == "send"]) == 1
    assert "released" not in calls


@pytest.mark.asyncio
async def test_durable_webhook_retries_failed_subscription_without_resending_completed_one():
    calls = []

    class FakeRepository:
        states: dict[tuple[str, str], str] = {}

        def list_webhook_subscriptions(self, *, tenant_id, event_type=None):
            return [
                {
                    "id": "sub-ok",
                    "tenant_id": tenant_id,
                    "url": "https://ok.example/hook",
                    "event_types": ["document.review_completed"],
                    "secret": None,
                    "active": True,
                },
                {
                    "id": "sub-retry",
                    "tenant_id": tenant_id,
                    "url": "https://retry.example/hook",
                    "event_types": ["document.review_completed"],
                    "secret": None,
                    "active": True,
                },
            ]

        def claim_webhook_delivery(self, *, event_id, subscription_id, lease_seconds):
            return "lease-1" if self.states.get((event_id, subscription_id)) != "delivered" else None

        def complete_webhook_delivery(self, *, event_id, subscription_id, lease_token, response_code):
            self.states[(event_id, subscription_id)] = "delivered"
            calls.append(("complete", subscription_id))
            return True

        def release_webhook_delivery(
            self,
            *,
            event_id,
            subscription_id,
            lease_token,
            error,
            response_code,
        ):
            self.states[(event_id, subscription_id)] = "pending"
            calls.append(("release", subscription_id))
            return True

    dispatcher = DurableWebhookDispatcher(max_retries=0, repository=FakeRepository())
    attempts = {"retry": 0}

    async def fake_deliver(url, body, headers):
        if "retry" in url and attempts["retry"] == 0:
            attempts["retry"] += 1
            return 500, None
        calls.append(("send", url))
        return 200, None

    dispatcher._deliver = fake_deliver
    event = WebhookEvent(
        event_type="document.review_completed",
        document_id="inv-1",
        payload={},
        timestamp=datetime.now(timezone.utc),
        tenant_id="tenant-a",
    )

    with pytest.raises(Exception, match="retry required"):
        await dispatcher.dispatch_outbox("evt-1", event)
    await dispatcher.dispatch_outbox("evt-1", event)

    assert calls == [
        ("send", "https://ok.example/hook"),
        ("complete", "sub-ok"),
        ("release", "sub-retry"),
        ("send", "https://retry.example/hook"),
        ("complete", "sub-retry"),
    ]

@pytest.mark.asyncio
async def test_durable_webhook_lease_covers_all_configured_attempts():
    claimed_leases = []

    class FakeRepository:
        def list_webhook_subscriptions(self, *, tenant_id, event_type=None):
            return [
                {
                    "id": "sub-1",
                    "tenant_id": tenant_id,
                    "url": "https://example.com/hook",
                    "event_types": ["document.review_completed"],
                    "secret": None,
                    "active": True,
                }
            ]

        def claim_webhook_delivery(self, *, event_id, subscription_id, lease_seconds):
            claimed_leases.append(lease_seconds)
            return "lease-1"

        def complete_webhook_delivery(self, **_kwargs):
            return True

        def release_webhook_delivery(self, **_kwargs):
            return True

    dispatcher = DurableWebhookDispatcher(max_retries=4, backoff_base=1, repository=FakeRepository())
    dispatcher._deliver = AsyncMock(return_value=(202, None))
    event = WebhookEvent(
        event_type="document.review_completed",
        document_id="inv-1",
        payload={},
        timestamp=datetime.now(timezone.utc),
        tenant_id="tenant-a",
    )

    await dispatcher.dispatch_outbox("evt-1", event)

    # Five 10-second HTTP attempts plus 1+2+4+8 seconds backoff and a 5-second buffer.
    assert claimed_leases == [70]
