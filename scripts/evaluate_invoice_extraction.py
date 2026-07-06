#!/usr/bin/env python3
"""Evaluate invoice extraction accuracy against golden fixtures."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# Ensure we can import from project root
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from app.services.layout_analyzer import analyze_layout
from app.services.invoice_extractor import extract_invoice

FIXTURES_DIR = _PROJECT_ROOT / "tests" / "fixtures" / "invoice_eval"
FIELDS = [
    "issuer_registration_number",
    "transaction_date",
    "total_amount",
    "issuer_name",
    "recipient_name",
]


def load_fixtures() -> list[dict]:
    """Load all fixture files from the eval directory."""
    fixtures = []
    for fpath in sorted(FIXTURES_DIR.glob("*.json")):
        if fpath.name == "generate_fixtures.py":
            continue
        with open(fpath, encoding="utf-8") as f:
            fixtures.append(json.load(f))
    return fixtures


def evaluate_field(expected, actual) -> bool:
    """Compare expected vs actual field value."""
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    return str(expected) == str(actual)


def get_expected(fixture: dict, field: str):
    """Get expected value for a field from the fixture."""
    exp = fixture.get("expected", {})
    if field == "issuer_registration_number":
        return exp.get("issuer_registration_number")
    elif field == "transaction_date":
        return exp.get("transaction_date")
    elif field == "total_amount":
        return exp.get("total_amount")
    elif field == "issuer_name":
        return exp.get("issuer_name")
    elif field == "recipient_name":
        return exp.get("recipient_name")
    return None


def get_actual(result, field: str):
    """Get actual extracted value from the pipeline response."""
    inv = result.invoice
    if field == "issuer_registration_number":
        return inv.issuer_registration_number
    elif field == "transaction_date":
        return inv.transaction_date
    elif field == "total_amount":
        return inv.total_amount
    elif field == "issuer_name":
        return inv.issuer_name
    elif field == "recipient_name":
        return inv.recipient_name
    return None


def get_category(name: str) -> str:
    """Get category from fixture name."""
    parts = name.split("_")
    prefix = parts[0]
    # Normalize categories
    cat_map = {
        "simple": "simple",
        "multiline": "multiline",
        "receipt": "receipt",
        "poor": "poor_quality",
        "mixed": "mixed_tax",
        "non": "non_invoice",
        "edge": "edge",
    }
    return cat_map.get(prefix, prefix)


def run_evaluation():
    """Run extraction on all fixtures, compute accuracy metrics."""
    fixtures = load_fixtures()
    results = []

    print(f"Loaded {len(fixtures)} fixtures")
    print()

    for fixture in fixtures:
        name = fixture["name"]
        expected = fixture["expected"]
        ocr_lines = fixture["ocr_lines"]

        # Run extraction pipeline
        response = extract_invoice(ocr_lines, request_id=f"eval-{name}")

        # Compare fields
        for field in FIELDS:
            exp_val = get_expected(fixture, field)
            act_val = get_actual(response, field)
            match = evaluate_field(exp_val, act_val)
            results.append({
                "fixture": name,
                "field": field,
                "expected": exp_val,
                "actual": act_val,
                "match": match,
            })

        # Tax breakdown
        exp_tax = expected.get("tax_by_rate", {})
        act_tax = response.invoice.consumption_tax_by_rate or {}
        for rate in ("8%", "10%"):
            exp_tax_val = exp_tax.get(rate)
            act_tax_val = act_tax.get(rate)
            match_tax = exp_tax_val == act_tax_val
            results.append({
                "fixture": name,
                "field": f"tax_{rate}",
                "expected": exp_tax_val,
                "actual": act_tax_val,
                "match": match_tax,
            })

        # Document type
        exp_doc_type = expected.get("document_type")
        act_doc_type = response.document_type
        match_doc = exp_doc_type == act_doc_type
        results.append({
            "fixture": name,
            "field": "document_type",
            "expected": exp_doc_type,
            "actual": act_doc_type,
            "match": match_doc,
        })

        # Line items count
        exp_li = expected.get("line_items_count", 0)
        act_li = len(response.invoice.line_items) if response.invoice.line_items else 0
        results.append({
            "fixture": name,
            "field": "line_items_count",
            "expected": exp_li,
            "actual": act_li,
            "match": exp_li == act_li,
        })

        # needs_review
        exp_review = expected.get("needs_review", False)
        act_review = response.needs_review
        results.append({
            "fixture": name,
            "field": "needs_review",
            "expected": exp_review,
            "actual": act_review,
            "match": exp_review == act_review,
        })

    # ---- Compute and print metrics ----
    total = len(results)
    if total == 0:
        print("No results to report.")
        return

    correct = sum(1 for r in results if r["match"])

    print("=" * 70)
    print("  Invoice Extraction Evaluation Report")
    print("=" * 70)
    print(f"  Total fixtures:          {len(fixtures)}")
    print(f"  Total field comparisons: {total}")
    print(f"  Overall accuracy:        {correct}/{total} ({correct / total * 100:.1f}%)")
    print()

    # Per-field accuracy
    print("  Per-field accuracy:")
    print(f"  {'Field':<35} {'Correct':<10} {'Total':<8} {'Accuracy':<10}")
    print(f"  {'-'*35} {'-'*10} {'-'*8} {'-'*10}")
    for field in FIELDS + ["document_type", "tax_8%", "tax_10%", "line_items_count", "needs_review"]:
        field_results = [r for r in results if r["field"] == field]
        if not field_results:
            continue
        field_correct = sum(1 for r in field_results if r["match"])
        field_total = len(field_results)
        pct = field_correct / field_total * 100
        print(f"  {field:<35} {field_correct:<10} {field_total:<8} {pct:.1f}%")
    print()

    # Per-category accuracy
    print("  Per-category accuracy:")
    print(f"  {'Category':<25} {'Correct':<10} {'Total':<8} {'Accuracy':<10}")
    print(f"  {'-'*25} {'-'*10} {'-'*8} {'-'*10}")
    categories = {}
    for r in results:
        cat = get_category(r["fixture"])
        categories.setdefault(cat, [])
        categories[cat].append(r)
    for cat in sorted(categories):
        cat_results = categories[cat]
        cat_correct = sum(1 for r in cat_results if r["match"])
        cat_total = len(cat_results)
        pct = cat_correct / cat_total * 100
        print(f"  {cat:<25} {cat_correct:<10} {cat_total:<8} {pct:.1f}%")
    print()

    # Auto-approval metrics
    print("  Auto-approval metrics:")
    auto_approve = sum(1 for r in results
                       if r["field"] == "needs_review" and r["actual"] is False)
    needs_review = sum(1 for r in results
                       if r["field"] == "needs_review" and r["actual"] is True)
    print(f"  Auto-approved:     {auto_approve}")
    print(f"  Needs review:      {needs_review}")

    # False auto-approvals: negative samples that auto-approved
    false_auto = sum(1 for r in results
                     if r["field"] == "needs_review" and r["actual"] is False
                     and get_category(r["fixture"]) == "non_invoice")
    print(f"  False auto-approvals (non-invoice): {false_auto}")
    print()

    # Line items with table detection
    print("  Line item extraction:")
    li_fixtures = [r for r in results if r["field"] == "line_items_count"]
    li_correct = sum(1 for r in li_fixtures if r["match"])
    li_total = len(li_fixtures)
    print(f"  Line items count accuracy: {li_correct}/{li_total} ({li_correct / li_total * 100:.1f}%)")
    print()

    # Per-fixture detailed results for debugging
    print("=" * 70)
    print("  Detail: per-fixture field accuracy")
    print("=" * 70)
    for fixture in fixtures:
        name = fixture["name"]
        fix_results = [r for r in results if r["fixture"] == name]
        fix_correct = sum(1 for r in fix_results if r["match"])
        fix_total = len(fix_results)
        mismatches = [r for r in fix_results if not r["match"]]
        status = "OK" if not mismatches else "ISSUES"
        print(f"  {name:<30} {fix_correct}/{fix_total} {status}")
        for m in mismatches:
            print(f"    {m['field']:<30} expected={m['expected']!r} actual={m['actual']!r}")
    print()


if __name__ == "__main__":
    run_evaluation()
