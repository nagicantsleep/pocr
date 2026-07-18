import importlib.util
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "prepare-jawildtext-receipt-corpus.py"
_SPEC = importlib.util.spec_from_file_location("jawildtext_preparer", _SCRIPT)
preparer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(preparer)


def test_expected_fields_excludes_unadjudicated_store_name():
    assert preparer.expected_fields(
        {
            "fields": {
                "store_name": {"value": "株式会社テスト"},
                "date": {"value": "2026/07/18"},
                "total_amount": {"value": "1,200"},
            }
        }
    ) == {
        "transaction_date": "2026/07/18",
        "total_amount": "1,200",
    }


def test_prepare_rejects_a_requested_revision_that_metadata_does_not_resolve(tmp_path, monkeypatch):
    monkeypatch.setattr(
        preparer,
        "_request_json",
        lambda _url: {
            "sha": "different-revision",
            "cardData": {"license": "apache-2.0"},
        },
    )

    with pytest.raises(RuntimeError, match="did not resolve"):
        preparer.prepare(tmp_path, 1, revision="expected-revision")
