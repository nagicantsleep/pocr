from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.repositories.invoice_repository import ReviewStatus
from app.services.document_store import StoredDocument
from app.services.durable_invoice_service import DurableInvoiceService


def _document(**overrides):
    values = {
        "id": "jp-001",
        "document_type": "invoice_jp",
        "structured_json": {"issuer_name": {"value": "Acme"}, "total_amount": {"value": 5000}},
        "confidence": 0.91,
        "needs_review": True,
        "review_status": "needs_review",
        "created_at": datetime(2026, 7, 17, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 7, 17, tzinfo=timezone.utc),
        "tenant_id": "tenant-a",
    }
    return StoredDocument(**{**values, **overrides})


def _invoice(**overrides):
    values = {
        "id": "jp-001",
        "tenant_id": "tenant-a",
        "extracted_json": {"issuer_name": {"value": "Acme"}},
        "validation_json": {
            "_durable_document": {
                "document_type": "invoice_jp",
                "confidence": 0.91,
                "needs_review": True,
                "reviewed_by": None,
                "review_reason": None,
            }
        },
        "review_status": ReviewStatus.NEEDS_REVIEW,
        "document_version": 1,
        "created_at": datetime(2026, 7, 17, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 7, 17, tzinfo=timezone.utc),
    }
    return {**values, **overrides}


