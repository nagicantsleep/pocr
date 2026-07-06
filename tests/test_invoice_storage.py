"""Tests for invoice repository (PostgreSQL storage and audit logs)."""

from unittest.mock import MagicMock, patch

import pytest

from app.repositories.invoice_repository import ReviewStatus


def _make_repo():
    """Create an InvoiceRepository with a fully mocked pool, bypassing __init__."""
    repo = object.__new__(__import__("app.repositories.invoice_repository", fromlist=["InvoiceRepository"]).InvoiceRepository)
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


class TestTableCreation:
    def test_ensure_schema_executes_ddl(self):
        repo, mock_pool = _make_repo()
        repo.ensure_schema()
        assert mock_pool.connection.called


class TestSaveAndGetInvoice:
    def test_save_returns_id(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx

        invoice_id = repo.save_invoice({
            "source": {"file_path": "test.pdf"},
            "raw_ocr": {"results": []},
            "extracted": {"issuer_name": "Acme Corp", "total_amount": 5000},
            "validation": {"is_valid": True},
        })

        assert invoice_id.startswith("inv_")
        # ensure_schema (2 CREATE TABLE) + 1 INSERT = 3 calls
        assert conn.execute.call_count == 3

    def test_get_invoice_returns_none_for_missing(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = None

        result = repo.get_invoice("inv_nonexistent")
        assert result is None

    def test_get_invoice_returns_dict(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = (
            "inv_123", None, None, "Acme", None, None, None,
            5000, None, {"issuer_name": "Acme"}, {"is_valid": True},
            "needs_review", "2025-01-01", "2025-01-01",
        )

        result = repo.get_invoice("inv_123")
        assert result is not None
        assert result["id"] == "inv_123"
        assert result["total_amount"] == 5000
        assert result["review_status"] == "needs_review"


class TestUpdateWithAuditLog:
    def test_update_fields_writes_audit(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx

        row = (
            "inv_123", None, None, "Old Name", None, None, None,
            5000, None, None, None, "needs_review", "2025-01-01", "2025-01-01",
        )
        conn.execute.return_value.fetchone.return_value = row

        ok = repo.update_invoice(
            "inv_123",
            {"issuer_name": "New Name"},
            actor="reviewer",
            reason="Corrected name",
        )

        assert ok is True
        # get + update + audit = 3 calls
        assert conn.execute.call_count >= 3

    def test_update_nonexistent_returns_false(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchone.return_value = None

        ok = repo.update_invoice("inv_bad", {"issuer_name": "X"})
        assert ok is False


class TestAuditLog:
    def test_get_audit_log(self):
        repo, mock_pool = _make_repo()
        ctx, conn = _mock_conn()
        mock_pool.connection.return_value = ctx
        conn.execute.return_value.fetchall.return_value = [
            (1, "inv_123", "api", "update_fields", None, None, "fix", "2025-01-01"),
        ]

        logs = repo.get_audit_log("inv_123")
        assert len(logs) == 1
        assert logs[0]["actor"] == "api"
        assert logs[0]["action"] == "update_fields"


class TestReviewStatuses:
    def test_all_statuses_defined(self):
        assert ReviewStatus.AUTO_APPROVED == "auto_approved"
        assert ReviewStatus.NEEDS_REVIEW == "needs_review"
        assert ReviewStatus.REVIEWED == "reviewed"
        assert ReviewStatus.REJECTED == "rejected"
        assert ReviewStatus.EXPORTED == "exported"
