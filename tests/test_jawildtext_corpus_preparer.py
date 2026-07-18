import importlib.util
from pathlib import Path


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