class TestDurableInvoiceService:
    def test_store_extraction_preserves_id_and_durable_metadata(self):
        repository = MagicMock()
        repository.get_invoice.return_value = _invoice()
        service = DurableInvoiceService(repository)

        stored = service.store_extraction(
            _document(),
            raw_ocr={"pages": []},
            source={"file_path": "x.png"},
            actor="operator-1",
            reason="receipt extracted",
        )

        assert stored.id == "jp-001"
        args, kwargs = repository.save_invoice.call_args
        assert kwargs["tenant_id"] == "tenant-a"
        assert kwargs["invoice_id"] == "jp-001"
        assert kwargs["actor"] == "operator-1"
        assert kwargs["reason"] == "receipt extracted"
        assert args[0]["validation"]["_durable_document"]["confidence"] == 0.91

    def test_store_extraction_preserves_pending_status(self):
        repository = MagicMock()
        repository.get_invoice.return_value = _invoice(
            review_status="pending",
            validation_json={
                "_durable_document": {
                    "document_type": "invoice_jp",
                    "confidence": 0.91,
                    "needs_review": False,
                    "reviewed_by": None,
                    "review_reason": None,
                }
            },
        )
        service = DurableInvoiceService(repository)

        stored = service.store_extraction(_document(review_status="pending", needs_review=False))

        assert stored.review_status == "pending"
        assert repository.save_invoice.call_args.args[0]["review_status"] == "pending"

    def test_store_extraction_commits_canonical_response_with_document(self):
        repository = MagicMock()
        repository.get_invoice.return_value = _invoice()
        service = DurableInvoiceService(repository)

        service.store_extraction(
            _document(),
            idempotency_key="key-1",
            request_fingerprint="fingerprint",
            canonical_response={"document_id": "jp-001", "status": "completed"},
        )

        repository.save_invoice.assert_not_called()
        kwargs = repository.save_invoice_and_complete_idempotency.call_args.kwargs
        assert kwargs["invoice_id"] == "jp-001"
        assert kwargs["canonical_response"]["status"] == "completed"

    def test_claim_idempotency_forwards_tenant_scoped_request(self):
        repository = MagicMock()
        repository.claim_idempotency_record.return_value = (True, {"state": "pending"})
        service = DurableInvoiceService(repository)

        claimed, record = service.claim_idempotency(
            tenant_id="tenant-a",
            idempotency_key="key-1",
            request_fingerprint="fingerprint",
            resource_id="jp-001",
            expires_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        )

        assert claimed is True
        assert record["state"] == "pending"
        assert repository.claim_idempotency_record.call_args.kwargs["tenant_id"] == "tenant-a"

    def test_store_extractions_forwards_all_pages_to_one_batch_write(self):
        repository = MagicMock()
        repository.get_invoice.side_effect = [_invoice(), _invoice(id="jp-002")]
        service = DurableInvoiceService(repository)

        stored = service.store_extractions(
            [_document(), _document(id="jp-002")],
            sources=[{"file_path": "page-1.png"}, {"file_path": "page-2.png"}],
            raw_ocr_pages=[{"results": []}, {"results": []}],
            actor="operator-1",
        )

        assert [document.id for document in stored] == ["jp-001", "jp-002"]
        writes = repository.save_invoices.call_args.args[0]
        assert [write["invoice_id"] for write in writes] == ["jp-001", "jp-002"]
        assert repository.save_invoices.call_args.kwargs["tenant_id"] == "tenant-a"

    def test_get_hides_other_tenant_by_repository_predicate(self):
        repository = MagicMock()
        repository.get_invoice.return_value = None
        service = DurableInvoiceService(repository)

        assert service.get("jp-001", tenant_id="tenant-b") is None
        repository.get_invoice.assert_called_once_with("jp-001", tenant_id="tenant-b")

    def test_approve_updates_status_metadata_audit_and_outbox_transactionally(self):
        repository = MagicMock()
        repository.get_invoice.side_effect = [
            _invoice(),
            _invoice(
                review_status=ReviewStatus.REVIEWED,
                validation_json={
                    "_durable_document": {
                        "document_type": "invoice_jp",
                        "confidence": 0.91,
                        "needs_review": True,
                        "reviewed_by": "reviewer-1",
                        "review_reason": "validated",
                    }
                },
            ),
        ]
        repository.update_invoice.return_value = True
        service = DurableInvoiceService(repository)

        result = service.approve(
            "jp-001",
            actor="reviewer-1",
            reason="validated",
            tenant_id="tenant-a",
        )

        assert result.review_status == "approved"
        updates = repository.update_invoice.call_args.args[1]
        assert updates["review_status"] == ReviewStatus.REVIEWED
        assert updates["validation_json"]["_durable_document"]["reviewed_by"] == "reviewer-1"
        assert repository.update_invoice.call_args.kwargs["audit_action"] == "approve"
        assert repository.update_invoice.call_args.kwargs["expected_version"] == 1

    def test_patch_blocks_terminal_document_without_force(self):
        repository = MagicMock()
        repository.get_invoice.return_value = _invoice(review_status=ReviewStatus.REVIEWED)
        service = DurableInvoiceService(repository)

        with pytest.raises(PermissionError):
            service.patch(
                "jp-001",
                fields={"invoice_number": {"value": "R-1"}},
                actor="reviewer-1",
                tenant_id="tenant-a",
            )

        repository.update_invoice.assert_not_called()

    def test_review_blocks_terminal_state_without_write(self):
        repository = MagicMock()
        repository.get_invoice.return_value = _invoice(review_status=ReviewStatus.REVIEWED)
        service = DurableInvoiceService(repository)

        with pytest.raises(PermissionError):
            service.reject(
                "jp-001",
                actor="reviewer-2",
                tenant_id="tenant-a",
            )

        repository.update_invoice.assert_not_called()

    def test_list_maps_review_status_and_returns_total(self):
        repository = MagicMock()
        repository.list_invoices.return_value = ([_invoice()], 1)
        service = DurableInvoiceService(repository)

        documents, total = service.list(
            tenant_id="tenant-a",
            review_status="needs_review",
            document_type="invoice_jp",
        )

        assert documents[0].id == "jp-001"
        assert total == 1
        assert repository.list_invoices.call_args.kwargs["review_status"] == ReviewStatus.NEEDS_REVIEW

    def test_list_audit_entries_forwards_existing_audit_filters(self):
        repository = MagicMock()
        repository.list_audit_entries.return_value = (
            [
                {
                    "id": 1,
                    "invoice_id": "jp-001",
                    "tenant_id": "tenant-a",
                    "actor": "reviewer-1",
                    "action": "approve",
                    "after_json": {"extracted_json": {}},
                    "reason": "validated",
                    "created_at": datetime(2026, 7, 17, tzinfo=timezone.utc),
                }
            ],
            1,
        )
        service = DurableInvoiceService(repository)

        entries, total = service.list_audit_entries(
            tenant_id="tenant-a",
            action="approve",
            actor="reviewer-1",
            limit=10,
            offset=2,
        )

        assert entries[0].action.value == "approve"
        assert total == 1
        assert repository.list_audit_entries.call_args.kwargs == {
            "tenant_id": "tenant-a",
            "document_id": None,
            "action": "approve",
            "actor": "reviewer-1",
            "limit": 10,
            "offset": 2,
        }
