from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_mod
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class WebhookDeliveryError(Exception):
    """Raised when all webhook deliveries for an event fail."""

    pass


_DEFAULT_MAX_RETRIES = 4
_DEFAULT_BACKOFF_BASE = 1.0
_MAX_URL_LENGTH = 2048


class WebhookURLError(ValueError):
    """Raised when a webhook URL fails validation (scheme/host/length)."""


def validate_webhook_url(url: str, *, allowed_hosts: list[str] | None = None) -> None:
    """Reject unsafe URLs and require an application allowlist when configured.

    Ponytail: allowlisted hosts are trusted deployment configuration. Add
    DNS pinning if subscriptions must support untrusted dynamic hosts.
    """
    if not isinstance(url, str) or not url:
        raise WebhookURLError("Webhook URL must be a non-empty string")
    if len(url) > _MAX_URL_LENGTH:
        raise WebhookURLError(f"Webhook URL exceeds {_MAX_URL_LENGTH} chars")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise WebhookURLError("Webhook URL must use https scheme")
    host = (parsed.hostname or "").lower()
    if not host:
        raise WebhookURLError("Webhook URL must include a host")
    if parsed.username or parsed.password:
        raise WebhookURLError("Webhook URL must not include credentials")
    if allowed_hosts is not None:
        normalized = {h.strip().lower().rstrip(".") for h in allowed_hosts if h.strip()}
        if not normalized:
            raise WebhookURLError("WEBHOOK_ALLOWED_HOSTS must be configured")
        if host not in normalized:
            raise WebhookURLError(f"Host {host!r} not in WEBHOOK_ALLOWED_HOSTS allowlist")


@dataclass
class WebhookSubscription:
    id: str
    url: str
    events: list[str]
    secret: str | None
    active: bool = True
    tenant_id: str = "development"


@dataclass
class WebhookEvent:
    event_type: str
    document_id: str
    payload: dict
    timestamp: datetime
    tenant_id: str = "development"


@dataclass
class DeliveryResult:
    subscription_id: str
    url: str
    status: str  # "delivered", "failed"
    event_type: str
    error: str | None = None
    status_code: int | None = None


