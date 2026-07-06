"""PostgreSQL-backed invoice storage and audit logs."""

import json
import uuid
from datetime import datetime, timezone

from app.config import get_settings

INVOICES_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    source_file_hash TEXT,
    source_file_path TEXT,
    issuer_name TEXT,
    issuer_registration_number TEXT,
    invoice_number TEXT,
    transaction_date TEXT,
    total_amount INTEGER,
    raw_ocr_json JSONB,
    extracted_json JSONB,
    validation_json JSONB,
    review_status TEXT DEFAULT 'needs_review',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""

AUDIT_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_audit_logs (
    id SERIAL PRIMARY KEY,
    invoice_id TEXT REFERENCES invoices(id),
    actor TEXT,
    action TEXT,
    before_json JSONB,
    after_json JSONB,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


class ReviewStatus:
    AUTO_APPROVED = "auto_approved"
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"
    REJECTED = "rejected"
    EXPORTED = "exported"


class InvoiceRepository:
    def __init__(self, dsn: str | None = None, min_connections: int = 1, max_connections: int = 10) -> None:
        import psycopg_pool

        self.dsn = dsn or get_settings().POSTGRES_DSN
        self._pool = psycopg_pool.ConnectionPool(
            self.dsn,
            min_size=min_connections,
            max_size=max_connections,
            open=False,
        )
        self._pool.open()

    def _conn(self):
        return self._pool.connection()

    def ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(INVOICES_SCHEMA)
            conn.execute(AUDIT_LOG_SCHEMA)

    def save_invoice(self, invoice_data: dict) -> str:
        """Insert invoice, return ID."""
        invoice_id = f"inv_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc)
        self.ensure_schema()

        source = invoice_data.get("source", {})
        extracted = invoice_data.get("extracted", {})
        validation = invoice_data.get("validation", {})

        # Extract top-level fields from extracted data for easy querying
        issuer_name = extracted.get("issuer_name")
        issuer_reg = extracted.get("issuer_registration_number")
        invoice_number = extracted.get("invoice_number")
        transaction_date = extracted.get("transaction_date")
        total_amount = extracted.get("total_amount")

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO invoices
                    (id, source_file_hash, source_file_path, issuer_name,
                     issuer_registration_number, invoice_number, transaction_date,
                     total_amount, raw_ocr_json, extracted_json, validation_json,
                     review_status, created_at, updated_at)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s)
                """,
                (
                    invoice_id,
                    source.get("file_hash"),
                    source.get("file_path"),
                    issuer_name,
                    issuer_reg,
                    invoice_number,
                    transaction_date,
                    total_amount,
                    json.dumps(invoice_data.get("raw_ocr")),
                    json.dumps(extracted),
                    json.dumps(validation),
                    ReviewStatus.NEEDS_REVIEW,
                    now,
                    now,
                ),
            )
        return invoice_id

    def get_invoice(self, invoice_id: str) -> dict | None:
        """Fetch invoice by ID."""
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, source_file_hash, source_file_path, issuer_name,
                       issuer_registration_number, invoice_number, transaction_date,
                       total_amount, raw_ocr_json, extracted_json, validation_json,
                       review_status, created_at, updated_at
                FROM invoices WHERE id = %s
                """,
                (invoice_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "source_file_hash": row[1],
            "source_file_path": row[2],
            "issuer_name": row[3],
            "issuer_registration_number": row[4],
            "invoice_number": row[5],
            "transaction_date": row[6],
            "total_amount": row[7],
            "raw_ocr_json": row[8],
            "extracted_json": row[9],
            "validation_json": row[10],
            "review_status": row[11],
            "created_at": row[12],
            "updated_at": row[13],
        }

    def update_invoice(self, invoice_id: str, updates: dict, actor: str = "system", reason: str = "") -> bool:
        """Update invoice fields with audit log entry."""
        self.ensure_schema()
        current = self.get_invoice(invoice_id)
        if current is None:
            return False

        now = datetime.now(timezone.utc)
        # Build SET clause for updatable fields
        updatable = {
            "issuer_name", "issuer_registration_number", "invoice_number",
            "transaction_date", "total_amount", "review_status",
            "source_file_hash", "source_file_path",
        }
        filtered = {k: v for k, v in updates.items() if k in updatable}
        if not filtered:
            return False

        set_parts = ["updated_at = %s"]
        params = [now]
        for col, val in filtered.items():
            set_parts.append(f"{col} = %s")
            params.append(val)
        params.append(invoice_id)

        # Audit log: before = current top-level fields, after = updates
        before_snapshot = {k: current.get(k) for k in filtered}

        with self._conn() as conn:
            conn.execute(
                f"UPDATE invoices SET {', '.join(set_parts)} WHERE id = %s",
                params,
            )

        self.add_audit_log(
            invoice_id=invoice_id,
            actor=actor,
            action="update_fields",
            before=before_snapshot,
            after=filtered,
            reason=reason,
        )
        return True

    def add_audit_log(
        self,
        invoice_id: str,
        actor: str,
        action: str,
        before: dict | None,
        after: dict | None,
        reason: str = "",
    ) -> None:
        """Insert audit log entry."""
        self.ensure_schema()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO invoice_audit_logs
                    (invoice_id, actor, action, before_json, after_json, reason)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    invoice_id,
                    actor,
                    action,
                    json.dumps(before) if before is not None else None,
                    json.dumps(after) if after is not None else None,
                    reason,
                ),
            )

    def get_audit_log(self, invoice_id: str) -> list[dict]:
        """Fetch audit log for invoice."""
        self.ensure_schema()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, invoice_id, actor, action, before_json, after_json, reason, created_at
                FROM invoice_audit_logs
                WHERE invoice_id = %s
                ORDER BY created_at ASC
                """,
                (invoice_id,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "invoice_id": r[1],
                "actor": r[2],
                "action": r[3],
                "before_json": r[4],
                "after_json": r[5],
                "reason": r[6],
                "created_at": r[7],
            }
            for r in rows
        ]

    def close(self) -> None:
        """Close the connection pool. Call on application shutdown."""
        self._pool.close()


_invoice_repository: InvoiceRepository | None = None


def get_invoice_repository() -> InvoiceRepository:
    global _invoice_repository
    if _invoice_repository is None:
        _invoice_repository = InvoiceRepository()
    return _invoice_repository
