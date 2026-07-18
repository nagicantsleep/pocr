from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.webhook_dispatch import (
    DeliveryResult,
    WebhookDeliveryError,
    WebhookDispatcher,
    WebhookEvent,
    WebhookSubscription,
    WebhookURLError,
    get_webhook_dispatcher,
)


@pytest.fixture
def dispatcher():
    return WebhookDispatcher()


@pytest.fixture
def dispatcher_with_allowlist():
    return WebhookDispatcher(allowed_hosts=["allowed.example.com"])


def _make_event(event_type: str = "document.created") -> WebhookEvent:
    return WebhookEvent(
        event_type=event_type,
        document_id="doc-1",
        payload={"vendor": "Acme"},
        timestamp=datetime.now(timezone.utc),
    )


# --- subscribe ---


def test_subscribe_returns_subscription(dispatcher):
    sub = dispatcher.subscribe(url="https://example.com/hook", events=["document.created"])
    assert isinstance(sub, WebhookSubscription)
    assert sub.id
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


def test_subscribe_rejects_http(dispatcher):
    from app.services.webhook_dispatch import WebhookURLError
    with pytest.raises(WebhookURLError, match="https"):
        dispatcher.subscribe(url="http://example.com/hook", events=["x"])


def test_subscribe_rejects_empty_url(dispatcher):
    from app.services.webhook_dispatch import WebhookURLError
    with pytest.raises(WebhookURLError, match="non-empty"):
        dispatcher.subscribe(url="", events=["x"])


def test_subscribe_enforces_allowlist(dispatcher_with_allowlist):
    from app.services.webhook_dispatch import WebhookURLError
    with pytest.raises(WebhookURLError, match="not in"):
        dispatcher_with_allowlist.subscribe(
            url="https://evil.example.com/hook", events=["x"],
        )
    sub = dispatcher_with_allowlist.subscribe(
        url="https://allowed.example.com/hook", events=["x"],
    )
    assert sub.url.endswith("/hook")


def test_subscribe_rejects_empty_application_allowlist():
    dispatcher = WebhookDispatcher(allowed_hosts=[])
    with pytest.raises(WebhookURLError, match="must be configured"):
        dispatcher.subscribe(url="https://example.com/hook", events=["x"])


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


@pytest.mark.asyncio
async def test_api_subscription_persists_and_receives_delivery():
    dispatcher = get_webhook_dispatcher()
    previous_allowlist = dispatcher._allowed_hosts
    dispatcher._subscriptions.clear()
    dispatcher._allowed_hosts = ["example.com"]
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": ["document.created"],
            },
        )
        assert response.status_code == 201
        assert client.get("/v1/webhooks").json()["subscriptions"] == [response.json()]

        delivered = MagicMock(status_code=200)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=delivered) as post:
            results = await dispatcher.dispatch(_make_event())

        assert results[0].status == "delivered"
        post.assert_awaited_once()
    finally:
        dispatcher._subscriptions.clear()
        dispatcher._allowed_hosts = previous_allowlist


# --- dispatch: HTTP delivery ---


@pytest.mark.asyncio
async def test_dispatch_makes_http_post(dispatcher):
    sub = dispatcher.subscribe(url="https://example.com/hook", events=["document.created"])

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        results = await dispatcher.dispatch(_make_event())

    assert len(results) == 1
    r = results[0]
    assert r.subscription_id == sub.id
    assert r.url == "https://example.com/hook"
    assert r.status == "delivered"
    assert r.status_code == 200
    assert r.error is None
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args[0][0] == "https://example.com/hook"


@pytest.mark.asyncio
async def test_dispatch_retries_then_succeeds(dispatcher):
    """Fail twice (500, 500), then succeed (200) on the third attempt."""
    dispatcher.subscribe(url="https://example.com/hook", events=["document.created"])

    fail_response = MagicMock()
    fail_response.status_code = 500

    ok_response = MagicMock()
    ok_response.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[fail_response, fail_response, ok_response]) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        results = await dispatcher.dispatch(_make_event())

    assert len(results) == 1
    r = results[0]
    assert r.status == "delivered"
    assert r.status_code == 200
    assert mock_post.call_count == 3


