"""PostgreSQL-backed invoice storage, audit logs, and delivery intents."""

import json
import uuid
from datetime import datetime, timedelta, timezone

from app.config import get_settings

DEFAULT_TENANT_ID = "default"
_MIN_IDEMPOTENCY_TTL_SECONDS = 300

INVOICES_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
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
    document_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""

AUDIT_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_audit_logs (
    id SERIAL PRIMARY KEY,
    invoice_id TEXT REFERENCES invoices(id),
    tenant_id TEXT NOT NULL DEFAULT 'default',
    actor TEXT,
    action TEXT,
    before_json JSONB,
    after_json JSONB,
    before_version INTEGER,
    after_version INTEGER,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

IDEMPOTENCY_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_idempotency_records (
    tenant_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    canonical_response_json JSONB,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (tenant_id, idempotency_key)
);
"""

OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_outbox (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    invoice_id TEXT REFERENCES invoices(id),
    event_type TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    publish_attempts INTEGER NOT NULL DEFAULT 0,
    claimed_until TIMESTAMPTZ,
    lease_token TEXT,
    last_error TEXT
);
"""

EXTRACTION_JOB_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_extraction_jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_file_hash TEXT NOT NULL,
    content_type TEXT NOT NULL,
    ocr_lang TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    document_id TEXT REFERENCES invoices(id),
    result_json JSONB,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    claimed_until TIMESTAMPTZ,
    lease_token TEXT,
    artifact_cleanup_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
    artifact_cleanup_pending BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
"""

SEARCH_CHUNK_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_search_chunks (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, invoice_id, chunk_index)
);
"""

WEBHOOK_SUBSCRIPTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_webhook_subscriptions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    url TEXT NOT NULL,
    event_types_json JSONB NOT NULL,
    secret TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""

WEBHOOK_DELIVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_webhook_deliveries (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES invoice_outbox(id),
    subscription_id TEXT NOT NULL REFERENCES invoice_webhook_subscriptions(id),
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    response_code INTEGER,
    error TEXT,
    claimed_until TIMESTAMPTZ,
    lease_token TEXT,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (event_id, subscription_id)
);
"""

CONSUMER_RECEIPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice_consumer_receipts (
    event_id TEXT NOT NULL REFERENCES invoice_outbox(id),
    consumer TEXT NOT NULL,
    received_at TIMESTAMPTZ DEFAULT NOW(),
    state TEXT NOT NULL DEFAULT 'processing',
    claimed_until TIMESTAMPTZ,
    lease_token TEXT,
    last_error TEXT,
    PRIMARY KEY (event_id, consumer)
);
"""

SCHEMA_MIGRATIONS = (
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'",
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS document_version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE invoice_audit_logs ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'",
    "ALTER TABLE invoice_audit_logs ADD COLUMN IF NOT EXISTS before_version INTEGER",
    "ALTER TABLE invoice_audit_logs ADD COLUMN IF NOT EXISTS after_version INTEGER",
    "ALTER TABLE invoice_outbox ADD COLUMN IF NOT EXISTS claimed_until TIMESTAMPTZ",
    "ALTER TABLE invoice_outbox ADD COLUMN IF NOT EXISTS lease_token TEXT",
    "ALTER TABLE invoice_outbox ADD COLUMN IF NOT EXISTS last_error TEXT",
    "ALTER TABLE invoice_outbox ALTER COLUMN invoice_id DROP NOT NULL",
    "ALTER TABLE invoice_webhook_deliveries ADD COLUMN IF NOT EXISTS claimed_until TIMESTAMPTZ",
    "ALTER TABLE invoice_webhook_deliveries ADD COLUMN IF NOT EXISTS lease_token TEXT",
    "ALTER TABLE invoice_consumer_receipts ADD COLUMN IF NOT EXISTS state TEXT NOT NULL DEFAULT 'processing'",
    "ALTER TABLE invoice_consumer_receipts ADD COLUMN IF NOT EXISTS claimed_until TIMESTAMPTZ",
    "ALTER TABLE invoice_consumer_receipts ADD COLUMN IF NOT EXISTS lease_token TEXT",
    "ALTER TABLE invoice_consumer_receipts ADD COLUMN IF NOT EXISTS last_error TEXT",
    "ALTER TABLE invoice_extraction_jobs ADD COLUMN IF NOT EXISTS lease_token TEXT",
    "ALTER TABLE invoice_extraction_jobs ADD COLUMN IF NOT EXISTS artifact_cleanup_keys JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE invoice_extraction_jobs ADD COLUMN IF NOT EXISTS artifact_cleanup_pending BOOLEAN NOT NULL DEFAULT FALSE",
    "CREATE INDEX IF NOT EXISTS idx_invoices_tenant_id ON invoices (tenant_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_invoice_audit_logs_tenant_invoice ON invoice_audit_logs (tenant_id, invoice_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_invoice_outbox_pending ON invoice_outbox (published_at, claimed_until, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_invoice_extraction_jobs_claim ON invoice_extraction_jobs (status, claimed_until, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_invoice_search_chunks_tenant_invoice ON invoice_search_chunks (tenant_id, invoice_id, chunk_index)",
    "CREATE INDEX IF NOT EXISTS idx_invoice_webhook_subscriptions_tenant_active ON invoice_webhook_subscriptions (tenant_id, active)",
    "CREATE INDEX IF NOT EXISTS idx_invoice_webhook_deliveries_claim ON invoice_webhook_deliveries (status, claimed_until)",
)


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
        self._schema_ready = False
        self._pool.open()

    def _conn(self):
        return self._pool.connection()

    @staticmethod
    def _tenant_id(tenant_id: str) -> str:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")
        return tenant_id

    @staticmethod
    def _json(value: dict | list | None) -> str | None:
        return json.dumps(value, default=str) if value is not None else None

    @staticmethod
    def _field_value(value):
        return value.get("value") if isinstance(value, dict) else value

    @staticmethod
    def _invoice_from_row(row) -> dict:
        return {
            "id": row[0],
            "tenant_id": row[1],
            "source_file_hash": row[2],
            "source_file_path": row[3],
            "issuer_name": row[4],
            "issuer_registration_number": row[5],
            "invoice_number": row[6],
            "transaction_date": row[7],
            "total_amount": row[8],
            "raw_ocr_json": row[9],
            "extracted_json": row[10],
            "validation_json": row[11],
            "review_status": row[12],
            "document_version": row[13],
            "created_at": row[14],
            "updated_at": row[15],
        }

    @staticmethod
    def _snapshot(invoice: dict) -> dict:
        """Keep audit snapshots complete enough to reconstruct review changes."""
        return {
            key: invoice.get(key)
            for key in (
                "id",
                "tenant_id",
                "source_file_hash",
                "source_file_path",
                "issuer_name",
                "issuer_registration_number",
                "invoice_number",
                "transaction_date",
                "total_amount",
                "raw_ocr_json",
                "extracted_json",
                "validation_json",
                "review_status",
                "document_version",
            )
        }

    def ensure_schema(self) -> None:
        if getattr(self, "_schema_ready", False):
            return
        with self._conn() as conn:
            conn.execute(INVOICES_SCHEMA)
            conn.execute(AUDIT_LOG_SCHEMA)
            conn.execute(IDEMPOTENCY_SCHEMA)
            conn.execute(OUTBOX_SCHEMA)
            conn.execute(EXTRACTION_JOB_SCHEMA)
            conn.execute(SEARCH_CHUNK_SCHEMA)
            conn.execute(WEBHOOK_SUBSCRIPTION_SCHEMA)
            conn.execute(WEBHOOK_DELIVERY_SCHEMA)
            conn.execute(CONSUMER_RECEIPT_SCHEMA)
            for statement in SCHEMA_MIGRATIONS:
                conn.execute(statement)
        self._schema_ready = True

    def _enqueue_outbox(
        self,
        conn,
        *,
        tenant_id: str,
        invoice_id: str | None,
        event_type: str,
        payload: dict,
    ) -> str:
        event_id = f"evt_{uuid.uuid4().hex}"
        conn.execute(
            """
            INSERT INTO invoice_outbox
                (id, tenant_id, invoice_id, event_type, payload_json)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (event_id, tenant_id, invoice_id, event_type, self._json(payload)),
        )
        return event_id

    def save_invoice(
        self,
        invoice_data: dict,
        tenant_id: str = DEFAULT_TENANT_ID,
        invoice_id: str | None = None,
        actor: str = "system",
        reason: str = "",
    ) -> str:
        """Insert an invoice, its create audit record, and outbox intent atomically."""
        tenant_id = self._tenant_id(tenant_id)
        invoice_id = invoice_id or f"inv_{uuid.uuid4().hex}"
        self.ensure_schema()

        with self._conn() as conn:
            self._insert_invoice(
                conn,
                invoice_data,
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                actor=actor,
                reason=reason,
            )
        return invoice_id

    def _insert_invoice(
        self,
        conn,
        invoice_data: dict,
        *,
        tenant_id: str,
        invoice_id: str,
        actor: str,
        reason: str,
    ) -> None:
        """Write one extracted document using an already-open transaction."""
        now = datetime.now(timezone.utc)
        source = invoice_data.get("source", {})
        extracted = invoice_data.get("extracted", {})
        validation = invoice_data.get("validation", {})

        conn.execute(
            """
            INSERT INTO invoices
                (id, tenant_id, source_file_hash, source_file_path, issuer_name,
                 issuer_registration_number, invoice_number, transaction_date,
                 total_amount, raw_ocr_json, extracted_json, validation_json,
                 review_status, document_version, created_at, updated_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                 %s::jsonb, %s, %s, %s, %s)
            """,
            (
                invoice_id,
                tenant_id,
                source.get("file_hash"),
                source.get("file_path"),
                self._field_value(extracted.get("issuer_name")),
                self._field_value(extracted.get("issuer_registration_number")),
                self._field_value(extracted.get("invoice_number")),
                self._field_value(extracted.get("transaction_date")),
                self._field_value(extracted.get("total_amount")),
                self._json(invoice_data.get("raw_ocr")),
                self._json(extracted),
                self._json(validation),
                invoice_data.get("review_status", ReviewStatus.NEEDS_REVIEW),
                1,
                now,
                now,
            ),
        )
        created_invoice = {
            "id": invoice_id,
            "tenant_id": tenant_id,
            "source_file_hash": source.get("file_hash"),
            "source_file_path": source.get("file_path"),
            "issuer_name": extracted.get("issuer_name"),
            "issuer_registration_number": extracted.get("issuer_registration_number"),
            "invoice_number": extracted.get("invoice_number"),
            "transaction_date": extracted.get("transaction_date"),
            "total_amount": extracted.get("total_amount"),
            "raw_ocr_json": invoice_data.get("raw_ocr"),
            "extracted_json": extracted,
            "validation_json": validation,
            "review_status": invoice_data.get("review_status", ReviewStatus.NEEDS_REVIEW),
            "document_version": 1,
        }
        conn.execute(
            """
            INSERT INTO invoice_audit_logs
                (invoice_id, tenant_id, actor, action, before_json, after_json,
                 before_version, after_version, reason)
            VALUES (%s, %s, %s, 'create', NULL, %s::jsonb, NULL, %s, %s)
            """,
            (
                invoice_id,
                tenant_id,
                actor,
                self._json(self._snapshot(created_invoice)),
                1,
                reason,
            ),
        )
        self._enqueue_outbox(
            conn,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            event_type="document.extraction_completed",
            payload={
                "document_id": invoice_id,
                "review_status": invoice_data.get("review_status", ReviewStatus.NEEDS_REVIEW),
                "document_version": 1,
            },
        )

    def save_invoice_and_complete_idempotency(
        self,
        invoice_data: dict,
        *,
        tenant_id: str,
        invoice_id: str,
        actor: str,
        reason: str,
        idempotency_key: str,
        request_fingerprint: str,
        canonical_response: dict,
    ) -> str:
        """Commit the document, audit, outbox, and idempotency response together."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            self._insert_invoice(
                conn,
                invoice_data,
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                actor=actor,
                reason=reason,
            )
            completed = conn.execute(
                """
                UPDATE invoice_idempotency_records
                SET state = 'completed', canonical_response_json = %s::jsonb, updated_at = %s
                WHERE tenant_id = %s
                  AND idempotency_key = %s
                  AND request_fingerprint = %s
                  AND resource_id = %s
                  AND state = 'pending'
                RETURNING tenant_id
                """,
                (
                    self._json(canonical_response),
                    datetime.now(timezone.utc),
                    tenant_id,
                    idempotency_key,
                    request_fingerprint,
                    invoice_id,
                ),
            ).fetchone()
            if completed is None:
                raise RuntimeError("idempotency claim was not owned by this extraction")
        return invoice_id

    def save_invoices_and_complete_idempotency(
        self,
        invoice_writes: list[dict],
        *,
        tenant_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        resource_id: str,
        canonical_response: dict,
    ) -> list[str]:
        """Commit every page plus its canonical response in one database transaction."""
        tenant_id = self._tenant_id(tenant_id)
        if not invoice_writes:
            raise ValueError("invoice_writes must not be empty")
        self.ensure_schema()
        invoice_ids: list[str] = []
        with self._conn() as conn:
            for write in invoice_writes:
                invoice_id = write["invoice_id"]
                self._insert_invoice(
                    conn,
                    write["invoice_data"],
                    tenant_id=tenant_id,
                    invoice_id=invoice_id,
                    actor=write.get("actor", "system"),
                    reason=write.get("reason", ""),
                )
                invoice_ids.append(invoice_id)
            completed = conn.execute(
                """
                UPDATE invoice_idempotency_records
                SET state = 'completed', canonical_response_json = %s::jsonb, updated_at = %s
                WHERE tenant_id = %s
                  AND idempotency_key = %s
                  AND request_fingerprint = %s
                  AND resource_id = %s
                  AND state = 'pending'
                RETURNING tenant_id
                """,
                (
                    self._json(canonical_response),
                    datetime.now(timezone.utc),
                    tenant_id,
                    idempotency_key,
                    request_fingerprint,
                    resource_id,
                ),
            ).fetchone()
            if completed is None:
                raise RuntimeError("idempotency claim was not owned by these extraction pages")
        return invoice_ids

    def save_invoices(
        self,
        invoice_writes: list[dict],
        *,
        tenant_id: str,
    ) -> list[str]:
        """Commit every page's invoice, audit, and outbox records as one unit."""
        tenant_id = self._tenant_id(tenant_id)
        if not invoice_writes:
            raise ValueError("invoice_writes must not be empty")
        self.ensure_schema()
        invoice_ids: list[str] = []
        with self._conn() as conn:
            for write in invoice_writes:
                invoice_id = write["invoice_id"]
                self._insert_invoice(
                    conn,
                    write["invoice_data"],
                    tenant_id=tenant_id,
                    invoice_id=invoice_id,
                    actor=write.get("actor", "system"),
                    reason=write.get("reason", ""),
                )
                invoice_ids.append(invoice_id)
        return invoice_ids

    def get_invoice(self, invoice_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> dict | None:
        """Fetch an invoice by ID only when it belongs to the requested tenant."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, tenant_id, source_file_hash, source_file_path, issuer_name,
                       issuer_registration_number, invoice_number, transaction_date,
                       total_amount, raw_ocr_json, extracted_json, validation_json,
                       review_status, document_version, created_at, updated_at
                FROM invoices
                WHERE id = %s AND tenant_id = %s
                """,
                (invoice_id, tenant_id),
            ).fetchone()
        return self._invoice_from_row(row) if row is not None else None

    def list_invoices(
        self,
        *,
        tenant_id: str,
        review_status: str | None = None,
        document_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """List and count tenant-scoped invoice documents with stable pagination."""
        tenant_id = self._tenant_id(tenant_id)
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        self.ensure_schema()

        filters = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if review_status is not None:
            filters.append("review_status = %s")
            params.append(review_status)
        if document_type is not None:
            filters.append("validation_json -> '_durable_document' ->> 'document_type' = %s")
            params.append(document_type)
        where_clause = " AND ".join(filters)
        select_columns = """
            id, tenant_id, source_file_hash, source_file_path, issuer_name,
            issuer_registration_number, invoice_number, transaction_date,
            total_amount, raw_ocr_json, extracted_json, validation_json,
            review_status, document_version, created_at, updated_at
        """
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT {select_columns}
                FROM invoices
                WHERE {where_clause}
                ORDER BY created_at ASC, id ASC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            ).fetchall()
            total = conn.execute(
                f"SELECT COUNT(*) FROM invoices WHERE {where_clause}",
                params,
            ).fetchone()[0]
        return [self._invoice_from_row(row) for row in rows], total

    def update_invoice(
        self,
        invoice_id: str,
        updates: dict,
        actor: str = "system",
        reason: str = "",
        tenant_id: str = DEFAULT_TENANT_ID,
        expected_version: int | None = None,
        audit_action: str = "update_fields",
    ) -> bool:
        """Atomically apply a versioned update, audit full snapshots, and enqueue intent."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()

        updatable = {
            "issuer_name",
            "issuer_registration_number",
            "invoice_number",
            "transaction_date",
            "total_amount",
            "review_status",
            "source_file_hash",
            "source_file_path",
            "extracted_json",
            "validation_json",
        }
        filtered = {key: value for key, value in updates.items() if key in updatable}
        if not filtered:
            return False

        now = datetime.now(timezone.utc)
        with self._conn() as conn:
            current_row = conn.execute(
                """
                SELECT id, tenant_id, source_file_hash, source_file_path, issuer_name,
                       issuer_registration_number, invoice_number, transaction_date,
                       total_amount, raw_ocr_json, extracted_json, validation_json,
                       review_status, document_version, created_at, updated_at
                FROM invoices
                WHERE id = %s AND tenant_id = %s
                FOR UPDATE
                """,
                (invoice_id, tenant_id),
            ).fetchone()
            if current_row is None:
                return False

            current = self._invoice_from_row(current_row)
            if expected_version is not None and current["document_version"] != expected_version:
                return False

            set_parts = ["updated_at = %s", "document_version = document_version + 1"]
            params = [now]
            for column, value in filtered.items():
                if column in {"extracted_json", "validation_json"}:
                    set_parts.append(f"{column} = %s::jsonb")
                    params.append(self._json(value))
                else:
                    set_parts.append(f"{column} = %s")
                    params.append(value)
            params.extend((invoice_id, tenant_id, current["document_version"]))
            updated_row = conn.execute(
                f"""
                UPDATE invoices
                SET {", ".join(set_parts)}
                WHERE id = %s AND tenant_id = %s AND document_version = %s
                RETURNING document_version
                """,
                params,
            ).fetchone()
            if updated_row is None:
                return False

            after = {**current, **filtered, "updated_at": now, "document_version": updated_row[0]}
            conn.execute(
                """
                INSERT INTO invoice_audit_logs
                    (invoice_id, tenant_id, actor, action, before_json, after_json,
                     before_version, after_version, reason)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                """,
                (
                    invoice_id,
                    tenant_id,
                    actor,
                    audit_action,
                    self._json(self._snapshot(current)),
                    self._json(self._snapshot(after)),
                    current["document_version"],
                    updated_row[0],
                    reason,
                ),
            )

            review_status = filtered.get("review_status")
            event_type = (
                "document.review_completed"
                if review_status in {ReviewStatus.REVIEWED, ReviewStatus.REJECTED}
                else "document.fields_patched"
            )
            self._enqueue_outbox(
                conn,
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                event_type=event_type,
                payload={
                    "document_id": invoice_id,
                    "actor": actor,
                    "reason": reason,
                    "changes": {
                        key: value
                        for key, value in filtered.items()
                        if key not in {"extracted_json", "validation_json"}
                    },
                    "document_version": updated_row[0],
                },
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
        tenant_id: str = DEFAULT_TENANT_ID,
        before_version: int | None = None,
        after_version: int | None = None,
    ) -> None:
        """Insert a tenant-scoped audit log entry for non-review maintenance work."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO invoice_audit_logs
                    (invoice_id, tenant_id, actor, action, before_json, after_json,
                     before_version, after_version, reason)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                """,
                (
                    invoice_id,
                    tenant_id,
                    actor,
                    action,
                    self._json(before),
                    self._json(after),
                    before_version,
                    after_version,
                    reason,
                ),
            )

    def get_audit_log(self, invoice_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict]:
        """Fetch an invoice's audit log only within the requested tenant."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, invoice_id, tenant_id, actor, action, before_json, after_json,
                       before_version, after_version, reason, created_at
                FROM invoice_audit_logs
                WHERE invoice_id = %s AND tenant_id = %s
                ORDER BY created_at ASC
                """,
                (invoice_id, tenant_id),
            ).fetchall()
        return [
            {
                "id": row[0],
                "invoice_id": row[1],
                "tenant_id": row[2],
                "actor": row[3],
                "action": row[4],
                "before_json": row[5],
                "after_json": row[6],
                "before_version": row[7],
                "after_version": row[8],
                "reason": row[9],
                "created_at": row[10],
            }
            for row in rows
        ]

    def list_audit_entries(
        self,
        *,
        tenant_id: str,
        document_id: str | None = None,
        action: str | None = None,
        actor: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """List tenant-scoped audit entries with the public filter/pagination shape."""
        tenant_id = self._tenant_id(tenant_id)
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        self.ensure_schema()
        filters = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if document_id is not None:
            filters.append("invoice_id = %s")
            params.append(document_id)
        if action is not None:
            filters.append("action = %s")
            params.append(action)
        if actor is not None:
            filters.append("actor = %s")
            params.append(actor)
        where_clause = " AND ".join(filters)
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT id, invoice_id, tenant_id, actor, action, before_json, after_json,
                       before_version, after_version, reason, created_at
                FROM invoice_audit_logs
                WHERE {where_clause}
                ORDER BY created_at ASC, id ASC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            ).fetchall()
            total = conn.execute(
                f"SELECT COUNT(*) FROM invoice_audit_logs WHERE {where_clause}",
                params,
            ).fetchone()[0]
        entries = [
            {
                "id": row[0],
                "invoice_id": row[1],
                "tenant_id": row[2],
                "actor": row[3],
                "action": row[4],
                "before_json": row[5],
                "after_json": row[6],
                "before_version": row[7],
                "after_version": row[8],
                "reason": row[9],
                "created_at": row[10],
            }
            for row in rows
        ]
        return entries, total

    def claim_idempotency_record(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        resource_id: str,
        expires_at: datetime,
    ) -> tuple[bool, dict]:
        """Atomically create or reclaim an expired tenant-scoped idempotency key."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        now = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            expires_at = now.replace(microsecond=0) + timedelta(seconds=_MIN_IDEMPOTENCY_TTL_SECONDS)
        with self._conn() as conn:
            claimed = conn.execute(
                """
                INSERT INTO invoice_idempotency_records
                    (tenant_id, idempotency_key, request_fingerprint, resource_id, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, idempotency_key) DO UPDATE
                SET request_fingerprint = EXCLUDED.request_fingerprint,
                    resource_id = EXCLUDED.resource_id,
                    state = 'pending',
                    canonical_response_json = NULL,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = NOW()
                WHERE invoice_idempotency_records.expires_at <= NOW()
                RETURNING tenant_id, idempotency_key, request_fingerprint, resource_id,
                          state, canonical_response_json, expires_at, created_at, updated_at
                """,
                (tenant_id, idempotency_key, request_fingerprint, resource_id, expires_at),
            ).fetchone()
            if claimed is not None:
                return True, self._idempotency_from_row(claimed)

            existing = conn.execute(
                """
                SELECT tenant_id, idempotency_key, request_fingerprint, resource_id,
                       state, canonical_response_json, expires_at, created_at, updated_at
                FROM invoice_idempotency_records
                WHERE tenant_id = %s AND idempotency_key = %s
                """,
                (tenant_id, idempotency_key),
            ).fetchone()
            if existing is None:
                raise RuntimeError("idempotency record disappeared before it could be read")
            return False, self._idempotency_from_row(existing)

    def complete_idempotency_record(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        resource_id: str,
        canonical_response: dict,
    ) -> bool:
        """Store the canonical completed response only for the original owner."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_idempotency_records
                SET state = 'completed', canonical_response_json = %s::jsonb, updated_at = %s
                WHERE tenant_id = %s
                  AND idempotency_key = %s
                  AND request_fingerprint = %s
                  AND resource_id = %s
                  AND state = 'pending'
                RETURNING tenant_id
                """,
                (
                    self._json(canonical_response),
                    datetime.now(timezone.utc),
                    tenant_id,
                    idempotency_key,
                    request_fingerprint,
                    resource_id,
                ),
            ).fetchone()
        return row is not None

    def release_idempotency_record(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        resource_id: str,
    ) -> bool:
        """Release only this pending owner after an extraction transaction aborts."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                DELETE FROM invoice_idempotency_records
                WHERE tenant_id = %s
                  AND idempotency_key = %s
                  AND request_fingerprint = %s
                  AND resource_id = %s
                  AND state = 'pending'
                RETURNING tenant_id
                """,
                (tenant_id, idempotency_key, request_fingerprint, resource_id),
            ).fetchone()
        return row is not None

    def create_extraction_job_and_complete_idempotency(
        self,
        *,
        job_id: str,
        tenant_id: str,
        source_key: str,
        source_file_hash: str,
        content_type: str,
        ocr_lang: str | None,
        idempotency_key: str,
        request_fingerprint: str,
        canonical_response: dict,
    ) -> str:
        """Atomically queue an artifact-backed extraction job and its durable response."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO invoice_extraction_jobs
                    (id, tenant_id, source_key, source_file_hash, content_type, ocr_lang)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (job_id, tenant_id, source_key, source_file_hash, content_type, ocr_lang),
            )
            self._enqueue_outbox(
                conn,
                tenant_id=tenant_id,
                invoice_id=None,
                event_type="document.extraction_requested",
                payload={
                    "job_id": job_id,
                    "source_key": source_key,
                    "content_type": content_type,
                    "ocr_lang": ocr_lang,
                },
            )
            completed = conn.execute(
                """
                UPDATE invoice_idempotency_records
                SET state = 'completed', canonical_response_json = %s::jsonb, updated_at = %s
                WHERE tenant_id = %s
                  AND idempotency_key = %s
                  AND request_fingerprint = %s
                  AND resource_id = %s
                  AND state = 'pending'
                RETURNING tenant_id
                """,
                (
                    self._json(canonical_response),
                    datetime.now(timezone.utc),
                    tenant_id,
                    idempotency_key,
                    request_fingerprint,
                    job_id,
                ),
            ).fetchone()
            if completed is None:
                raise RuntimeError("idempotency claim was not owned by this extraction job")
        return job_id

    def get_extraction_job(self, job_id: str, *, tenant_id: str) -> dict | None:
        """Read a tenant-scoped durable extraction job without its source bytes."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, tenant_id, source_key, source_file_hash, content_type, ocr_lang,
                       status, document_id, result_json, error, attempts, claimed_until, lease_token,
                       created_at, updated_at, completed_at
                FROM invoice_extraction_jobs
                WHERE id = %s AND tenant_id = %s
                """,
                (job_id, tenant_id),
            ).fetchone()
        return self._extraction_job_from_row(row) if row is not None else None

    def claim_extraction_job(
        self,
        job_id: str,
        *,
        tenant_id: str,
        lease_seconds: int = 300,
    ) -> dict | None:
        """Lease queued or abandoned work for exactly one worker."""
        tenant_id = self._tenant_id(tenant_id)
        lease_seconds = max(1, int(lease_seconds))
        lease_token = uuid.uuid4().hex
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_extraction_jobs
                SET status = 'running',
                    attempts = attempts + 1,
                    claimed_until = NOW() + (%s * INTERVAL '1 second'),
                    lease_token = %s,
                    error = NULL,
                    updated_at = NOW()
                WHERE id = %s
                  AND tenant_id = %s
                  AND (
                    status = 'queued'
                    OR (status = 'running' AND claimed_until <= NOW())
                  )
                RETURNING id, tenant_id, source_key, source_file_hash, content_type, ocr_lang,
                          status, document_id, result_json, error, attempts, claimed_until, lease_token,
                          created_at, updated_at, completed_at
                """,
                (lease_seconds, lease_token, job_id, tenant_id),
            ).fetchone()
        return self._extraction_job_from_row(row) if row is not None else None

    def has_active_extraction_job_claim(self, job_id: str, *, tenant_id: str) -> bool:
        """Tell a Kafka worker whether another live lease owns this job."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM invoice_extraction_jobs
                WHERE id = %s
                  AND tenant_id = %s
                  AND status = 'running'
                  AND claimed_until > NOW()
                """,
                (job_id, tenant_id),
            ).fetchone()
        return row is not None

    def list_expired_extraction_jobs(self, *, limit: int = 100) -> list[dict]:
        """Return abandoned running jobs so recovery does not depend on Kafka replay."""
        self.ensure_schema()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, tenant_id
                FROM invoice_extraction_jobs
                WHERE status = 'running'
                  AND claimed_until <= NOW()
                ORDER BY claimed_until ASC, created_at ASC
                LIMIT %s
                """,
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [{"job_id": row[0], "tenant_id": row[1]} for row in rows]

    def renew_extraction_job_claim(
        self,
        job_id: str,
        *,
        tenant_id: str,
        lease_token: str,
        lease_seconds: int = 300,
    ) -> bool:
        """Extend only the current, still-live extraction claim."""
        tenant_id = self._tenant_id(tenant_id)
        lease_seconds = max(1, int(lease_seconds))
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_extraction_jobs
                SET claimed_until = NOW() + (%s * INTERVAL '1 second'),
                    updated_at = NOW()
                WHERE id = %s
                  AND tenant_id = %s
                  AND status = 'running'
                  AND lease_token = %s
                  AND claimed_until > NOW()
                RETURNING id
                """,
                (lease_seconds, job_id, tenant_id, lease_token),
            ).fetchone()
        return row is not None

    def complete_extraction_job(
        self,
        job_id: str,
        *,
        tenant_id: str,
        lease_token: str,
        document_id: str,
        result: dict,
    ) -> bool:
        """Complete only a claimed job after its document/outbox transaction commits."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_extraction_jobs
                SET status = 'completed', document_id = %s, result_json = %s::jsonb,
                    error = NULL, claimed_until = NULL, lease_token = NULL,
                    completed_at = NOW(), updated_at = NOW()
                WHERE id = %s
                  AND tenant_id = %s
                  AND status = 'running'
                  AND lease_token = %s
                  AND claimed_until > NOW()
                RETURNING id
                """,
                (document_id, self._json(result), job_id, tenant_id, lease_token),
            ).fetchone()
        return row is not None

    def complete_extraction_job_and_store_invoices(
        self,
        job_id: str,
        *,
        tenant_id: str,
        lease_token: str,
        invoice_writes: list[dict],
        result: dict,
    ) -> bool:
        """Commit extracted invoices only while this worker owns the live job lease."""
        tenant_id = self._tenant_id(tenant_id)
        if not invoice_writes:
            raise ValueError("invoice_writes must not be empty")
        self.ensure_schema()
        with self._conn() as conn:
            claimed = conn.execute(
                """
                SELECT id
                FROM invoice_extraction_jobs
                WHERE id = %s
                  AND tenant_id = %s
                  AND status = 'running'
                  AND lease_token = %s
                  AND claimed_until > NOW()
                FOR UPDATE
                """,
                (job_id, tenant_id, lease_token),
            ).fetchone()
            if claimed is None:
                return False
            for write in invoice_writes:
                self._insert_invoice(
                    conn,
                    write["invoice_data"],
                    tenant_id=tenant_id,
                    invoice_id=write["invoice_id"],
                    actor=write.get("actor", "system"),
                    reason=write.get("reason", ""),
                )
            completed = conn.execute(
                """
                UPDATE invoice_extraction_jobs
                SET status = 'completed',
                    document_id = %s,
                    result_json = %s::jsonb,
                    error = NULL,
                    claimed_until = NULL,
                    lease_token = NULL,
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                  AND tenant_id = %s
                  AND status = 'running'
                  AND lease_token = %s
                  AND claimed_until > NOW()
                RETURNING id
                """,
                (
                    invoice_writes[0]["invoice_id"],
                    self._json(result),
                    job_id,
                    tenant_id,
                    lease_token,
                ),
            ).fetchone()
            if completed is None:
                raise RuntimeError("extraction job claim was lost before completion")
        return True

    def fail_extraction_job(
        self,
        job_id: str,
        *,
        tenant_id: str,
        lease_token: str,
        error: str,
        retry: bool = False,
    ) -> bool:
        """Release retryable failures or make terminal failure durable."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_extraction_jobs
                SET status = %s, error = %s, claimed_until = NULL, lease_token = NULL,
                    completed_at = CASE WHEN %s THEN NULL ELSE NOW() END,
                    updated_at = NOW()
                WHERE id = %s
                  AND tenant_id = %s
                  AND status = 'running'
                  AND lease_token = %s
                  AND claimed_until > NOW()
                RETURNING id
                """,
                ("queued" if retry else "failed", error[:2000], retry, job_id, tenant_id, lease_token),
            ).fetchone()
        return row is not None

    def cancel_extraction_job(self, job_id: str, *, tenant_id: str) -> bool:
        """Cancel only queued/running tenant work; completed jobs remain immutable."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_extraction_jobs
                SET status = 'cancelled', claimed_until = NULL, lease_token = NULL,
                    artifact_cleanup_keys = COALESCE(
                        artifact_cleanup_keys,
                        '[]'::jsonb
                    ) || jsonb_build_array(source_key),
                    artifact_cleanup_pending = TRUE, updated_at = NOW(), completed_at = NOW()
                WHERE id = %s
                  AND tenant_id = %s
                  AND status IN ('queued', 'running')
                RETURNING id
                """,
                (job_id, tenant_id),
            ).fetchone()
        return row is not None

    def add_extraction_job_artifact_cleanup(
        self,
        job_id: str,
        *,
        tenant_id: str,
        keys: list[str],
    ) -> bool:
        """Durably retain generated keys that a cancelled worker must delete."""
        tenant_id = self._tenant_id(tenant_id)
        keys = [key for key in keys if isinstance(key, str) and key]
        if not keys:
            return True
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_extraction_jobs
                SET artifact_cleanup_keys = artifact_cleanup_keys || %s::jsonb,
                    artifact_cleanup_pending = TRUE, updated_at = NOW()
                WHERE id = %s AND tenant_id = %s AND status = 'cancelled'
                RETURNING id
                """,
                (self._json(keys), job_id, tenant_id),
            ).fetchone()
        return row is not None

    def journal_extraction_job_artifacts(
        self,
        job_id: str,
        *,
        tenant_id: str,
        lease_token: str,
        keys: list[str],
    ) -> bool:
        """Persist derived artifact candidates before object storage writes."""
        tenant_id = self._tenant_id(tenant_id)
        keys = [key for key in keys if isinstance(key, str) and key]
        if not keys:
            return True
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_extraction_jobs
                SET artifact_cleanup_keys = artifact_cleanup_keys || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                  AND tenant_id = %s
                  AND status = 'running'
                  AND lease_token = %s
                  AND claimed_until > NOW()
                RETURNING id
                """,
                (self._json(keys), job_id, tenant_id, lease_token),
            ).fetchone()
        return row is not None

    def list_cancelled_extraction_jobs_for_cleanup(self, *, limit: int = 100) -> list[dict]:
        """Return durable artifact-cleanup tombstones for the extraction worker."""
        self.ensure_schema()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, tenant_id, artifact_cleanup_keys
                FROM invoice_extraction_jobs
                WHERE status = 'cancelled' AND artifact_cleanup_pending = TRUE
                ORDER BY updated_at ASC
                LIMIT %s
                """,
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [
            {"job_id": row[0], "tenant_id": row[1], "artifact_cleanup_keys": row[2] or []}
            for row in rows
        ]

    def complete_extraction_job_artifact_cleanup(
        self,
        job_id: str,
        *,
        tenant_id: str,
        keys: list[str],
    ) -> bool:
        """Clear a tombstone only when its key snapshot was fully deleted."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_extraction_jobs
                SET artifact_cleanup_pending = FALSE, updated_at = NOW()
                WHERE id = %s
                  AND tenant_id = %s
                  AND status = 'cancelled'
                  AND artifact_cleanup_pending = TRUE
                  AND artifact_cleanup_keys @> %s::jsonb
                  AND %s::jsonb @> artifact_cleanup_keys
                RETURNING id
                """,
                (job_id, tenant_id, self._json(keys), self._json(keys)),
            ).fetchone()
        return row is not None

    def save_search_chunks(
        self,
        invoice_id: str,
        *,
        tenant_id: str,
        chunks: list[dict],
    ) -> None:
        """Replace one document's tenant-scoped search projection transactionally."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            self._replace_search_chunks(
                conn,
                invoice_id=invoice_id,
                tenant_id=tenant_id,
                chunks=chunks,
            )

    def _replace_search_chunks(
        self,
        conn,
        *,
        invoice_id: str,
        tenant_id: str,
        chunks: list[dict],
    ) -> None:
        conn.execute(
            "DELETE FROM invoice_search_chunks WHERE tenant_id = %s AND invoice_id = %s",
            (tenant_id, invoice_id),
        )
        for index, chunk in enumerate(chunks):
            conn.execute(
                """
                INSERT INTO invoice_search_chunks
                    (tenant_id, invoice_id, chunk_index, content, metadata_json)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (
                    tenant_id,
                    invoice_id,
                    index,
                    str(chunk.get("content", "")),
                    self._json(chunk.get("metadata") or {}),
                ),
            )

    def list_search_chunks(self, invoice_id: str, *, tenant_id: str) -> list[dict]:
        """Return a document's durable projection only inside its tenant."""
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT chunk_index, content, metadata_json
                FROM invoice_search_chunks
                WHERE tenant_id = %s AND invoice_id = %s
                ORDER BY chunk_index ASC
                """,
                (tenant_id, invoice_id),
            ).fetchall()
        return [
            {"chunk_index": row[0], "content": row[1], "metadata": row[2]}
            for row in rows
        ]

    def search_search_chunks(
        self,
        *,
        tenant_id: str,
        terms: list[str],
        limit: int,
    ) -> list[dict]:
        """Rank tenant chunks by the fraction of query terms they contain."""
        tenant_id = self._tenant_id(tenant_id)
        terms = list(dict.fromkeys(term.casefold() for term in terms if term.strip()))
        if not terms:
            return []
        limit = max(1, min(int(limit), 200))
        match_clauses = ["LOWER(content) LIKE %s" for _ in terms]
        score_clauses = [
            "CASE WHEN LOWER(content) LIKE %s THEN 1 ELSE 0 END"
            for _ in terms
        ]
        patterns = [f"%{term}%" for term in terms]
        self.ensure_schema()
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT invoice_id, chunk_index, content, metadata_json,
                       ({' + '.join(score_clauses)})::DOUBLE PRECISION / %s AS score
                FROM invoice_search_chunks
                WHERE tenant_id = %s
                  AND ({' OR '.join(match_clauses)})
                ORDER BY score DESC, invoice_id ASC, chunk_index ASC
                LIMIT %s
                """,
                (*patterns, len(terms), tenant_id, *patterns, limit),
            ).fetchall()
        return [
            {
                "invoice_id": row[0],
                "chunk_index": row[1],
                "content": row[2],
                "metadata": row[3],
                "score": float(row[4]),
            }
            for row in rows
        ]

    def delete_search_chunks(self, invoice_id: str, *, tenant_id: str) -> bool:
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            result = conn.execute(
                "DELETE FROM invoice_search_chunks WHERE tenant_id = %s AND invoice_id = %s",
                (tenant_id, invoice_id),
            )
        return result.rowcount > 0

    def subscribe_webhook(
        self,
        *,
        subscription_id: str,
        tenant_id: str,
        url: str,
        event_types: list[str],
        secret: str | None = None,
    ) -> str:
        """Create one tenant-scoped webhook subscription."""
        tenant_id = self._tenant_id(tenant_id)
        if not url or not event_types:
            raise ValueError("url and event_types must be non-empty")
        self.ensure_schema()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO invoice_webhook_subscriptions
                    (id, tenant_id, url, event_types_json, secret)
                VALUES (%s, %s, %s, %s::jsonb, %s)
                """,
                (subscription_id, tenant_id, url, self._json(event_types), secret),
            )
        return subscription_id

    def list_webhook_subscriptions(
        self,
        *,
        tenant_id: str,
        event_type: str | None = None,
    ) -> list[dict]:
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        query = """
            SELECT id, tenant_id, url, event_types_json, secret, active, created_at, updated_at
            FROM invoice_webhook_subscriptions
            WHERE tenant_id = %s AND active = TRUE
        """
        params: list[object] = [tenant_id]
        if event_type is not None:
            query += " AND event_types_json @> %s::jsonb"
            params.append(self._json([event_type]))
        query += " ORDER BY created_at ASC, id ASC"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "id": row[0],
                "tenant_id": row[1],
                "url": row[2],
                "event_types": row[3],
                "secret": row[4],
                "active": row[5],
                "created_at": row[6],
                "updated_at": row[7],
            }
            for row in rows
        ]

    def unsubscribe_webhook(self, subscription_id: str, *, tenant_id: str) -> bool:
        tenant_id = self._tenant_id(tenant_id)
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_webhook_subscriptions
                SET active = FALSE, updated_at = NOW()
                WHERE id = %s AND tenant_id = %s AND active = TRUE
                RETURNING id
                """,
                (subscription_id, tenant_id),
            ).fetchone()
        return row is not None

    def record_webhook_delivery(
        self,
        *,
        event_id: str,
        subscription_id: str,
        status: str,
        response_code: int | None = None,
        error: str | None = None,
    ) -> bool:
        """Upsert delivery state; duplicate Kafka events increase attempts, not rows."""
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                INSERT INTO invoice_webhook_deliveries
                    (event_id, subscription_id, status, response_code, error, delivered_at)
                VALUES (%s, %s, %s, %s, %s, CASE WHEN %s = 'delivered' THEN NOW() ELSE NULL END)
                ON CONFLICT (event_id, subscription_id) DO UPDATE
                SET status = EXCLUDED.status,
                    attempts = invoice_webhook_deliveries.attempts + 1,
                    response_code = EXCLUDED.response_code,
                    error = EXCLUDED.error,
                    delivered_at = CASE
                        WHEN EXCLUDED.status = 'delivered' THEN NOW()
                        ELSE invoice_webhook_deliveries.delivered_at
                    END,
                    updated_at = NOW()
                RETURNING id
                """,
                (event_id, subscription_id, status, response_code, error, status),
            ).fetchone()
        return row is not None

    def claim_webhook_delivery(
        self,
        *,
        event_id: str,
        subscription_id: str,
        lease_seconds: int = 30,
    ) -> str | None:
        """Claim a webhook attempt with a fencing token before sending."""
        if not event_id or not subscription_id:
            raise ValueError("event_id and subscription_id must be non-empty")
        lease_seconds = max(1, int(lease_seconds))
        lease_token = uuid.uuid4().hex
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_webhook_deliveries
                SET status = 'processing',
                    attempts = invoice_webhook_deliveries.attempts + 1,
                    claimed_until = NOW() + (%s * INTERVAL '1 second'),
                    lease_token = %s,
                    error = NULL,
                    updated_at = NOW()
                WHERE event_id = %s
                  AND subscription_id = %s
                  AND status != 'delivered'
                  AND (
                    claimed_until IS NULL
                    OR claimed_until <= NOW()
                  )
                RETURNING lease_token
                """,
                (lease_seconds, lease_token, event_id, subscription_id),
            ).fetchone()
        return row[0] if row is not None else None

    def list_pending_webhook_subscriptions(self, event_id: str) -> list[dict]:
        """Return active subscriptions with a materialized retryable delivery intent."""
        self.ensure_schema()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT subscription.id, subscription.tenant_id, subscription.url,
                       subscription.event_types_json, subscription.secret, subscription.active
                FROM invoice_webhook_deliveries AS delivery
                JOIN invoice_webhook_subscriptions AS subscription
                  ON subscription.id = delivery.subscription_id
                WHERE delivery.event_id = %s
                  AND subscription.active = TRUE
                  AND delivery.status != 'delivered'
                  AND (
                      delivery.claimed_until IS NULL
                      OR delivery.claimed_until <= NOW()
                  )
                ORDER BY subscription.created_at ASC, subscription.id ASC
                """,
                (event_id,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "tenant_id": row[1],
                "url": row[2],
                "event_types": row[3],
                "secret": row[4],
                "active": row[5],
            }
            for row in rows
        ]

    def complete_webhook_delivery(
        self,
        *,
        event_id: str,
        subscription_id: str,
        lease_token: str,
        response_code: int | None = None,
    ) -> bool:
        """Mark delivery only after the HTTP sender reports a successful response."""
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_webhook_deliveries
                SET status = 'delivered', response_code = %s, error = NULL,
                    claimed_until = NULL, lease_token = NULL, delivered_at = NOW(), updated_at = NOW()
                WHERE event_id = %s AND subscription_id = %s AND status = 'processing'
                  AND lease_token = %s
                  AND claimed_until > NOW()
                RETURNING id
                """,
                (response_code, event_id, subscription_id, lease_token),
            ).fetchone()
        return row is not None

    def release_webhook_delivery(
        self,
        *,
        event_id: str,
        subscription_id: str,
        lease_token: str,
        error: str,
        response_code: int | None = None,
    ) -> bool:
        """Release a failed sender lease for safe retry without losing its receipt."""
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_webhook_deliveries
                SET status = 'pending', response_code = %s, error = %s,
                    claimed_until = NULL, lease_token = NULL, updated_at = NOW()
                WHERE event_id = %s AND subscription_id = %s AND status = 'processing'
                  AND lease_token = %s
                  AND claimed_until > NOW()
                RETURNING id
                """,
                (response_code, error[:2000], event_id, subscription_id, lease_token),
            ).fetchone()
        return row is not None

    def list_pending_webhook_events(self, *, limit: int = 100) -> list[dict]:
        """Return pending delivery events for retry without replaying projections."""
        self.ensure_schema()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT outbox.id, outbox.tenant_id, outbox.invoice_id, outbox.event_type,
                       outbox.payload_json, outbox.created_at
                FROM invoice_outbox AS outbox
                WHERE outbox.invoice_id IS NOT NULL
                  AND EXISTS (
                      SELECT 1
                      FROM invoice_webhook_deliveries AS delivery
                      JOIN invoice_webhook_subscriptions AS subscription
                        ON subscription.id = delivery.subscription_id
                      WHERE delivery.event_id = outbox.id
                        AND subscription.active = TRUE
                        AND delivery.status != 'delivered'
                        AND (
                            delivery.claimed_until IS NULL
                            OR delivery.claimed_until <= NOW()
                        )
                  )
                ORDER BY outbox.created_at ASC
                LIMIT %s
                """,
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [
            {
                "event_id": row[0],
                "tenant_id": row[1],
                "invoice_id": row[2],
                "event_type": row[3],
                "payload": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

    @staticmethod
    def _extraction_job_from_row(row) -> dict:
        return {
            "job_id": row[0],
            "tenant_id": row[1],
            "source_key": row[2],
            "source_file_hash": row[3],
            "content_type": row[4],
            "ocr_lang": row[5],
            "status": row[6],
            "document_id": row[7],
            "result": row[8],
            "error": row[9],
            "attempts": row[10],
            "claimed_until": row[11],
            "lease_token": row[12],
            "created_at": row[13],
            "updated_at": row[14],
            "completed_at": row[15],
        }

    @staticmethod
    def _idempotency_from_row(row) -> dict:
        return {
            "tenant_id": row[0],
            "idempotency_key": row[1],
            "request_fingerprint": row[2],
            "resource_id": row[3],
            "state": row[4],
            "canonical_response_json": row[5],
            "expires_at": row[6],
            "created_at": row[7],
            "updated_at": row[8],
        }

    def list_pending_outbox(self, limit: int = 100) -> list[dict]:
        """Read unpublished delivery intents for a dispatcher to claim later."""
        self.ensure_schema()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, tenant_id, invoice_id, event_type, payload_json, created_at, publish_attempts
                FROM invoice_outbox
                WHERE published_at IS NULL
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "tenant_id": row[1],
                "invoice_id": row[2],
                "event_type": row[3],
                "payload_json": row[4],
                "created_at": row[5],
                "publish_attempts": row[6],
            }
            for row in rows
        ]

    def claim_pending_outbox(
        self,
        limit: int = 100,
        lease_seconds: int = 30,
    ) -> list[dict]:
        """Lease unpublished events for one publisher without blocking other publishers."""
        limit = max(1, min(int(limit), 500))
        lease_seconds = max(1, int(lease_seconds))
        lease_token = uuid.uuid4().hex
        self.ensure_schema()
        with self._conn() as conn:
            rows = conn.execute(
                """
                WITH claimable AS (
                    SELECT id
                    FROM invoice_outbox
                    WHERE published_at IS NULL
                      AND (claimed_until IS NULL OR claimed_until <= NOW())
                    ORDER BY created_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE invoice_outbox AS outbox
                SET claimed_until = NOW() + (%s * INTERVAL '1 second'),
                    lease_token = %s,
                    publish_attempts = outbox.publish_attempts + 1,
                    last_error = NULL
                FROM claimable
                WHERE outbox.id = claimable.id
                RETURNING outbox.id, outbox.tenant_id, outbox.invoice_id, outbox.event_type,
                          outbox.payload_json, outbox.created_at, outbox.publish_attempts,
                          outbox.lease_token
                """,
                (limit, lease_seconds, lease_token),
            ).fetchall()
        return [
            {
                "id": row[0],
                "tenant_id": row[1],
                "invoice_id": row[2],
                "event_type": row[3],
                "payload_json": row[4],
                "created_at": row[5],
                "publish_attempts": row[6],
                "lease_token": row[7],
            }
            for row in rows
        ]

    def mark_outbox_published(self, event_id: str, lease_token: str) -> bool:
        """Mark an event delivered after the broker accepts the envelope."""
        if not lease_token:
            raise ValueError("lease_token is required")
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_outbox
                SET published_at = NOW(), claimed_until = NULL, lease_token = NULL, last_error = NULL
                WHERE id = %s AND published_at IS NULL
                  AND lease_token = %s
                  AND claimed_until > NOW()
                RETURNING id
                """,
                (event_id, lease_token),
            ).fetchone()
        return row is not None

    def release_outbox_claim(self, event_id: str, lease_token: str, error: str = "") -> bool:
        """Release a failed delivery for retry without marking it published."""
        if not lease_token:
            raise ValueError("lease_token is required")
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_outbox
                SET claimed_until = NULL, lease_token = NULL, last_error = %s
                WHERE id = %s AND published_at IS NULL
                  AND lease_token = %s
                  AND claimed_until > NOW()
                RETURNING id
                """,
                (error[:2000], event_id, lease_token),
            ).fetchone()
        return row is not None

    def claim_consumer_receipt(
        self,
        event_id: str,
        consumer: str,
        lease_seconds: int = 30,
    ) -> str | None:
        """Lease one consumer effect with a fencing token."""
        if not event_id or not consumer:
            raise ValueError("event_id and consumer must be non-empty strings")
        lease_seconds = max(1, int(lease_seconds))
        lease_token = uuid.uuid4().hex
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                INSERT INTO invoice_consumer_receipts
                    (event_id, consumer, state, claimed_until, lease_token)
                VALUES (%s, %s, 'processing', NOW() + (%s * INTERVAL '1 second'), %s)
                ON CONFLICT (event_id, consumer) DO UPDATE
                SET state = 'processing',
                    claimed_until = NOW() + (%s * INTERVAL '1 second'),
                    lease_token = EXCLUDED.lease_token,
                    last_error = NULL
                WHERE invoice_consumer_receipts.state != 'completed'
                  AND (
                    invoice_consumer_receipts.claimed_until IS NULL
                    OR invoice_consumer_receipts.claimed_until <= NOW()
                  )
                RETURNING lease_token
                """,
                (event_id, consumer, lease_seconds, lease_token, lease_seconds),
            ).fetchone()
        return row[0] if row is not None else None

    def has_active_consumer_receipt(self, event_id: str, consumer: str) -> bool:
        """Tell a Kafka worker whether another live receipt lease owns this event."""
        if not event_id or not consumer:
            raise ValueError("event_id and consumer must be non-empty strings")
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM invoice_consumer_receipts
                WHERE event_id = %s
                  AND consumer = %s
                  AND state = 'processing'
                  AND claimed_until > NOW()
                """,
                (event_id, consumer),
            ).fetchone()
        return row is not None

    def complete_consumer_receipt(self, event_id: str, consumer: str, lease_token: str) -> bool:
        """Commit the consumer effect only for its current fenced owner."""
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_consumer_receipts
                SET state = 'completed', claimed_until = NULL, lease_token = NULL, last_error = NULL
                WHERE event_id = %s AND consumer = %s AND state = 'processing'
                  AND lease_token = %s
                  AND claimed_until > NOW()
                RETURNING event_id
                """,
                (event_id, consumer, lease_token),
            ).fetchone()
        return row is not None

    def release_consumer_receipt(
        self,
        event_id: str,
        consumer: str,
        lease_token: str,
        error: str = "",
    ) -> bool:
        """Release only the caller's current consumer lease for retry."""
        self.ensure_schema()
        with self._conn() as conn:
            row = conn.execute(
                """
                UPDATE invoice_consumer_receipts
                SET state = 'pending', claimed_until = NULL, lease_token = NULL, last_error = %s
                WHERE event_id = %s AND consumer = %s AND state = 'processing'
                  AND lease_token = %s
                  AND claimed_until > NOW()
                RETURNING event_id
                """,
                (error[:2000], event_id, consumer, lease_token),
            ).fetchone()
        return row is not None

    def complete_consumer_receipt_and_save_search_chunks(
        self,
        event_id: str,
        consumer: str,
        lease_token: str,
        *,
        invoice_id: str,
        tenant_id: str,
        event_type: str,
        chunks: list[dict],
    ) -> bool:
        """Commit a durable search projection with its fenced consumer receipt."""
        tenant_id = self._tenant_id(tenant_id)
        if not lease_token:
            raise ValueError("lease_token is required")
        self.ensure_schema()
        with self._conn() as conn:
            completed = conn.execute(
                """
                UPDATE invoice_consumer_receipts
                SET state = 'completed', claimed_until = NULL, lease_token = NULL, last_error = NULL
                WHERE event_id = %s AND consumer = %s AND state = 'processing'
                  AND lease_token = %s
                  AND claimed_until > NOW()
                RETURNING event_id
                """,
                (event_id, consumer, lease_token),
            ).fetchone()
            if completed is None:
                return False
            self._replace_search_chunks(
                conn,
                invoice_id=invoice_id,
                tenant_id=tenant_id,
                chunks=chunks,
            )
            conn.execute(
                """
                INSERT INTO invoice_webhook_deliveries
                    (event_id, subscription_id, status, attempts)
                SELECT %s, subscription.id, 'pending', 0
                FROM invoice_webhook_subscriptions AS subscription
                WHERE subscription.tenant_id = %s
                  AND subscription.active = TRUE
                  AND subscription.event_types_json @> %s::jsonb
                ON CONFLICT (event_id, subscription_id) DO NOTHING
                """,
                (event_id, tenant_id, self._json([event_type])),
            )
        return True

    def close(self) -> None:
        """Close the connection pool. Call on application shutdown."""
        self._pool.close()


_invoice_repository: InvoiceRepository | None = None


def get_invoice_repository() -> InvoiceRepository:
    global _invoice_repository
    if _invoice_repository is None:
        _invoice_repository = InvoiceRepository()
    return _invoice_repository
