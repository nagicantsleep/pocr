from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.webhook_dispatch import get_webhook_dispatcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/webhooks", tags=["Webhooks"])


class WebhookSubscribeRequest(BaseModel):
    url: str
    events: list[str]
    secret: str | None = None


class WebhookSubscriptionResponse(BaseModel):
    id: str
    url: str
    events: list[str]
    active: bool


class WebhookListResponse(BaseModel):
    subscriptions: list[WebhookSubscriptionResponse]


@router.post("", response_model=WebhookSubscriptionResponse, status_code=201)
async def subscribe(req: WebhookSubscribeRequest):
    """Register a webhook subscription."""
    dispatcher = get_webhook_dispatcher()
    sub = dispatcher.subscribe(url=req.url, events=req.events, secret=req.secret)
    return WebhookSubscriptionResponse(
        id=sub.id,
        url=sub.url,
        events=sub.events,
        active=sub.active,
    )


@router.get("", response_model=WebhookListResponse)
async def list_subscriptions():
    """List all webhook subscriptions."""
    dispatcher = get_webhook_dispatcher()
    subs = dispatcher.list_subscriptions()
    return WebhookListResponse(
        subscriptions=[
            WebhookSubscriptionResponse(
                id=s.id,
                url=s.url,
                events=s.events,
                active=s.active,
            )
            for s in subs
        ]
    )


@router.delete("/{subscription_id}", status_code=200)
async def unsubscribe(subscription_id: str):
    """Remove a webhook subscription."""
    dispatcher = get_webhook_dispatcher()
    removed = dispatcher.unsubscribe(subscription_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "removed", "id": subscription_id}