@pytest.mark.asyncio
async def test_dispatch_max_retries_exhausted_returns_failed(dispatcher):
    """All attempts return 500 -- final status is 'failed'."""
    dispatcher.subscribe(url="https://example.com/hook", events=["document.created"])

    fail_response = MagicMock()
    fail_response.status_code = 500

    dispatcher_retry = WebhookDispatcher(max_retries=2)  # 1 initial + 2 retries = 3 total
    dispatcher_retry.subscribe(url="https://example.com/hook", events=["document.created"])

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=fail_response) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        results = await dispatcher_retry.dispatch(_make_event())

    assert len(results) == 1
    r = results[0]
    assert r.status == "failed"
    assert r.error is not None
    assert r.status_code == 500
    assert mock_post.call_count == 3


@pytest.mark.asyncio
async def test_dispatch_connection_error_returns_failed(dispatcher):
    """Network errors are caught and result in 'failed' status."""
    dispatcher.subscribe(url="https://example.com/hook", events=["document.created"])

    dispatcher_retry = WebhookDispatcher(max_retries=1)  # 1 initial + 1 retry = 2 total
    dispatcher_retry.subscribe(url="https://example.com/hook", events=["document.created"])

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=Exception("connection refused")) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        results = await dispatcher_retry.dispatch(_make_event())

    assert len(results) == 1
    r = results[0]
    assert r.status == "failed"
    assert "connection refused" in r.error
    assert r.status_code is None
    assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_dispatch_skips_inactive_subscriptions(dispatcher):
    sub = dispatcher.subscribe(url="https://a.com/hook", events=["document.created"])
    sub.active = False

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        results = await dispatcher.dispatch(_make_event())

    assert results == []
    mock_post.assert_not_called()


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
async def test_dispatch_multiple_subscribers(dispatcher):
    dispatcher.subscribe(url="https://a.com/hook", events=["document.created"])
    dispatcher.subscribe(url="https://b.com/hook", events=["document.created", "document.approved"])
    dispatcher.subscribe(url="https://c.com/hook", events=["document.approved"])

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        results = await dispatcher.dispatch(_make_event())

    assert len(results) == 2
    urls = {r.url for r in results}
    assert urls == {"https://a.com/hook", "https://b.com/hook"}
    assert all(r.status == "delivered" for r in results)


@pytest.mark.asyncio
async def test_dispatch_payload_contains_event_data(dispatcher):
    dispatcher.subscribe(url="https://example.com/hook", events=["document.created"])

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await dispatcher.dispatch(_make_event())

    import json as _json
    sent_content = mock_post.call_args[1].get("content") or mock_post.call_args.kwargs.get("content")
    assert sent_content is not None
    sent_json = _json.loads(sent_content)
    assert sent_json["event_type"] == "document.created"
    assert sent_json["document_id"] == "doc-1"
    assert sent_json["payload"] == {"vendor": "Acme"}


# --- dispatch_or_raise ---


@pytest.mark.asyncio
async def test_dispatch_or_raise_returns_results_on_success(dispatcher):
    dispatcher.subscribe(url="https://example.com/hook", events=["document.created"])

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        results = await dispatcher.dispatch_or_raise(_make_event())

    assert len(results) == 1
    assert results[0].status == "delivered"


@pytest.mark.asyncio
async def test_dispatch_or_raise_raises_when_all_fail(dispatcher):
    dispatcher.subscribe(url="https://example.com/hook", events=["document.created"])

    fail_response = MagicMock()
    fail_response.status_code = 500

    dispatcher_retry = WebhookDispatcher(max_retries=0)
    dispatcher_retry.subscribe(url="https://example.com/hook", events=["document.created"])

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=fail_response), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(WebhookDeliveryError, match="All 1 webhook deliveries failed"):
            await dispatcher_retry.dispatch_or_raise(_make_event())


@pytest.mark.asyncio
async def test_dispatch_or_raise_does_not_raise_when_partial_success(dispatcher):
    dispatcher.subscribe(url="https://a.com/hook", events=["document.created"])
    dispatcher.subscribe(url="https://b.com/hook", events=["document.created"])

    ok_response = MagicMock()
    ok_response.status_code = 200
    fail_response = MagicMock()
    fail_response.status_code = 500

    dispatcher_retry = WebhookDispatcher(max_retries=0)
    dispatcher_retry.subscribe(url="https://a.com/hook", events=["document.created"])
    dispatcher_retry.subscribe(url="https://b.com/hook", events=["document.created"])

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[ok_response, fail_response]), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        results = await dispatcher_retry.dispatch_or_raise(_make_event())

    assert len(results) == 2
    assert any(r.status == "delivered" for r in results)
    assert any(r.status == "failed" for r in results)
