"""Tests for invoice repository (PostgreSQL storage and audit logs)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.repositories.invoice_repository import InvoiceRepository, ReviewStatus


def _make_repo():
    """Create an InvoiceRepository with a fully mocked pool, bypassing __init__."""
    repo = object.__new__(InvoiceRepository)
    mock_pool = MagicMock()
    repo._pool = mock_pool
    return repo, mock_pool


def _mock_conn():
    """Return a context-manager mock that yields a connection."""
    conn = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, conn

class _TransactionalCursor:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row

class _TransactionalConnection:
    def __init__(self, fail_on_invoice: int | None = None):
        self.fail_on_invoice = fail_on_invoice
        self.invoice_inserts = 0
        self.staged_invoice_ids: list[str] = []
        self.committed_invoice_ids: list[str] = []
        self.statements: list[str] = []

    def execute(self, statement, params=None):
        self.statements.append(statement)
        if "INSERT INTO invoices" in statement:
            self.invoice_inserts += 1
            if self.fail_on_invoice == self.invoice_inserts:
                raise RuntimeError("later page insert failed")
            self.staged_invoice_ids.append(params[0])
        return _TransactionalCursor(("tenant-a",))

class _TransactionalContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, _exc, _traceback):
        if exc_type is None:
            self.connection.committed_invoice_ids.extend(self.connection.staged_invoice_ids)
        self.connection.staged_invoice_ids.clear()
        return False


def _invoice_row(
    *,
    tenant_id: str = "tenant-a",
    version: int = 3,
    issuer_name: str = "Acme",
    review_status: str = "needs_review",
):
    return (
        "inv_123",
        tenant_id,
        None,
        None,
        issuer_name,
        None,
        None,
        None,
        5000,
        None,
        {"issuer_name": issuer_name},
        {"is_valid": True},
        review_status,
        version,
        "2025-01-01",
        "2025-01-01",
    )


class TestTableCreation:
    def test_ensure_schema_executes_durable_ddl(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx

        repo.ensure_schema()

        statements = [call.args[0] for call in conn.execute.call_args_list]
        assert any("invoice_idempotency_records" in statement for statement in statements)
        assert any("invoice_outbox" in statement for statement in statements)
        assert any("invoice_consumer_receipts" in statement for statement in statements)
        assert any(
            "invoice_extraction_jobs" in statement and "lease_token" in statement
            for statement in statements
        )
        assert any("document_version" in statement for statement in statements)


class TestSaveAndGetInvoice:
    def test_save_returns_id_and_tenant_scoped_outbox_intent(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx

        invoice_id = repo.save_invoice(
            {
                "source": {"file_path": "test.pdf"},
                "raw_ocr": {"results": []},
                "extracted": {"issuer_name": "Acme Corp", "total_amount": 5000},
                "validation": {"is_valid": True},
            },
            tenant_id="tenant-a",
        )

        assert invoice_id.startswith("inv_")
        insert_calls = [
            call for call in conn.execute.call_args_list if "INSERT INTO invoices" in call.args[0]
        ]
        assert insert_calls[0].args[1][1] == "tenant-a"
        outbox_calls = [
            call for call in conn.execute.call_args_list if "INSERT INTO invoice_outbox" in call.args[0]
        ]
        assert outbox_calls[0].args[1][1] == "tenant-a"
        assert outbox_calls[0].args[1][3] == "document.extraction_completed"
        audit_calls = [
            call for call in conn.execute.call_args_list if "INSERT INTO invoice_audit_logs" in call.args[0]
        ]
        assert audit_calls[0].args[1][2] == "system"
        assert audit_calls[0].args[1][4] == 1

    def test_get_invoice_returns_none_for_missing(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = None

        result = repo.get_invoice("inv_nonexistent", tenant_id="tenant-a")

        assert result is None
        select_call = conn.execute.call_args_list[-1]
        assert select_call.args[1] == ("inv_nonexistent", "tenant-a")

    def test_get_invoice_returns_versioned_tenant_scoped_dict(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = _invoice_row()

        result = repo.get_invoice("inv_123", tenant_id="tenant-a")

        assert result is not None
        assert result["id"] == "inv_123"
        assert result["tenant_id"] == "tenant-a"
        assert result["document_version"] == 3
        assert result["total_amount"] == 5000


class TestUpdateWithAuditLog:
    def test_update_writes_transactional_full_snapshots_and_outbox(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.side_effect = [_invoice_row(), (4,)]

        ok = repo.update_invoice(
            "inv_123",
            {"issuer_name": "New Name", "review_status": ReviewStatus.REVIEWED},
            actor="reviewer",
            reason="Corrected name",
            tenant_id="tenant-a",
            expected_version=3,
        )

        assert ok is True
        statements = [call.args[0] for call in conn.execute.call_args_list]
        assert any("FOR UPDATE" in statement for statement in statements)
        assert any("document_version = document_version + 1" in statement for statement in statements)
        audit_call = next(
            call for call in conn.execute.call_args_list if "INSERT INTO invoice_audit_logs" in call.args[0]
        )
        before_snapshot = audit_call.args[1][4]
        after_snapshot = audit_call.args[1][5]
        assert '"issuer_name": "Acme"' in before_snapshot
        assert '"issuer_name": "New Name"' in after_snapshot
        assert audit_call.args[1][6:8] == (3, 4)
        assert audit_call.args[1][3] == "update_fields"
        outbox_call = next(
            call for call in conn.execute.call_args_list if "INSERT INTO invoice_outbox" in call.args[0]
        )
        assert outbox_call.args[1][3] == "document.review_completed"

    def test_update_rejects_stale_version_without_writing_audit(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = _invoice_row(version=4)

        ok = repo.update_invoice(
            "inv_123",
            {"issuer_name": "New Name"},
            tenant_id="tenant-a",
            expected_version=3,
        )

        assert ok is False
        statements = [call.args[0] for call in conn.execute.call_args_list]
        assert not any("UPDATE invoices" in statement for statement in statements)
        assert not any("INSERT INTO invoice_audit_logs" in statement for statement in statements)

    def test_update_nonexistent_returns_false(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = None

        ok = repo.update_invoice("inv_bad", {"issuer_name": "X"}, tenant_id="tenant-a")

        assert ok is False


class TestAuditLog:
    def test_get_audit_log_is_tenant_scoped(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchall.return_value = [
            (1, "inv_123", "tenant-a", "api", "update_fields", None, None, 2, 3, "fix", "2025-01-01"),
        ]

        logs = repo.get_audit_log("inv_123", tenant_id="tenant-a")

        assert len(logs) == 1
        assert logs[0]["tenant_id"] == "tenant-a"
        assert logs[0]["before_version"] == 2
        select_call = conn.execute.call_args_list[-1]
        assert select_call.args[1] == ("inv_123", "tenant-a")

    def test_list_audit_entries_applies_tenant_filters_and_pagination(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchall.return_value = [
            (1, "inv_123", "tenant-a", "reviewer", "approve", None, None, 1, 2, "ok", "2025-01-01"),
        ]
        conn.execute.return_value.fetchone.return_value = (1,)

        entries, total = repo.list_audit_entries(
            tenant_id="tenant-a",
            document_id="inv_123",
            action="approve",
            actor="reviewer",
            limit=10,
            offset=5,
        )

        assert total == 1
        assert entries[0]["action"] == "approve"
        select_call = conn.execute.call_args_list[-2]
        assert "tenant_id = %s" in select_call.args[0]
        assert "invoice_id = %s" in select_call.args[0]
        assert select_call.args[1] == ("tenant-a", "inv_123", "approve", "reviewer", 10, 5)


class TestIdempotency:
    def test_claim_idempotency_record_returns_owner_row(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = (
            "tenant-a",
            "key-1",
            "fingerprint",
            "inv_123",
            "pending",
            None,
            "2025-01-02",
            "2025-01-01",
            "2025-01-01",
        )

        claimed, record = repo.claim_idempotency_record(
            tenant_id="tenant-a",
            idempotency_key="key-1",
            request_fingerprint="fingerprint",
            resource_id="inv_123",
            expires_at=datetime.now(timezone.utc),
        )

        assert claimed is True
        assert record["resource_id"] == "inv_123"
        assert record["state"] == "pending"
        statement = conn.execute.call_args_list[-1].args[0]
        assert "expires_at <= NOW()" in statement

    def test_expired_idempotency_claim_replaces_response_and_uses_minimum_ttl(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = (
            "tenant-a",
            "key-1",
            "replacement-fingerprint",
            "inv_new",
            "pending",
            None,
            "2026-07-17T00:05:00Z",
            "2026-07-17T00:00:00Z",
            "2026-07-17T00:00:00Z",
        )

        claimed, record = repo.claim_idempotency_record(
            tenant_id="tenant-a",
            idempotency_key="key-1",
            request_fingerprint="replacement-fingerprint",
            resource_id="inv_new",
            expires_at=datetime.now(timezone.utc),
        )

        assert claimed is True
        assert record["resource_id"] == "inv_new"
        params = conn.execute.call_args_list[-1].args[1]
        assert params[-1] > datetime.now(timezone.utc)

    def test_complete_idempotency_record_persists_canonical_response(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = ("tenant-a",)

        completed = repo.complete_idempotency_record(
            tenant_id="tenant-a",
            idempotency_key="key-1",
            request_fingerprint="fingerprint",
            resource_id="inv_123",
            canonical_response={"document_id": "inv_123", "status": "completed"},
        )

        assert completed is True
        call = conn.execute.call_args_list[-1]
        assert '"document_id": "inv_123"' in call.args[1][0]


class TestDurableAtomicity:
    def test_atomic_extraction_commit_includes_canonical_response_and_outbox(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = ("tenant-a",)

        invoice_id = repo.save_invoice_and_complete_idempotency(
            {
                "source": {"file_path": "documents/inv_123/raw"},
                "extracted": {"issuer_name": {"value": "Acme"}},
                "validation": {},
            },
            tenant_id="tenant-a",
            invoice_id="inv_123",
            actor="operator-1",
            reason="extracted",
            idempotency_key="key-1",
            request_fingerprint="fingerprint",
            canonical_response={"document_id": "inv_123", "status": "completed"},
        )

        assert invoice_id == "inv_123"
        statements = [call.args[0] for call in conn.execute.call_args_list]
        assert any("INSERT INTO invoices" in statement for statement in statements)
        assert any("INSERT INTO invoice_audit_logs" in statement for statement in statements)
        assert any("INSERT INTO invoice_outbox" in statement for statement in statements)
        completion = next(
            call
            for call in conn.execute.call_args_list
            if "UPDATE invoice_idempotency_records" in call.args[0]
        )
        assert '"document_id": "inv_123"' in completion.args[1][0]
        assert completion.args[1][3:] == ("key-1", "fingerprint", "inv_123")

    def test_queue_job_writes_job_event_and_canonical_response_in_one_transaction(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = ("tenant-a",)

        job_id = repo.create_extraction_job_and_complete_idempotency(
            job_id="job_123",
            tenant_id="tenant-a",
            source_key="documents/job_123/raw",
            source_file_hash="sha256",
            content_type="image/png",
            ocr_lang="ja",
            idempotency_key="async-key",
            request_fingerprint="fingerprint",
            canonical_response={"job_id": "job_123", "status": "received"},
        )

        assert job_id == "job_123"
        outbox_call = next(
            call for call in conn.execute.call_args_list if "INSERT INTO invoice_outbox" in call.args[0]
        )
        assert outbox_call.args[1][2] is None
        assert outbox_call.args[1][3] == "document.extraction_requested"

    def test_batch_page_failure_rolls_back_every_durable_page_and_idempotency(self):
        repo = object.__new__(InvoiceRepository)
        conn = _TransactionalConnection(fail_on_invoice=2)
        repo._schema_ready = True
        repo._conn = lambda: _TransactionalContext(conn)
        repo.ensure_schema = lambda: None

        page = {
            "invoice_data": {
                "source": {"file_path": "documents/page/raw"},
                "extracted": {"invoice_number": {"value": "R-1"}},
                "validation": {},
            },
            "actor": "operator-1",
        }
        with pytest.raises(RuntimeError, match="later page insert failed"):
            repo.save_invoices_and_complete_idempotency(
                [
                    {**page, "invoice_id": "page-1"},
                    {**page, "invoice_id": "page-2"},
                ],
                tenant_id="tenant-a",
                idempotency_key="key-1",
                request_fingerprint="fingerprint",
                resource_id="page-1",
                canonical_response={"document_id": "page-1", "status": "completed"},
            )

        assert conn.staged_invoice_ids == []
        assert conn.committed_invoice_ids == []
        assert not any("UPDATE invoice_idempotency_records" in statement for statement in conn.statements)

    def test_non_idempotent_batch_page_failure_rolls_back_every_durable_page(self):
        repo = object.__new__(InvoiceRepository)
        conn = _TransactionalConnection(fail_on_invoice=2)
        repo._schema_ready = True
        repo._conn = lambda: _TransactionalContext(conn)
        repo.ensure_schema = lambda: None

        page = {
            "invoice_data": {
                "source": {"file_path": "documents/page/raw"},
                "extracted": {"invoice_number": {"value": "R-1"}},
                "validation": {},
            },
            "actor": "operator-1",
        }
        with pytest.raises(RuntimeError, match="later page insert failed"):
            repo.save_invoices(
                [
                    {**page, "invoice_id": "page-1"},
                    {**page, "invoice_id": "page-2"},
                ],
                tenant_id="tenant-a",
            )

        assert conn.staged_invoice_ids == []
        assert conn.committed_invoice_ids == []


class TestExtractionJobFencing:
    @staticmethod
    def _job_row(lease_token: str = "lease-current"):
        return (
            "job_123",
            "tenant-a",
            "jobs/job_123/source",
            "sha256",
            "image/png",
            "ja",
            "running",
            None,
            None,
            None,
            1,
            "2026-07-17T00:05:00Z",
            lease_token,
            "2026-07-17T00:00:00Z",
            "2026-07-17T00:00:00Z",
            None,
        )

    def test_claim_assigns_a_fencing_token(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = self._job_row()

        job = repo.claim_extraction_job("job_123", tenant_id="tenant-a", lease_seconds=45)

        assert job["lease_token"] == "lease-current"
        call = conn.execute.call_args_list[-1]
        assert "lease_token = %s" in call.args[0]
        assert call.args[1][0] == 45
        assert len(call.args[1][1]) == 32

    def test_renew_requires_current_unexpired_token(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = ("job_123",)

        assert repo.renew_extraction_job_claim(
            "job_123",
            tenant_id="tenant-a",
            lease_token="lease-current",
            lease_seconds=45,
        )

        call = conn.execute.call_args_list[-1]
        assert "lease_token = %s" in call.args[0]
        assert "claimed_until > NOW()" in call.args[0]
        assert call.args[1] == (45, "job_123", "tenant-a", "lease-current")

    def test_active_and_expired_job_claim_queries_are_distinct(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = (1,)
        conn.execute.return_value.fetchall.return_value = [("job_123", "tenant-a")]

        assert repo.has_active_extraction_job_claim("job_123", tenant_id="tenant-a")
        active_call = conn.execute.call_args_list[-1]
        assert "status = 'running'" in active_call.args[0]
        assert "claimed_until > NOW()" in active_call.args[0]

        assert repo.list_expired_extraction_jobs() == [
            {"job_id": "job_123", "tenant_id": "tenant-a"},
        ]
        expired_call = conn.execute.call_args_list[-1]
        assert "claimed_until <= NOW()" in expired_call.args[0]

    def test_stale_owner_cannot_complete_or_fail_reclaimed_job(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = None

        assert not repo.complete_extraction_job(
            "job_123",
            tenant_id="tenant-a",
            lease_token="lease-old",
            document_id="inv_123",
            result={"page_count": 1},
        )
        complete_call = conn.execute.call_args_list[-1]
        assert "lease_token = %s" in complete_call.args[0]
        assert "claimed_until > NOW()" in complete_call.args[0]
        assert complete_call.args[1][-1] == "lease-old"

        assert not repo.fail_extraction_job(
            "job_123",
            tenant_id="tenant-a",
            lease_token="lease-old",
            error="stale owner",
        )
        fail_call = conn.execute.call_args_list[-1]
        assert "lease_token = %s" in fail_call.args[0]
        assert "claimed_until > NOW()" in fail_call.args[0]
        assert fail_call.args[1][-1] == "lease-old"

    def test_cancelled_job_fence_skips_invoice_audit_and_outbox_writes(self):
        repo, _mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        repo._conn = lambda: ctx
        repo.ensure_schema = lambda: None
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn.execute.return_value = cursor

        committed = repo.complete_extraction_job_and_store_invoices(
            "job_123",
            tenant_id="tenant-a",
            lease_token="lease-old",
            invoice_writes=[
                {
                    "invoice_id": "inv_123",
                    "invoice_data": {
                        "source": {"file_path": "documents/inv_123/raw"},
                        "extracted": {},
                        "validation": {},
                    },
                }
            ],
            result={"page_count": 1},
        )

        assert not committed
        statements = [call.args[0] for call in conn.execute.call_args_list]
        assert any("FOR UPDATE" in statement for statement in statements)
        assert not any("INSERT INTO invoices" in statement for statement in statements)
        assert not any("INSERT INTO invoice_audit_logs" in statement for statement in statements)
        assert not any("INSERT INTO invoice_outbox" in statement for statement in statements)

    def test_fenced_completion_commits_documents_before_terminal_job_state(self):
        repo, _mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        repo._conn = lambda: ctx
        repo.ensure_schema = lambda: None

        def execute(statement, _params=None):
            cursor = MagicMock()
            if "SELECT id" in statement and "invoice_extraction_jobs" in statement:
                cursor.fetchone.return_value = ("job_123",)
            elif "UPDATE invoice_extraction_jobs" in statement:
                cursor.fetchone.return_value = ("job_123",)
            else:
                cursor.fetchone.return_value = None
            return cursor

        conn.execute.side_effect = execute
        committed = repo.complete_extraction_job_and_store_invoices(
            "job_123",
            tenant_id="tenant-a",
            lease_token="lease-current",
            invoice_writes=[
                {
                    "invoice_id": "inv_123",
                    "invoice_data": {
                        "source": {"file_path": "documents/inv_123/raw"},
                        "extracted": {},
                        "validation": {},
                    },
                }
            ],
            result={"page_count": 1},
        )

        assert committed
        statements = [call.args[0] for call in conn.execute.call_args_list]
        fence_index = next(index for index, statement in enumerate(statements) if "FOR UPDATE" in statement)
        invoice_index = next(
            index for index, statement in enumerate(statements) if "INSERT INTO invoices" in statement
        )
        completion_index = next(
            index
            for index, statement in enumerate(statements)
            if "UPDATE invoice_extraction_jobs" in statement
        )
        assert fence_index < invoice_index < completion_index

    def test_cancel_records_durable_artifact_cleanup_tombstone(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = ("job_123",)

        assert repo.cancel_extraction_job("job_123", tenant_id="tenant-a")

        call = conn.execute.call_args_list[-1]
        assert "artifact_cleanup_keys = COALESCE(" in call.args[0]
        assert "'[]'::jsonb" in call.args[0]
        assert ") || jsonb_build_array(source_key)" in call.args[0]
        assert "artifact_cleanup_pending = TRUE" in call.args[0]

    def test_cancel_unions_source_with_preexisting_journal_candidates(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = ("job_123",)

        assert repo.cancel_extraction_job("job_123", tenant_id="tenant-a")

        statement = conn.execute.call_args_list[-1].args[0]
        assert "COALESCE(\n                        artifact_cleanup_keys,\n                        '[]'::jsonb\n                    ) || jsonb_build_array(source_key)" in statement

    def test_cleanup_tombstone_is_retained_until_matching_snapshot_completes(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchall.return_value = [
            ("job_123", "tenant-a", ["jobs/job_123/source"]),
        ]
        conn.execute.return_value.fetchone.return_value = ("job_123",)

        pending = repo.list_cancelled_extraction_jobs_for_cleanup()
        assert pending == [
            {
                "job_id": "job_123",
                "tenant_id": "tenant-a",
                "artifact_cleanup_keys": ["jobs/job_123/source"],
            }
        ]
        assert repo.complete_extraction_job_artifact_cleanup(
            "job_123",
            tenant_id="tenant-a",
            keys=["jobs/job_123/source"],
        )

        call = conn.execute.call_args_list[-1]
        assert "artifact_cleanup_keys @> %s::jsonb" in call.args[0]
        assert "%s::jsonb @> artifact_cleanup_keys" in call.args[0]
        assert call.args[1][-2:] == ('["jobs/job_123/source"]', '["jobs/job_123/source"]')

    def test_running_owner_journals_artifact_candidates_before_storage_write(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = ("job_123",)

        assert repo.journal_extraction_job_artifacts(
            "job_123",
            tenant_id="tenant-a",
            lease_token="lease-current",
            keys=["documents/job_123/raw", "documents/job_123/extracted.json"],
        )

        call = conn.execute.call_args_list[-1]
        assert "artifact_cleanup_keys = artifact_cleanup_keys || %s::jsonb" in call.args[0]
        assert "lease_token = %s" in call.args[0]
        assert "claimed_until > NOW()" in call.args[0]
        assert call.args[1][-1] == "lease-current"

    def test_duplicate_reclaim_journal_keys_do_not_block_cleanup_completion(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = ("job_123",)

        assert repo.complete_extraction_job_artifact_cleanup(
            "job_123",
            tenant_id="tenant-a",
            keys=["jobs/job_123/source", "documents/job_123/raw"],
        )

        call = conn.execute.call_args_list[-1]
        assert "artifact_cleanup_keys @> %s::jsonb" in call.args[0]
        assert "%s::jsonb @> artifact_cleanup_keys" in call.args[0]
        assert call.args[1][-2:] == (
            '["jobs/job_123/source", "documents/job_123/raw"]',
            '["jobs/job_123/source", "documents/job_123/raw"]',
        )


class TestReviewStatuses:
    def test_all_statuses_defined(self):
        assert ReviewStatus.AUTO_APPROVED == "auto_approved"
        assert ReviewStatus.NEEDS_REVIEW == "needs_review"
        assert ReviewStatus.REVIEWED == "reviewed"
        assert ReviewStatus.REJECTED == "rejected"
        assert ReviewStatus.EXPORTED == "exported"


class TestOutboxDelivery:
    def test_claim_pending_outbox_leases_rows_with_skip_locked(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchall.return_value = [
            (
                "evt_1",
                "tenant-a",
                "inv_123",
                "document.review_completed",
                {},
                "2025-01-01",
                2,
                "lease-current",
            ),
        ]

        events = repo.claim_pending_outbox(limit=10, lease_seconds=45)

        assert events[0]["id"] == "evt_1"
        statement = conn.execute.call_args_list[-1].args[0]
        assert "FOR UPDATE SKIP LOCKED" in statement
        assert "claimed_until" in statement
        assert "lease_token" in statement
        assert conn.execute.call_args_list[-1].args[1][:2] == (10, 45)
        assert len(conn.execute.call_args_list[-1].args[1][2]) == 32
        assert events[0]["lease_token"] == "lease-current"

    def test_mark_and_release_outbox_claim_require_current_live_fence(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = ("evt_1",)

        assert repo.mark_outbox_published("evt_1", "lease-current") is True
        mark_call = conn.execute.call_args_list[-1]
        assert "published_at IS NULL" in mark_call.args[0]
        assert "lease_token = %s" in mark_call.args[0]
        assert "claimed_until > NOW()" in mark_call.args[0]
        assert mark_call.args[1] == ("evt_1", "lease-current")

        assert repo.release_outbox_claim("evt_1", "lease-current", "broker unavailable") is True
        release_call = conn.execute.call_args_list[-1]
        assert "lease_token = %s" in release_call.args[0]
        assert "claimed_until > NOW()" in release_call.args[0]
        assert release_call.args[1] == ("broker unavailable", "evt_1", "lease-current")

    def test_expired_or_reclaimed_outbox_owner_cannot_mark_or_release(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = None

        assert not repo.mark_outbox_published("evt_1", "lease-stale")
        mark_call = conn.execute.call_args_list[-1]
        assert "lease_token = %s" in mark_call.args[0]
        assert "claimed_until > NOW()" in mark_call.args[0]

        assert not repo.release_outbox_claim("evt_1", "lease-stale", "broker unavailable")
        release_call = conn.execute.call_args_list[-1]
        assert "lease_token = %s" in release_call.args[0]
        assert "claimed_until > NOW()" in release_call.args[0]

    def test_claim_consumer_receipt_leases_only_one_handler(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = ("evt_1",)

        assert repo.claim_consumer_receipt("evt_1", "search-indexer", lease_seconds=45)
        statement = conn.execute.call_args_list[-1].args[0]
        assert "state != 'completed'" in statement
        assert "claimed_until" in statement
        assert "lease_token" in statement

    def test_active_consumer_receipt_query_distinguishes_live_lease(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = (1,)

        assert repo.has_active_consumer_receipt("evt_1", "search-indexer")
        call = conn.execute.call_args_list[-1]
        assert "state = 'processing'" in call.args[0]
        assert "claimed_until > NOW()" in call.args[0]

    def test_consumer_receipt_can_complete_or_release_failed_effect(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = ("evt_1",)

        assert repo.complete_consumer_receipt("evt_1", "search-indexer", "lease-1") is True
        complete_call = conn.execute.call_args_list[-1]
        assert "state = 'completed'" in complete_call.args[0]
        assert "claimed_until > NOW()" in complete_call.args[0]

        assert repo.release_consumer_receipt(
            "evt_1",
            "search-indexer",
            "lease-1",
            "index failed",
        ) is True
        release_call = conn.execute.call_args_list[-1]
        assert "state = 'pending'" in release_call.args[0]
        assert "claimed_until > NOW()" in release_call.args[0]
        assert release_call.args[1] == ("index failed", "evt_1", "search-indexer", "lease-1")

    def test_stale_consumer_lease_cannot_complete_reclaimed_receipt(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = None

        assert not repo.complete_consumer_receipt("evt_1", "search-indexer", "stale-token")
        call = conn.execute.call_args_list[-1]
        assert "lease_token = %s" in call.args[0]
        assert "claimed_until > NOW()" in call.args[0]
        assert call.args[1][-1] == "stale-token"

    def test_search_projection_and_receipt_complete_in_one_transaction(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = ("evt_1",)

        assert repo.complete_consumer_receipt_and_save_search_chunks(
            "evt_1",
            "search-indexer",
            "lease-current",
            invoice_id="inv_123",
            tenant_id="tenant-a",
            event_type="document.review_completed",
            chunks=[{"content": "Acme", "metadata": {"tenant_id": "tenant-a"}}],
        )

        statements = [call.args[0] for call in conn.execute.call_args_list]
        receipt_update = next(
            statement
            for statement in statements
            if "UPDATE invoice_consumer_receipts" in statement
        )
        assert "claimed_until > NOW()" in receipt_update
        assert any("DELETE FROM invoice_search_chunks" in statement for statement in statements)
        assert any("INSERT INTO invoice_search_chunks" in statement for statement in statements)
        intent_insert = next(
            statement
            for statement in statements
            if "INSERT INTO invoice_webhook_deliveries" in statement
        )
        assert "subscription.active = TRUE" in intent_insert
        assert "subscription.event_types_json @>" in intent_insert

class TestWebhookDeliveryLease:
    def test_webhook_delivery_claim_precedes_complete_or_retry(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = (1,)

        assert repo.claim_webhook_delivery(
            event_id="evt_1",
            subscription_id="sub_1",
            lease_seconds=45,
        )
        claim_call = conn.execute.call_args_list[-1]
        assert "claimed_until" in claim_call.args[0]
        assert "status != 'delivered'" in claim_call.args[0]
        assert "lease_token" in claim_call.args[0]

        assert repo.release_webhook_delivery(
            event_id="evt_1",
            subscription_id="sub_1",
            lease_token="lease-1",
            error="timeout",
        )
        release_call = conn.execute.call_args_list[-1]
        assert "status = 'pending'" in release_call.args[0]
        assert "claimed_until > NOW()" in release_call.args[0]

        assert repo.complete_webhook_delivery(
            event_id="evt_1",
            subscription_id="sub_1",
            lease_token="lease-1",
            response_code=202,
        )
        complete_call = conn.execute.call_args_list[-1]
        assert "status = 'delivered'" in complete_call.args[0]
        assert "claimed_until > NOW()" in complete_call.args[0]

    def test_stale_webhook_lease_cannot_complete_reclaimed_delivery(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = None

        assert not repo.complete_webhook_delivery(
            event_id="evt_1",
            subscription_id="sub_1",
            lease_token="stale-token",
        )
        call = conn.execute.call_args_list[-1]
        assert "lease_token = %s" in call.args[0]
        assert "claimed_until > NOW()" in call.args[0]
        assert call.args[1][-1] == "stale-token"

    def test_pending_webhook_scan_returns_retryable_events_only(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchall.return_value = [
            (
                "evt_1",
                "tenant-a",
                "inv_123",
                "document.review_completed",
                {"document_version": 2},
                "2026-07-17T00:00:00Z",
            )
        ]

        events = repo.list_pending_webhook_events()

        assert events == [
            {
                "event_id": "evt_1",
                "tenant_id": "tenant-a",
                "invoice_id": "inv_123",
                "event_type": "document.review_completed",
                "payload": {"document_version": 2},
                "created_at": "2026-07-17T00:00:00Z",
            }
        ]
        call = conn.execute.call_args_list[-1]
        assert "delivery.status != 'delivered'" in call.args[0]
        assert "delivery.claimed_until <= NOW()" in call.args[0]

    def test_pending_webhook_intents_exclude_inactive_subscriptions(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchall.return_value = [
            ("sub_1", "tenant-a", "https://example.com/hook", ["document.review_completed"], None, True),
        ]

        subscriptions = repo.list_pending_webhook_subscriptions("evt_1")

        assert subscriptions[0]["id"] == "sub_1"
        call = conn.execute.call_args_list[-1]
        assert "subscription.active = TRUE" in call.args[0]
        assert "delivery.status != 'delivered'" in call.args[0]
