"""Regression tests for production-gate field comparison."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_evaluator():
    path = Path("scripts/evaluate-jp-enterprise.py")
    spec = spec_from_file_location("evaluate_jp_enterprise", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_semantically_equivalent_receipt_date_and_jpy_amount_match():
    evaluator = _load_evaluator()

    metrics = evaluator.field_metrics(
        {
            "transaction_date": "2025年11月21日(金)",
            "total_amount": "￥2,320",
            "issuer_name": "伝説のすた丼屋 ヨドバシAkiba店",
        },
        {
            "transaction_date": {"value": "2025-11-21"},
            "total_amount": {"value": 2320},
            "issuer_name": {"value": "株式会社アントワークス"},
        },
    )

    assert metrics["transaction_date"]["f1"] == 1.0
    assert metrics["total_amount"]["f1"] == 1.0
    assert metrics["issuer_name"]["f1"] == 0.0
