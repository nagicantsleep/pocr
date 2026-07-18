import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.auth import AuthenticatedPrincipal
from app.main import app
from app.routers.v1.jobs import cancel_job
from app.workers.invoice_extraction import (
    _cleanup_cancelled_artifacts,
    _execute_extraction_job,
    _process_until_extraction_lease_clears,
    _recover_expired_extraction_jobs,
    _run_cleanup_retry_loop,
    process_extraction_event,
)


def test_process_extraction_event_claims_job_and_persists_completion():
    calls = []
    job = {
        "job_id": "job-1",
        "tenant_id": "tenant-a",
        "source_key": "jobs/job-1/source",
        "content_type": "image/png",
        "ocr_lang": "ja",
        "lease_token": "claim-1",
    }
    document = SimpleNamespace(
        id="job-1",
        document_type="qualified_invoice",
        structured_json={"invoice_number": {"value": "INV-1"}},
        confidence=0.9,
        needs_review=False,
        review_status="pending",
        reviewed_by=None,
        review_reason=None,
    )

    class Repository:
        def claim_extraction_job(self, job_id, *, tenant_id, lease_seconds):
            calls.append(("claim", job_id, tenant_id, lease_seconds))
            return job

        def renew_extraction_job_claim(self, *_args, **_kwargs):
            return True

        def complete_extraction_job_and_store_invoices(
            self, job_id, *, tenant_id, lease_token, invoice_writes, result
        ):
            calls.append(
                ("complete", job_id, tenant_id, lease_token, invoice_writes, result)
            )
            return True

        def complete_extraction_job(self, *_args, **_kwargs):
            raise AssertionError("new durable extraction must commit documents atomically")

        def fail_extraction_job(self, *args, **kwargs):
            calls.append(("fail", args, kwargs))
            return True

    storage = SimpleNamespace(get=AsyncMock(return_value=b"image"))

    async def extractor(content, content_type, lang, **kwargs):
        assert content == b"image"
        assert content_type == "image/png"
        assert lang == "ja"
        assert kwargs["first_document_id"] == "job-1"
        assert kwargs["defer_durable_commit"] is True
        kwargs["created_document_ids"].add(document.id)
        return [
            (
                document,
                object(),
                {
                    "raw_ocr": {"results": []},
                    "source": {"file_path": "documents/job-1/raw", "file_hash": "hash"},
                },
            )
        ]

    durable_service = MagicMock()
    durable_service.get.return_value = None
    with patch(
        "app.workers.invoice_extraction.get_durable_invoice_service",
        return_value=durable_service,
    ):
        assert process_extraction_event(
            {
                "event_type": "document.extraction_requested",
                "tenant_id": "tenant-a",
                "payload": {"job_id": "job-1"},
            },
            repository=Repository(),
            storage_adapter=storage,
            extractor=extractor,
        )
    assert calls == [
        ("claim", "job-1", "tenant-a", 300),
        (
            "complete",
            "job-1",
            "tenant-a",
            "claim-1",
            [
                {
                    "invoice_id": "job-1",
                    "actor": "invoice-extraction-worker",
                    "invoice_data": {
                        "source": {
                            "file_path": "documents/job-1/raw",
                            "file_hash": "hash",
                        },
                        "raw_ocr": {"results": []},
                        "extracted": {"invoice_number": {"value": "INV-1"}},
                        "validation": {
                            "_durable_document": {
                                "document_type": "qualified_invoice",
                                "confidence": 0.9,
                                "needs_review": False,
                                "reviewed_by": None,
                                "review_reason": None,
                            }
                        },
                        "review_status": "pending",
                    },
                }
            ],
            {
                "documents": [
                    {
                        "status": "success",
                        "document_id": "job-1",
                        "document_type": "qualified_invoice",
                        "confidence": 0.9,
                        "needs_review": False,
                    }
                ],
                "page_count": 1,
            },
        ),
    ]


