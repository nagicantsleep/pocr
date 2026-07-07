from __future__ import annotations

import pytest
from datetime import datetime, timezone

from app.services.webhook_dispatch import (
    DeliveryResult,
    WebhookDispatcher,
    WebhookEvent,
    WebhookSubscription,
)


@pytest.fixture
def dispatcher():
    return WebhookDispatcher()


# --- subscribe ---


def test_subscribe_returns_subscription(dispatcher):
    sub = dispatcher.subscribe(url="https://example.com/hook", events=["document.created"])
    assert isinstance(sub, WebhookSubscription)
    assert sub.id  # non-empty uuid
    assert sub.url == "https://example.com/hook"
    assert sub.events == ["document.created"]
    assert sub.active is True
    assert sub.secret is None


def test_subscribe_with_secret(dispatcher):
    sub = dispatcher.subscribe(
        url="https://example.com/hook",
        events=["document.created"],
        secret="s3cret",
    )
    assert sub.secret == "s3cret"


# --- list_subscriptions ---


def test_list_subscriptions_returns_all(dispatcher):
    dispatcher.subscribe(url="https://a.com/hook", events=["document.created"])
    dispatcher.subscribe(url="https://b.com/hook", events=["document.review_completed"])

    subs = dispatcher.list_subscriptions()
    assert len(subs) == 2


def test_list_subscriptions_empty(dispatcher):
    assert dispatcher.list_subscriptions() == []


# --- unsubscribe ---


def test_unsubscribe_removes_subscription(dispatcher):
    sub = dispatcher.subscribe(url="https://a.com/hook", events=["document.created"])
    assert len(dispatcher.list_subscriptions()) == 1

    result = dispatcher.unsubscribe(sub.id)
    assert result is True
    assert len(dispatcher.list_subscriptions()) == 0


def test_unsubscribe_nonexistent_returns_false(dispatcher):
    result = dispatcher.unsubscribe("nonexistent-id")
    assert result is False


# --- dispatch ---


@pytest.mark.asyncio
async def test_dispatch_matching_event_returns_delivery(dispatcher):
    sub = dispatcher.subscribe(
        url="https://example.com/hook",
        events=["document.created", "document.review_completed"],
    )

    event = WebhookEvent(
        event_type="document.created",
        document_id="doc-1",
        payload={"vendor": "Acme"},
        timestamp=datetime.now(timezone.utc),
    )
    results = await dispatcher.dispatch(event)

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, DeliveryResult)
    assert r.subscription_id == sub.id
    assert r.url == "https://example.com/hook"
    assert r.status == "pending"
    assert r.event_type == "document.created"


@pytest.mark.asyncio
async def test_dispatch_no_matching_subscriptions_returns_empty(dispatcher):
    dispatcher.subscribe(url="https://a.com/hook", events=["document.created"])

    event = WebhookEvent(
        event_type="document.review_completed",
        document_id="doc-1",
        payload={},
        timestamp=datetime.now(timezone.utc),
    )
    results = await dispatcher.dispatch(event)
    assert results == []


@pytest.mark.asyncio
async def test_dispatch_skips_inactive_subscriptions(dispatcher):
    sub = dispatcher.subscribe(url="https://a.com/hook", events=["document.created"])
    sub.active = False

    event = WebhookEvent(
        event_type="document.created",
        document_id="doc-1",
        payload={},
        timestamp=datetime.now(timezone.utc),
    )
    results = await dispatcher.dispatch(event)
    assert results == []


@pytest.mark.asyncio
async def test_dispatch_multiple_subscribers(dispatcher):
    dispatcher.subscribe(url="https://a.com/hook", events=["document.created"])
    dispatcher.subscribe(url="https://b.com/hook", events=["document.created", "document.approved"])
    dispatcher.subscribe(url="https://c.com/hook", events=["document.approved"])

    event = WebhookEvent(
        event_type="document.created",
        document_id="doc-1",
        payload={},
        timestamp=datetime.now(timezone.utc),
    )
    results = await dispatcher.dispatch(event)
    assert len(results) == 2
    urls = {r.url for r in results}
    assert urls == {"https://a.com/hook", "https://b.com/hook"}
