from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class WebhookSubscription:
    id: str
    url: str
    events: list[str]
    secret: str | None
    active: bool = True


@dataclass
class WebhookEvent:
    event_type: str
    document_id: str
    payload: dict
    timestamp: datetime


@dataclass
class DeliveryResult:
    subscription_id: str
    url: str
    status: str  # "pending" in Stage 1, will be wired to actual HTTP in Stage 5
    event_type: str


class WebhookDispatcher:
    """Dispatches webhook events to subscribed URLs."""

    def __init__(self) -> None:
        self._subscriptions: list[WebhookSubscription] = []

    def subscribe(
        self, url: str, events: list[str], secret: str | None = None
    ) -> WebhookSubscription:
        sub = WebhookSubscription(
            id=str(uuid.uuid4()),
            url=url,
            events=events,
            secret=secret,
        )
        self._subscriptions.append(sub)
        return sub

    def unsubscribe(self, subscription_id: str) -> bool:
        for i, sub in enumerate(self._subscriptions):
            if sub.id == subscription_id:
                self._subscriptions.pop(i)
                return True
        return False

    def list_subscriptions(self) -> list[WebhookSubscription]:
        return list(self._subscriptions)

    async def dispatch(self, event: WebhookEvent) -> list[DeliveryResult]:
        """Dispatch event to all matching subscribers.

        Stage 1: logs the dispatch and returns pending results.
        Actual HTTP POST will be wired in Stage 5.
        """
        results: list[DeliveryResult] = []
        for sub in self._subscriptions:
            if not sub.active:
                continue
            if event.event_type in sub.events:
                results.append(
                    DeliveryResult(
                        subscription_id=sub.id,
                        url=sub.url,
                        status="pending",
                        event_type=event.event_type,
                    )
                )
        return results


def get_webhook_dispatcher() -> WebhookDispatcher:
    return WebhookDispatcher()