def test_process_extraction_event_ignores_duplicate_claim():
    class Repository:
        def claim_extraction_job(self, *_args, **_kwargs):
            return None

        def has_active_extraction_job_claim(self, *_args, **_kwargs):
            return False

    assert not process_extraction_event(
        {
            "event_type": "document.extraction_requested",
            "tenant_id": "tenant-a",
            "payload": {"job_id": "job-1"},
        },
        repository=Repository(),
    )


def test_process_extraction_event_defers_active_job_lease_and_retries_before_commit():
    class Repository:
        def claim_extraction_job(self, *_args, **_kwargs):
            return None

        def has_active_extraction_job_claim(self, job_id, *, tenant_id):
            assert (job_id, tenant_id) == ("job-1", "tenant-a")
            return True

    event = {
        "event_type": "document.extraction_requested",
        "tenant_id": "tenant-a",
        "payload": {"job_id": "job-1"},
    }
    assert process_extraction_event(event, repository=Repository()) is None

    outcomes = iter([None, False])
    assert not _process_until_extraction_lease_clears(
        lambda: next(outcomes),
        retry_seconds=0,
    )


def test_expired_job_recovery_reuses_the_durable_claim_path():
    repository = MagicMock()
    repository.list_expired_extraction_jobs.return_value = [
        {"job_id": "job-1", "tenant_id": "tenant-a"},
    ]
    storage = object()

    with patch("app.workers.invoice_extraction.process_extraction_event") as process:
        _recover_expired_extraction_jobs(repository, storage)

    process.assert_called_once_with(
        {
            "event_type": "document.extraction_requested",
            "tenant_id": "tenant-a",
            "payload": {"job_id": "job-1"},
        },
        repository=repository,
        storage_adapter=storage,
    )


def test_process_extraction_event_cleans_derived_artifacts_when_cancel_wins():
    document = SimpleNamespace(
        id="job-1",
        document_type="qualified_invoice",
        structured_json={},
        confidence=0.9,
        needs_review=False,
        review_status="pending",
        reviewed_by=None,
        review_reason=None,
    )
    calls = []

    class Repository:
        def claim_extraction_job(self, *_args, **_kwargs):
            return {
                "job_id": "job-1",
                "tenant_id": "tenant-a",
                "lease_token": "claim-1",
                "source_key": "jobs/job-1/source",
                "content_type": "image/png",
                "ocr_lang": "ja",
            }

        def renew_extraction_job_claim(self, *_args, **_kwargs):
            return True

        def complete_extraction_job_and_store_invoices(self, *_args, **kwargs):
            calls.append(kwargs)
            return False

        def add_extraction_job_artifact_cleanup(self, *_args, **_kwargs):
            return True

        def fail_extraction_job(self, *_args, **_kwargs):
            raise AssertionError("cancelled work must not be failed")

    storage = SimpleNamespace(
        get=AsyncMock(return_value=b"image"),
        delete=AsyncMock(),
    )

    async def extractor(*_args, **_kwargs):
        _kwargs["created_document_ids"].add(document.id)
        return [
            (
                document,
                object(),
                {
                    "raw_ocr": {"results": []},
                    "source": {"file_path": "documents/job-1/raw", "file_hash": "hash"},
                },
            )
        ]

    durable_service = MagicMock()
    durable_service.get.return_value = None
    with patch(
        "app.workers.invoice_extraction.get_durable_invoice_service",
        return_value=durable_service,
    ):
        assert not process_extraction_event(
            {
                "event_type": "document.extraction_requested",
                "tenant_id": "tenant-a",
                "payload": {"job_id": "job-1"},
            },
            repository=Repository(),
            storage_adapter=storage,
            extractor=extractor,
        )

    assert len(calls) == 1
    assert [call.args[0] for call in storage.delete.await_args_list] == [
        "documents/job-1/raw",
        "documents/job-1/extracted.json",
        "documents/job-1/raw.pdf",
    ]


