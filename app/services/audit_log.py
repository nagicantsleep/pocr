from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class AuditAction(str, Enum):
    CREATE = "create"
    APPROVE = "approve"
    REJECT = "reject"
    PATCH = "patch"
    REVIEW = "review"


@dataclass
class AuditEntry:
    id: str
    document_id: str
    action: AuditAction
    actor: str
    reason: str | None
    changes: dict | None
    created_at: datetime


# Module-level in-memory store. Postgres persistence will come in a later stage.
_store: list[AuditEntry] = []


class AuditLogService:
    """Audit log for document actions."""

    async def log(
        self,
        document_id: str,
        action: AuditAction,
        actor: str,
        reason: str | None = None,
        changes: dict | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            id=str(uuid.uuid4()),
            document_id=document_id,
            action=action,
            actor=actor,
            reason=reason,
            changes=changes,
            created_at=datetime.now(timezone.utc),
        )
        _store.append(entry)
        return entry

    async def list_entries(
        self,
        document_id: str | None = None,
        action: AuditAction | None = None,
        actor: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEntry]:
        filtered = _store
        if document_id is not None:
            filtered = [e for e in filtered if e.document_id == document_id]
        if action is not None:
            filtered = [e for e in filtered if e.action == action]
        if actor is not None:
            filtered = [e for e in filtered if e.actor == actor]
        return filtered[offset : offset + limit]

    async def get_entry(self, entry_id: str) -> AuditEntry | None:
        for entry in _store:
            if entry.id == entry_id:
                return entry
        return None


def get_audit_log_service() -> AuditLogService:
    return AuditLogService()
