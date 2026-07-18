from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth import AuthenticatedPrincipal, require_operator
from app.config import get_settings
from app.services.audit_log import AuditAction, AuditLogService, get_audit_log_service
from app.services.durable_invoice_service import get_durable_invoice_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/audit", tags=["Audit"])

def _durable_mode_enabled() -> bool:
    return get_settings().INVOICE_JP_DURABLE_MODE


class AuditEntryResponse(BaseModel):
    id: str
    document_id: str
    action: str
    actor: str
    reason: str | None
    changes: dict | None
    created_at: datetime


class AuditListResponse(BaseModel):
    entries: list[AuditEntryResponse]
    total: int
    limit: int
    offset: int


@router.get("", response_model=AuditListResponse)
async def list_audit_entries(
    document_id: Optional[str] = Query(None),
    action: Optional[AuditAction] = Query(None),
    actor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_operator),
):
    """List audit log entries with optional filtering and pagination."""
    if _durable_mode_enabled():
        entries, total = get_durable_invoice_service().list_audit_entries(
            document_id=document_id,
            action=action,
            actor=actor,
            limit=limit,
            offset=offset,
            tenant_id=principal.tenant_id,
        )
    else:
        svc = get_audit_log_service()
        entries, total = await svc.list_entries(
            document_id=document_id,
            action=action,
            actor=actor,
            limit=limit,
            offset=offset,
            tenant_id=principal.tenant_id,
        )
    return AuditListResponse(
        entries=[
            AuditEntryResponse(
                id=e.id,
                document_id=e.document_id,
                action=e.action.value,
                actor=e.actor,
                reason=e.reason,
                changes=e.changes,
                created_at=e.created_at,
            )
            for e in entries
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