def test_process_extraction_event_renews_slow_claim():
    job = {
        "job_id": "job-1",
        "tenant_id": "tenant-a",
        "lease_token": "claim-1",
        "source_key": "jobs/job-1/source",
        "content_type": "image/png",
        "ocr_lang": "ja",
    }
    document = SimpleNamespace(
        id="job-1",
        document_type="qualified_invoice",
        structured_json={},
        confidence=0.9,
        needs_review=False,
        review_status="pending",
        reviewed_by=None,
        review_reason=None,
    )
    renewals = []

    class Repository:
        def claim_extraction_job(self, *_args, **_kwargs):
            return job

        def renew_extraction_job_claim(self, *_args, **kwargs):
            renewals.append(kwargs)
            return True

        def complete_extraction_job_and_store_invoices(self, *_args, **_kwargs):
            return True

        def fail_extraction_job(self, *_args, **_kwargs):
            return True

    storage = SimpleNamespace(get=AsyncMock(return_value=b"image"), delete=AsyncMock())

    async def slow_extractor(*_args, **_kwargs):
        time.sleep(1.05)
        _kwargs["created_document_ids"].add(document.id)
        return [
            (
                document,
                object(),
                {
                    "raw_ocr": {"results": []},
                    "source": {"file_path": "documents/job-1/raw", "file_hash": "hash"},
                },
            )
        ]

    durable_service = MagicMock()
    durable_service.get.return_value = None
    with patch(
        "app.workers.invoice_extraction.get_durable_invoice_service",
        return_value=durable_service,
    ):
        assert process_extraction_event(
            {
                "event_type": "document.extraction_requested",
                "tenant_id": "tenant-a",
                "payload": {"job_id": "job-1"},
            },
            repository=Repository(),
            storage_adapter=storage,
            extractor=slow_extractor,
            lease_seconds=1,
        )

    assert renewals == [{"tenant_id": "tenant-a", "lease_token": "claim-1"}]


def test_durable_cancel_deletes_queued_source_artifact():
    repository = MagicMock()
    repository.get_extraction_job.return_value = {
        "job_id": "job-1",
        "source_key": "jobs/job-1/source",
    }
    repository.cancel_extraction_job.return_value = True
    storage = SimpleNamespace(delete=AsyncMock())
    principal = AuthenticatedPrincipal(
        tenant_id="tenant-a",
        user_id="operator-a",
        roles=frozenset({"operator"}),
    )

    with patch(
        "app.routers.v1.jobs.get_settings",
        return_value=SimpleNamespace(INVOICE_JP_DURABLE_MODE=True),
    ), patch(
        "app.routers.v1.jobs.get_invoice_repository",
        return_value=repository,
    ), patch(
        "app.routers.v1.jobs.get_storage_adapter",
        return_value=storage,
    ):
        assert asyncio.run(cancel_job("job-1", principal)) == {
            "job_id": "job-1",
            "status": "cancelled",
        }

    storage.delete.assert_awaited_once_with("jobs/job-1/source")


def test_cancelled_artifact_tombstone_retries_until_storage_is_empty():
    repository = MagicMock()
    repository.list_cancelled_extraction_jobs_for_cleanup.return_value = [
        {
            "job_id": "job-1",
            "tenant_id": "tenant-a",
            "artifact_cleanup_keys": ["jobs/job-1/source"],
        }
    ]
    storage = SimpleNamespace(delete=AsyncMock(return_value=True), exists=AsyncMock(return_value=False))

    _cleanup_cancelled_artifacts(repository, storage)

    repository.complete_extraction_job_artifact_cleanup.assert_called_once_with(
        "job-1",
        tenant_id="tenant-a",
        keys=["jobs/job-1/source"],
    )


def test_cancelled_artifact_tombstone_stays_pending_when_storage_delete_fails():
    repository = MagicMock()
    repository.list_cancelled_extraction_jobs_for_cleanup.return_value = [
        {
            "job_id": "job-1",
            "tenant_id": "tenant-a",
            "artifact_cleanup_keys": ["jobs/job-1/source"],
        }
    ]
    storage = SimpleNamespace(delete=AsyncMock(side_effect=RuntimeError("storage down")))

    _cleanup_cancelled_artifacts(repository, storage)

    repository.complete_extraction_job_artifact_cleanup.assert_not_called()


