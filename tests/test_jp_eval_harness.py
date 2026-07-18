"""Focused checks for the standalone JP evaluation harness."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "evaluate-jp-enterprise.py"
_SPEC = importlib.util.spec_from_file_location("jp_eval_harness", _SCRIPT)
assert _SPEC and _SPEC.loader
eval_harness = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(eval_harness)

_BENCHMARK_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "benchmark-jp-enterprise.py"
_BENCHMARK_SPEC = importlib.util.spec_from_file_location("jp_benchmark_harness", _BENCHMARK_SCRIPT)
assert _BENCHMARK_SPEC and _BENCHMARK_SPEC.loader
benchmark_harness = importlib.util.module_from_spec(_BENCHMARK_SPEC)
_BENCHMARK_SPEC.loader.exec_module(benchmark_harness)


def test_field_metrics_counts_wrong_value_as_false_positive_and_negative():
    metrics = eval_harness.field_metrics(
        {"issuer_name": "Acme", "total_amount": 100},
        {"issuer_name": {"value": "Other", "confidence": 0.7}, "total_amount": {"value": 100}},
    )

    assert metrics["issuer_name"]["tp"] == 0
    assert metrics["issuer_name"]["fp"] == 1
    assert metrics["issuer_name"]["fn"] == 1
    assert metrics["total_amount"]["f1"] == 1.0


def test_calibration_and_table_metrics_are_explicit_about_measurement():
    calibration = eval_harness.calibration_metrics([(0.9, True), (0.9, False)], bins=10)
    tables = eval_harness.table_region_metrics(
        [{"bbox": [0, 0, 10, 10]}],
        [{"bbox": [0, 0, 10, 10]}, {"bbox": [20, 20, 30, 30]}],
    )

    assert calibration["observations"] == 2
    assert calibration["ece"] == 0.4
    assert tables["tp"] == 1
    assert tables["fp"] == 1
    assert tables["f1"] < 1.0


def test_table_matching_uses_maximum_one_to_one_matching():
    tables = eval_harness.table_region_metrics(
        [{"bbox": [0, 0, 8, 10]}, {"bbox": [0, 0, 10, 10]}],
        [{"bbox": [0, 0, 10, 10]}, {"bbox": [0, 0, 4, 10]}],
        iou_threshold=0.5,
    )

    assert tables["tp"] == 2
    assert tables["f1"] == 1.0


def test_synthetic_fixture_is_rejected_as_production_proof():
    errors = eval_harness._provenance_errors(
        [{"id": "sample_001", "metadata": {"source": "synthetic"}}]
    )

    assert errors == [
        "sample_001: metadata.source='synthetic' is not an approved real-data provenance"
    ]

def test_unadjudicated_real_fixture_is_rejected_as_production_proof():
    errors = eval_harness._provenance_errors(
        [{
            "id": "receipt_001",
            "metadata": {
                "source": "public_real",
                "production_gate_eligible": False,
                "production_gate_blocker": "store_name is not a legal issuer",
            },
        }]
    )

    assert errors == ["receipt_001: store_name is not a legal issuer"]


def test_legacy_ground_truth_registration_alias_uses_the_public_api_field():
    metrics = eval_harness.field_metrics(
        {"registration_number": "T1234567890123"},
        {"issuer_registration_number": {"value": "T1234567890123", "confidence": 0.9}},
    )

    assert metrics["registration_number"]["actual_field"] == "issuer_registration_number"
    assert metrics["registration_number"]["f1"] == 1.0


def test_mrr_uses_first_relevant_result():
    assert eval_harness.reciprocal_rank(["x", "target", "other"], {"target"}) == 0.5
    assert eval_harness.mean_reciprocal_rank(
        [{"reciprocal_rank": 1.0}, {"reciprocal_rank": 0.5}]
    ) == 0.75


def test_benchmark_requires_known_real_corpus_provenance():
    assert benchmark_harness._non_synthetic({"corpus_source": "approved_real"}) is True
    assert benchmark_harness._non_synthetic({"corpus_source": "synthetic"}) is False
    assert benchmark_harness._non_synthetic({"corpus_source": "unknown"}) is False
    benchmark_harness._validate_provenance(
        {"corpus_source": "approved_real", "production_gate_eligible": True},
        "reference-machine",
    )
    with pytest.raises(RuntimeError, match="adjudication"):
        benchmark_harness._validate_provenance(
            {"corpus_source": "public_real", "production_gate_eligible": False},
            "reference-machine",
        )


def test_extraction_refuses_write_requests_without_explicit_opt_in():
    with pytest.raises(RuntimeError, match="--allow-write"):
        eval_harness.evaluate_extraction(SimpleNamespace(allow_write=False))


def test_invalid_ece_bin_count_is_rejected_by_the_cli_before_execution():
    with pytest.raises(SystemExit):
        eval_harness.build_parser().parse_args(
            ["extraction", "--base-url", "http://localhost", "--ece-bins", "0"]
        )


def test_completed_job_without_public_document_is_not_an_ingest_completion(monkeypatch):
    monkeypatch.setattr(
        benchmark_harness,
        "_request",
        lambda *_args, **_kwargs: (200, json.dumps({"status": "completed"}).encode()),
    )

    state, response = benchmark_harness._wait_for_job(
        "http://localhost",
        "job-1",
        {},
        timeout_seconds=1,
        poll_seconds=0,
    )

    assert state == "completed_without_document"
    assert response == {"status": "completed"}


def test_legacy_completed_job_preserves_nested_document_ids(monkeypatch):
    payload = {"status": "completed", "results": [{"document_id": "doc-1"}]}
    monkeypatch.setattr(
        benchmark_harness,
        "_request",
        lambda *_args, **_kwargs: (200, json.dumps(payload).encode()),
    )

    state, response = benchmark_harness._wait_for_job(
        "http://localhost",
        "job-1",
        {},
        timeout_seconds=1,
        poll_seconds=0,
    )

    assert state == "completed"
    assert benchmark_harness._job_document_ids(response) == ["doc-1"]


def test_failed_gate_returns_nonzero_exit_code(monkeypatch):
    parser = SimpleNamespace(
        parse_args=lambda _argv: SimpleNamespace(
            handler=lambda _args: {"gate_pass": False},
            output=None,
        )
    )
    monkeypatch.setattr(eval_harness, "build_parser", lambda: parser)

    assert eval_harness.main([]) == 3