class WebhookDispatcher:
    """Dispatches webhook events to subscribed URLs."""

    def __init__(
        self,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        backoff_base: float = _DEFAULT_BACKOFF_BASE,
        allowed_hosts: list[str] | None = None,
    ) -> None:
        self._subscriptions: list[WebhookSubscription] = []
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._allowed_hosts = allowed_hosts

    def subscribe(
        self,
        url: str,
        events: list[str],
        secret: str | None = None,
        tenant_id: str = "development",
    ) -> WebhookSubscription:
        validate_webhook_url(url, allowed_hosts=self._allowed_hosts)
        sub = WebhookSubscription(
            id=str(uuid.uuid4()),
            url=url,
            events=events,
            secret=secret,
            tenant_id=tenant_id,
        )
        self._subscriptions.append(sub)
        return sub

    def unsubscribe(self, subscription_id: str, tenant_id: str | None = None) -> bool:
        for i, sub in enumerate(self._subscriptions):
            if sub.id == subscription_id and (
                tenant_id is None or sub.tenant_id == tenant_id
            ):
                self._subscriptions.pop(i)
                return True
        return False

    def list_subscriptions(self, tenant_id: str | None = None) -> list[WebhookSubscription]:
        if tenant_id is None:
            return list(self._subscriptions)
        return [sub for sub in self._subscriptions if sub.tenant_id == tenant_id]

    async def _deliver(self, url: str, body: bytes, headers: dict | None = None) -> tuple[int, str | None]:
        """POST JSON body to *url*. Returns (status_code, error_detail)."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, content=body, headers=headers or {}, timeout=10.0)
            return resp.status_code, None

    async def dispatch(self, event: WebhookEvent) -> list[DeliveryResult]:
        """Dispatch event to all matching subscribers with retry."""
        tasks = []
        for sub in self._subscriptions:
            if not sub.active:
                continue
            if sub.tenant_id == event.tenant_id and event.event_type in sub.events:
                payload = {
                    "event_type": event.event_type,
                    "document_id": event.document_id,
                    "payload": event.payload,
                    "timestamp": event.timestamp.isoformat(),
                }
                tasks.append(self._deliver_with_retry(sub, event.event_type, payload))
        return await asyncio.gather(*tasks)

    async def dispatch_or_raise(self, event: WebhookEvent) -> list[DeliveryResult]:
        """Dispatch event; raise if ALL deliveries fail."""
        results = await self.dispatch(event)
        if results and all(r.status == "failed" for r in results):
            raise WebhookDeliveryError(
                f"All {len(results)} webhook deliveries failed for event {event.event_type} "
                f"on document {event.document_id}"
            )
        return results

    async def _deliver_with_retry(
        self,
        sub: WebhookSubscription,
        event_type: str,
        payload: dict,
    ) -> DeliveryResult:
        last_error: str | None = None
        last_status_code: int | None = None
        total_attempts = 1 + self._max_retries

        headers: dict[str, str] = {}
        body_bytes = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode("utf-8")
        if sub.secret:
            sig = hmac_mod.new(sub.secret.encode(), body_bytes, hashlib.sha256).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={sig}"
        headers["Content-Type"] = "application/json"

        for attempt in range(total_attempts):
            if attempt > 0:
                delay = self._backoff_base * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
            try:
                status_code, error_detail = await self._deliver(sub.url, body_bytes, headers)
                if 200 <= status_code < 300:
                    return DeliveryResult(
                        subscription_id=sub.id,
                        url=sub.url,
                        status="delivered",
                        event_type=event_type,
                        status_code=status_code,
                    )
                last_error = error_detail or f"HTTP {status_code}"
                last_status_code = status_code
            except Exception as exc:
                last_error = str(exc)
                last_status_code = None

        logger.warning(
            "Webhook delivery failed after %d attempts for %s: %s",
            total_attempts,
            sub.url,
            last_error,
        )
        return DeliveryResult(
            subscription_id=sub.id,
            url=sub.url,
            status="failed",
            event_type=event_type,
            error=last_error,
            status_code=last_status_code,
        )


_webhook_dispatcher: WebhookDispatcher | None = None


def get_webhook_dispatcher() -> WebhookDispatcher:
    global _webhook_dispatcher
    if _webhook_dispatcher is None:
        settings = get_settings()
        allowlist = [
            h for h in settings.WEBHOOK_ALLOWED_HOSTS.split(",") if h.strip()
        ]
        dispatcher_class = (
            DurableWebhookDispatcher
            if settings.INVOICE_JP_DURABLE_MODE
            else WebhookDispatcher
        )
        _webhook_dispatcher = dispatcher_class(allowed_hosts=allowlist)
    return _webhook_dispatcher


class DurableWebhookDispatcher(WebhookDispatcher):
    """PostgreSQL subscriptions and delivery state for committed outbox events."""

    def __init__(
        self,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        backoff_base: float = _DEFAULT_BACKOFF_BASE,
        allowed_hosts: list[str] | None = None,
        repository=None,
    ) -> None:
        super().__init__(max_retries, backoff_base, allowed_hosts)
        from app.repositories.invoice_repository import get_invoice_repository

        self._repository = repository or get_invoice_repository()

    def _ensure_schema(self) -> None:
        self._repository.ensure_schema()

    def subscribe(
        self,
        url: str,
        events: list[str],
        secret: str | None = None,
        tenant_id: str = "development",
    ) -> WebhookSubscription:
        validate_webhook_url(url, allowed_hosts=self._allowed_hosts)
        self._ensure_schema()
        subscription = WebhookSubscription(
            id=str(uuid.uuid4()),
            url=url,
            events=events,
            secret=secret,
            tenant_id=tenant_id,
        )
        self._repository.subscribe_webhook(
            subscription_id=subscription.id,
            tenant_id=tenant_id,
            url=url,
            event_types=events,
            secret=secret,
        )
        return subscription

    def unsubscribe(self, subscription_id: str, tenant_id: str | None = None) -> bool:
        if tenant_id is None:
            raise ValueError("durable webhook deletion requires tenant_id")
        return self._repository.unsubscribe_webhook(subscription_id, tenant_id=tenant_id)

    def list_subscriptions(self, tenant_id: str | None = None) -> list[WebhookSubscription]:
        if tenant_id is None:
            raise ValueError("durable webhook listing requires tenant_id")
        rows = self._repository.list_webhook_subscriptions(tenant_id=tenant_id)
        return [
            WebhookSubscription(
                id=row["id"],
                url=row["url"],
                events=row["event_types"],
                secret=row["secret"],
                active=row["active"],
                tenant_id=row["tenant_id"],
            )
            for row in rows
        ]

    def _delivery_lease_seconds(self) -> int:
        attempts = 1 + self._max_retries
        backoff = sum(self._backoff_base * (2 ** retry) for retry in range(self._max_retries))
        # HTTP timeout is 10s; keep a buffer so a second sender cannot overlap retries.
        return max(30, int(attempts * 10 + backoff + 5))

    def _claim_delivery(self, event_id: str, subscription_id: str) -> str | None:
        return self._repository.claim_webhook_delivery(
            event_id=event_id,
            subscription_id=subscription_id,
            lease_seconds=self._delivery_lease_seconds(),
        )

    def _complete_delivery(
        self,
        event_id: str,
        subscription_id: str,
        lease_token: str,
        response_code: int,
    ) -> None:
        if not self._repository.complete_webhook_delivery(
            event_id=event_id,
            subscription_id=subscription_id,
            lease_token=lease_token,
            response_code=response_code,
        ):
            raise RuntimeError("webhook delivery lease could not be completed")

    def _release_delivery(
        self,
        event_id: str,
        subscription_id: str,
        lease_token: str,
        error: str,
        response_code: int | None,
    ) -> None:
        self._repository.release_webhook_delivery(
            event_id=event_id,
            subscription_id=subscription_id,
            lease_token=lease_token,
            error=error,
            response_code=response_code,
        )

    async def _deliver_outbox_subscription(
        self,
        event_id: str,
        event: WebhookEvent,
        subscription: WebhookSubscription,
        lease_token: str,
    ) -> DeliveryResult:
        payload = {
            "event_id": event_id,
            "event_type": event.event_type,
            "document_id": event.document_id,
            "payload": event.payload,
            "timestamp": event.timestamp.isoformat(),
        }
        headers = {"Content-Type": "application/json", "X-Webhook-Event-Id": event_id}
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if subscription.secret:
            signature = hmac_mod.new(subscription.secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        last_error: str | None = None
        last_status_code: int | None = None
        for attempt in range(1 + self._max_retries):
            if attempt:
                await asyncio.sleep(self._backoff_base * (2 ** (attempt - 1)))
            try:
                status_code, error_detail = await self._deliver(subscription.url, body, headers)
                if 200 <= status_code < 300:
                    try:
                        self._complete_delivery(event_id, subscription.id, lease_token, status_code)
                    except Exception as exc:
                        logger.warning(
                            "Webhook %s accepted %s but delivery receipt was not persisted: %s",
                            event_id,
                            subscription.id,
                            exc,
                        )
                        return DeliveryResult(
                            subscription_id=subscription.id,
                            url=subscription.url,
                            status="failed",
                            event_type=event.event_type,
                            error=f"delivery acknowledgement failed after HTTP {status_code}: {exc}",
                            status_code=status_code,
                        )
                    return DeliveryResult(
                        subscription_id=subscription.id,
                        url=subscription.url,
                        status="delivered",
                        event_type=event.event_type,
                        status_code=status_code,
                    )
                last_error = error_detail or f"HTTP {status_code}"
                last_status_code = status_code
            except Exception as exc:
                last_error = str(exc)
                last_status_code = None

        error = last_error or "delivery failed"
        self._release_delivery(
            event_id,
            subscription.id,
            lease_token,
            error,
            last_status_code,
        )
        return DeliveryResult(
            subscription_id=subscription.id,
            url=subscription.url,
            status="failed",
            event_type=event.event_type,
            error=error,
            status_code=last_status_code,
        )

    async def dispatch_outbox(self, event_id: str, event: WebhookEvent) -> list[DeliveryResult]:
        """Deliver a committed event only to its active materialized intents."""
        list_intents = getattr(self._repository, "list_pending_webhook_subscriptions", None)
        if list_intents is None:
            subscriptions = [
                subscription
                for subscription in self.list_subscriptions(tenant_id=event.tenant_id)
                if subscription.active and event.event_type in subscription.events
            ]
        else:
            subscriptions = [
                WebhookSubscription(
                    id=row["id"],
                    url=row["url"],
                    events=row["event_types"],
                    secret=row["secret"],
                    active=row["active"],
                    tenant_id=row["tenant_id"],
                )
                for row in list_intents(event_id)
                if row["tenant_id"] == event.tenant_id and event.event_type in row["event_types"]
            ]
        claims = [
            (subscription, self._claim_delivery(event_id, subscription.id))
            for subscription in subscriptions
        ]
        tasks = [
            self._deliver_outbox_subscription(event_id, event, subscription, lease_token)
            for subscription, lease_token in claims
            if lease_token is not None
        ]
        results = await asyncio.gather(*tasks)
        if any(result.status == "failed" for result in results):
            raise WebhookDeliveryError(
                f"Webhook delivery failed for event {event.event_type}; retry required"
            )
        return results