def test_cleanup_retry_loop_processes_pending_tombstone_while_worker_is_busy():
    stop = threading.Event()
    repository = MagicMock()
    repository.list_cancelled_extraction_jobs_for_cleanup.return_value = [
        {
            "job_id": "job-1",
            "tenant_id": "tenant-a",
            "artifact_cleanup_keys": ["jobs/job-1/source", "documents/job-1/raw"],
        }
    ]
    repository.complete_extraction_job_artifact_cleanup.side_effect = lambda *_args, **_kwargs: stop.set()
    storage = SimpleNamespace(delete=AsyncMock(return_value=True), exists=AsyncMock(return_value=False))

    _run_cleanup_retry_loop(
        repository,
        storage,
        stop=stop,
        interval_seconds=0.01,
    )

    assert [call.args[0] for call in storage.delete.await_args_list] == [
        "jobs/job-1/source",
        "documents/job-1/raw",
    ]
    repository.complete_extraction_job_artifact_cleanup.assert_called_once()


def test_cancelled_restart_cleanup_uses_prewrite_artifact_journal():
    journaled_keys = ["jobs/job-1/source"]
    storage = SimpleNamespace(
        get=AsyncMock(return_value=b"image"),
        delete=AsyncMock(return_value=True),
        exists=AsyncMock(return_value=False),
    )
    repository = MagicMock()

    def journal(keys):
        journaled_keys.extend(keys)
        return True

    async def crash_after_journal(*_args, **kwargs):
        assert kwargs["artifact_journal"](
            ["documents/job-1/raw", "documents/job-1/extracted.json", "documents/job-1/raw.pdf"]
        )
        raise RuntimeError("worker terminated after journaling")

    durable_service = MagicMock()
    durable_service.get.return_value = None
    with patch(
        "app.workers.invoice_extraction.get_durable_invoice_service",
        return_value=durable_service,
    ):
        try:
            asyncio.run(
                _execute_extraction_job(
                    {
                        "job_id": "job-1",
                        "tenant_id": "tenant-a",
                        "source_key": "jobs/job-1/source",
                        "content_type": "image/png",
                    },
                    storage_adapter=storage,
                    extractor=crash_after_journal,
                    artifact_journal=journal,
                )
            )
        except RuntimeError as error:
            assert str(error) == "worker terminated after journaling"
        else:
            raise AssertionError("worker termination simulation must interrupt extraction")

    repository.list_cancelled_extraction_jobs_for_cleanup.return_value = [
        {
            "job_id": "job-1",
            "tenant_id": "tenant-a",
            "artifact_cleanup_keys": journaled_keys,
        }
    ]
    _cleanup_cancelled_artifacts(repository, storage)

    assert [call.args[0] for call in storage.delete.await_args_list] == journaled_keys
    repository.complete_extraction_job_artifact_cleanup.assert_called_once_with(
        "job-1",
        tenant_id="tenant-a",
        keys=journaled_keys,
    )


def test_async_route_persists_artifact_and_job_without_background_task():
    repository = MagicMock()
    repository.claim_idempotency_record.return_value = (
        True,
        {"state": "pending"},
    )
    storage = MagicMock(put=AsyncMock())
    client = TestClient(app)

    with patch(
        "app.routers.v1.invoice_jp._durable_mode_enabled",
        return_value=True,
    ), patch(
        "app.routers.v1.invoice_jp.get_invoice_repository",
        return_value=repository,
    ), patch(
        "app.routers.v1.invoice_jp.get_storage_adapter",
        return_value=storage,
    ), patch(
        "app.routers.v1.invoice_jp.asyncio.create_task",
    ) as create_task:
        response = client.post(
            "/v1/invoice-jp/extract:async",
            files={"file": ("invoice.png", b"image", "image/png")},
        )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    assert response.json() == {"job_id": job_id, "status": "received"}
    storage.put.assert_awaited_once_with(
        f"jobs/{job_id}/source",
        b"image",
        content_type="image/png",
    )
    assert repository.create_extraction_job_and_complete_idempotency.call_args.kwargs[
        "source_key"
    ] == f"jobs/{job_id}/source"
    create_task.assert_not_called()
