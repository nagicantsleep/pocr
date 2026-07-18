from __future__ import annotations

import json
from pathlib import Path


MANIFEST = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "stories"
    / "jp-enterprise-hardening"
    / "temporary-benchmark-manifest.json"
)


def test_temporary_benchmark_manifest_cannot_be_misread_as_production_evidence():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    datasets = {dataset["id"]: dataset for dataset in manifest["datasets"]}

    assert manifest["production_gate_eligible"] is False
    assert set(datasets) == {
        "Aulvem/japanese-invoice-receipt-extraction-eval",
        "llm-jp/jawildtext",
        "stockmark/OmniDocBench-JASyn",
    }
    aulvem = datasets["Aulvem/japanese-invoice-receipt-extraction-eval"]
    jawildtext = datasets["llm-jp/jawildtext"]
    omnidocbench = datasets["stockmark/OmniDocBench-JASyn"]

    assert aulvem["revision"] == "72e058a5489a902648431efc35bf477e92fbae8a"
    assert aulvem["license"] == "cc-by-nc-4.0"
    assert aulvem["provenance"] == "synthetic_text"
    assert aulvem["configurations"]["invoice"]["expected_documents"] == 20
    assert aulvem["configurations"]["receipt"]["expected_documents"] == 10
    assert aulvem["excluded_gates"] == ["real_image_ocr", "legal_issuer", "production_release"]
    assert all(
        len(config["artifact"]["sha256"]) == 64
        and config["artifact"]["url"].endswith(config["artifact"]["path"])
        for config in aulvem["configurations"].values()
    )
    assert jawildtext["revision"] == "627ca7ea7c224ffe1accff8737991fc2240784fa"
    assert jawildtext["license"] == "apache-2.0"
    assert jawildtext["supported_product_fields"] == [
        "transaction_date",
        "total_amount",
    ]
    assert jawildtext["excluded_gates"] == [
        "legal_issuer",
        "receipt_full_field_f1",
        "table_region_accuracy",
        "confidence_calibration",
        "production_release",
    ]
    assert omnidocbench["revision"] == "73ecb24624682575bd5ebf138026e711589ae5c6"
    assert omnidocbench["license"] == "cc-by-4.0"
    assert omnidocbench["expected_documents"] == 518
    assert omnidocbench["annotation"]["sha256"] == (
        "d6ef2b628626d73ae430a548005d872ff83f7477aeeb1441fd3fda8caccd99a8"
    )
    assert omnidocbench["excluded_gates"] == [
        "qualified_invoice_field_f1",
        "real_receipt_ocr",
        "production_release",
    ]
