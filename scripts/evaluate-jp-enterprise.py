#!/usr/bin/env python3
"""Evaluate JP extraction, calibration, table, and search relevance gates.

This tool intentionally separates metric calculation from proof provenance.
Synthetic fixtures can exercise the harness but are rejected by
--production-gate and never reported as production accuracy evidence.
"""

from __future__ import annotations

import argparse
import collections
import json
import mimetypes
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.dates import normalize_japanese_date
from app.utils.money import normalize_amount

PRODUCTION_SOURCES = {"real", "public_real", "consented_real", "approved_real"}
EXPECTED_FIELD_ALIASES = {"registration_number": "issuer_registration_number"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalise(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.strip().casefold().split())
    if isinstance(value, float):
        return f"{value:.8f}"
    return _json(value)


def _value(payload: Any) -> Any:
    if isinstance(payload, dict) and "value" in payload:
        return payload["value"]
    return payload


def _field_values_match(field: str, expected: Any, actual: Any) -> bool:
    """Compare field values after lossless date and JPY presentation normalization."""
    if expected is None or actual is None:
        return False
    if field == "transaction_date":
        expected_date = normalize_japanese_date(str(expected))
        actual_date = normalize_japanese_date(str(actual))
        return expected_date is not None and expected_date == actual_date
    if field == "total_amount":
        expected_amount = normalize_amount(str(expected))
        actual_amount = normalize_amount(str(actual))
        return expected_amount is not None and expected_amount == actual_amount
    return _normalise(expected) == _normalise(actual)

def _content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _post_multipart(
    url: str,
    file_path: Path,
    headers: dict[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    boundary = f"----jp-eval-{uuid.uuid4().hex}"
    file_bytes = file_path.read_bytes()
    content_type = _content_type(file_path)
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{file_path.name}"\r\n'
            ).encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            file_bytes,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{exc.code} POST {url}: {body_text}") from exc


def _get_json(url: str, headers: dict[str, str], timeout_seconds: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{exc.code} GET {url}: {body_text}") from exc


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _find_image(stem: Path) -> Path | None:
    for suffix in (".png", ".jpg", ".jpeg", ".tiff", ".pdf"):
        candidate = stem.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return None


def load_fixture_records(fixtures_dir: Path) -> list[dict[str, Any]]:
    """Load the versioned `<name>.json` plus `<name>.meta.json` fixture shape."""
    records: list[dict[str, Any]] = []
    for metadata_path in sorted(fixtures_dir.rglob("*.meta.json")):
        stem = metadata_path.with_name(metadata_path.name.removesuffix(".meta.json"))
        expected_path = stem.with_suffix(".json")
        image_path = _find_image(stem)
        if not expected_path.exists() or image_path is None:
            continue
        records.append(
            {
                "id": str(stem.relative_to(fixtures_dir)).replace("\\", "/"),
                "metadata": _load_json(metadata_path),
                "expected": _load_json(expected_path),
                "image_path": image_path,
            }
        )
    return records


def _provenance_errors(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for record in records:
        source = str(record["metadata"].get("source", "")).strip().casefold()
        if not source:
            errors.append(f"{record['id']}: metadata.source is required")
        elif source not in PRODUCTION_SOURCES:
            errors.append(
                f"{record['id']}: metadata.source={source!r} is not an approved real-data provenance"
            )
        elif record["metadata"].get("production_gate_eligible") is not True:
            blocker = record["metadata"].get(
                "production_gate_blocker",
                "metadata does not attest product-field adjudication",
            )
            errors.append(f"{record['id']}: {blocker}")
    return errors


def field_metrics(
    expected_fields: dict[str, Any],
    actual_fields: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Compute exact-value precision, recall, and F1 per expected field."""
    output: dict[str, dict[str, Any]] = {}
    for field, expected in expected_fields.items():
        if field == "line_items":
            continue
        actual_field = EXPECTED_FIELD_ALIASES.get(field, field)
        actual = _value(actual_fields.get(actual_field))
        expected_present = expected is not None
        actual_present = actual is not None
        match = (
            expected_present
            and actual_present
            and _field_values_match(field, expected, actual)
        )
        tp = int(match)
        fp = int(actual_present and not match)
        fn = int(expected_present and not match)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        output[field] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "expected": expected,
            "actual": actual,
            "actual_field": actual_field,
        }
    return output


def aggregate_field_metrics(
    per_fixture: list[dict[str, dict[str, Any]]],
) -> dict[str, dict[str, float | int]]:
    totals: dict[str, collections.Counter[str]] = {}
    for fixture in per_fixture:
        for field, metric in fixture.items():
            totals.setdefault(field, collections.Counter()).update(
                {key: int(metric[key]) for key in ("tp", "fp", "fn")}
            )
    output: dict[str, dict[str, float | int]] = {}
    for field, counts in sorted(totals.items()):
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        output[field] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        }
    return output


def expected_line_item_metrics(expected: list[Any], actual: list[Any]) -> dict[str, float | int]:
    """Compute exact line-item F1 while retaining duplicate occurrences."""
    expected_counts = collections.Counter(_normalise(value) for value in expected)
    actual_counts = collections.Counter(_normalise(value) for value in actual)
    tp = sum((expected_counts & actual_counts).values())
    fp = sum((actual_counts - expected_counts).values())
    fn = sum((expected_counts - actual_counts).values())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def expected_calibration(
    expected_fields: dict[str, Any],
    actual_fields: dict[str, Any],
    bins: int = 10,
) -> list[tuple[float, bool]]:
    observations: list[tuple[float, bool]] = []
    for field, expected in expected_fields.items():
        actual = actual_fields.get(EXPECTED_FIELD_ALIASES.get(field, field))
        if not isinstance(actual, dict) or "confidence" not in actual:
            continue
        confidence = actual["confidence"]
        if not isinstance(confidence, (int, float)):
            continue
        observations.append(
            (
                max(0.0, min(1.0, float(confidence))),
                expected is not None and _field_values_match(field, expected, _value(actual)),
            )
        )
    return observations


def calibration_metrics(observations: list[tuple[float, bool]], bins: int = 10) -> dict[str, Any]:
    """Calculate expected calibration error from field confidence observations."""
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for confidence, correct in observations:
        buckets[min(bins - 1, int(confidence * bins))].append((confidence, correct))
    total = len(observations)
    ece = 0.0
    report = []
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        avg_confidence = sum(item[0] for item in bucket) / len(bucket)
        accuracy = sum(item[1] for item in bucket) / len(bucket)
        ece += len(bucket) / total * abs(accuracy - avg_confidence)
        report.append(
            {
                "lower": index / bins,
                "upper": (index + 1) / bins,
                "count": len(bucket),
                "accuracy": accuracy,
                "mean_confidence": avg_confidence,
            }
        )
    return {"observations": total, "ece": ece if total else None, "bins": report}


def _bbox(box: Any) -> tuple[float, float, float, float] | None:
    if isinstance(box, list) and len(box) == 4:
        left, top, right, bottom = (float(value) for value in box)
    elif isinstance(box, dict):
        if {"x", "y", "width", "height"} <= box.keys():
            left, top = float(box["x"]), float(box["y"])
            right, bottom = left + float(box["width"]), top + float(box["height"])
        elif {"left", "top", "right", "bottom"} <= box.keys():
            left, top, right, bottom = (float(box[key]) for key in ("left", "top", "right", "bottom"))
        else:
            return None
    else:
        return None
    return (left, top, right, bottom) if right > left and bottom > top else None


def _iou(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    if not intersection:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / (first_area + second_area - intersection)


def table_region_metrics(expected: list[Any], actual: list[Any], iou_threshold: float = 0.5) -> dict[str, float | int]:
    """Match expected and observed table boxes greedily by IoU."""
    expected_boxes = [box for item in expected if (box := _bbox(item.get("bbox") if isinstance(item, dict) else item))]
    actual_boxes = [box for item in actual if (box := _bbox(item.get("bbox") if isinstance(item, dict) else item))]
    matched_expected_by_actual = [-1] * len(actual_boxes)

    def find_match(expected_index: int, visited_actual: set[int]) -> bool:
        for actual_index, actual_box in enumerate(actual_boxes):
            if actual_index in visited_actual:
                continue
            if _iou(expected_boxes[expected_index], actual_box) < iou_threshold:
                continue
            visited_actual.add(actual_index)
            previous_expected = matched_expected_by_actual[actual_index]
            if previous_expected == -1 or find_match(previous_expected, visited_actual):
                matched_expected_by_actual[actual_index] = expected_index
                return True
        return False

    tp = sum(find_match(index, set()) for index in range(len(expected_boxes)))
    fp, fn = len(actual_boxes) - tp, len(expected_boxes) - tp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "evaluable": bool(expected_boxes or actual_boxes),
    }


def reciprocal_rank(result_ids: list[str], relevant_ids: set[str]) -> float:
    for rank, document_id in enumerate(result_ids, start=1):
        if document_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    return sum(float(row["reciprocal_rank"]) for row in rows) / len(rows)


def _headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _unit_interval(value: str) -> float:
    parsed = float(value)
    if not 0.0 < parsed <= 1.0:
        raise argparse.ArgumentTypeError("must be greater than 0 and no more than 1")
    return parsed


def evaluate_extraction(args: argparse.Namespace) -> dict[str, Any]:
    if not args.allow_write:
        raise RuntimeError("extraction posts real documents; rerun with --allow-write")
    records = load_fixture_records(Path(args.fixtures).resolve())
    if not records:
        raise RuntimeError(f"No versioned fixture triples found in {args.fixtures}")
    provenance_errors = _provenance_errors(records)
    if args.production_gate and provenance_errors:
        raise RuntimeError("; ".join(provenance_errors))

    base_url = args.base_url.rstrip("/")
    headers = _headers(args.bearer_token)
    fixture_metrics: list[dict[str, Any]] = []
    per_field: list[dict[str, dict[str, Any]]] = []
    calibration: list[tuple[float, bool]] = []
    table_totals: list[dict[str, float | int]] = []
    line_item_totals: list[dict[str, float | int]] = []
    table_blockers: list[str] = []
    for record in records:
        response = _post_multipart(
            f"{base_url}/v1/invoice-jp/extract",
            record["image_path"],
            headers,
            args.timeout_seconds,
        )
        expected = record["expected"]
        expected_fields = expected.get("fields", {})
        actual_fields = response.get("fields", {})
        metrics = field_metrics(expected_fields, actual_fields)
        per_field.append(metrics)
        calibration.extend(expected_calibration(expected_fields, actual_fields))
        if isinstance(expected_fields.get("line_items"), list):
            line_item_totals.append(
                expected_line_item_metrics(expected_fields["line_items"], response.get("line_items", []))
            )
        expected_tables = expected.get("table_regions", [])
        actual_tables = response.get("table_regions", response.get("tables", []))
        if isinstance(expected_tables, list) and isinstance(actual_tables, list):
            table_totals.append(table_region_metrics(expected_tables, actual_tables, args.table_iou_threshold))
        elif expected_tables:
            table_blockers.append(
                f"{record['id']}: expected table_regions exist but the public response has no bbox list"
            )
        fixture_metrics.append(
            {
                "fixture": record["id"],
                "field_metrics": metrics,
                "response_document_id": response.get("document_id"),
            }
        )

    report: dict[str, Any] = {
        "kind": "jp_extraction_evaluation",
        "scope": "production_candidate" if not provenance_errors else "development_only",
        "fixture_count": len(records),
        "provenance_errors": provenance_errors,
        "field_metrics": aggregate_field_metrics(per_field),
        "calibration": calibration_metrics(calibration, args.ece_bins),
        "fixtures": fixture_metrics,
    }
    if line_item_totals:
        report["line_item_metrics"] = _aggregate_counts(line_item_totals)
    if table_blockers:
        report["table_region_metrics"] = {
            "evaluable": False,
            "blocker": "; ".join(table_blockers),
        }
    elif table_totals:
        report["table_region_metrics"] = _aggregate_counts(table_totals)
    else:
        report["table_region_metrics"] = {
            "evaluable": False,
            "blocker": "No table_regions annotations in the fixture ground truth.",
        }
    ece = report["calibration"]["ece"]
    field_scores = report["field_metrics"]
    field_gates = {
        field: field_scores[field]["f1"] >= minimum
        for field, minimum in {
            "registration_number": 0.85,
            "issuer_registration_number": 0.85,
            "total_amount": 0.85,
            "transaction_date": 0.85,
            "issuer_name": 0.80,
        }.items()
        if field in field_scores
    }
    if "line_item_metrics" in report:
        field_gates["line_items"] = report["line_item_metrics"]["f1"] >= 0.80
    table_gate = (
        report["table_region_metrics"].get("f1", 0.0) >= 0.90
        if report["table_region_metrics"].get("evaluable")
        else False
    )
    report["gate_checks"] = {
        "ece_le_0_05": ece is not None and ece <= 0.05,
        "field_f1": field_gates,
        "table_region_f1_ge_0_90": table_gate,
    }
    report["gate_pass"] = (
        report["scope"] == "production_candidate"
        and all(field_gates.values())
        and bool(report["gate_checks"]["ece_le_0_05"])
        and table_gate
    )
    return report


def _aggregate_counts(values: list[dict[str, float | int]]) -> dict[str, float | int | bool]:
    tp = sum(int(value["tp"]) for value in values)
    fp = sum(int(value["fp"]) for value in values)
    fn = sum(int(value["fn"]) for value in values)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "evaluable": True,
    }


def evaluate_search_mrr(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _load_json(Path(args.queries).resolve())
    if not isinstance(manifest, dict) or not isinstance(manifest.get("queries"), list):
        raise RuntimeError("Query manifest must be an object with a queries array.")
    source = str(manifest.get("corpus_source", "")).strip().casefold()
    production_source = source in PRODUCTION_SOURCES
    if args.production_gate and not production_source:
        raise RuntimeError("production gate requires an approved real manifest.corpus_source")
    if len(manifest["queries"]) != args.expected_queries:
        raise RuntimeError(
            f"Expected exactly {args.expected_queries} labeled queries, found {len(manifest['queries'])}."
        )

    base_url, headers = args.base_url.rstrip("/"), _headers(args.bearer_token)
    by_mode: dict[str, list[dict[str, Any]]] = {}
    for mode in args.modes:
        rows: list[dict[str, Any]] = []
        for item in manifest["queries"]:
            query = item.get("query")
            relevant = item.get("relevant_document_ids")
            if not isinstance(query, str) or not isinstance(relevant, list) or not relevant:
                raise RuntimeError("Every query needs a non-empty query and relevant_document_ids.")
            url = f"{base_url}/v1/search?{urllib.parse.urlencode({'q': query, 'mode': mode, 'limit': args.limit})}"
            response = _get_json(url, headers, args.timeout_seconds)
            if response.get("degraded"):
                raise RuntimeError(f"{mode} search degraded for query {query!r}; MRR gate is invalid.")
            result_ids = [result["document_id"] for result in response.get("results", [])]
            rows.append(
                {
                    "query": query,
                    "reciprocal_rank": reciprocal_rank(result_ids, set(relevant)),
                    "result_ids": result_ids,
                }
            )
        by_mode[mode] = rows
    scores = {mode: mean_reciprocal_rank(rows) for mode, rows in by_mode.items()}
    hybrid = scores.get("hybrid")
    baselines = [score for mode, score in scores.items() if mode != "hybrid" and score is not None]
    report = {
        "kind": "jp_search_mrr",
        "scope": "production_candidate" if production_source else "development_only",
        "corpus_source": manifest.get("corpus_source"),
        "query_count": len(manifest["queries"]),
        "mrr": scores,
        "mrr_ge_0_7": {mode: score is not None and score >= 0.7 for mode, score in scores.items()},
        "hybrid_meets_baseline": hybrid is not None and (not baselines or hybrid >= max(baselines)),
        "queries": by_mode,
    }
    report["gate_pass"] = (
        report["scope"] == "production_candidate"
        and all(report["mrr_ge_0_7"].values())
        and bool(report["hybrid_meets_baseline"])
    )
    return report


def _write_report(report: dict[str, Any], output: str | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        Path(output).write_text(rendered + "\n", encoding="utf-8")
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(rendered)
    else:
        stream.write((rendered + "\n").encode("utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    extraction = subparsers.add_parser("extraction", help="Run F1, ECE, and table metrics through the public API.")
    extraction.add_argument("--fixtures", default=str(PROJECT_ROOT / "tests" / "fixtures" / "invoice-jp"))
    extraction.add_argument("--base-url", required=True)
    extraction.add_argument("--bearer-token")
    extraction.add_argument("--timeout-seconds", type=float, default=60.0)
    extraction.add_argument("--ece-bins", type=_positive_int, default=10)
    extraction.add_argument("--table-iou-threshold", type=_unit_interval, default=0.5)
    extraction.add_argument("--allow-write", action="store_true")
    extraction.add_argument("--production-gate", action="store_true")
    extraction.add_argument("--output")
    extraction.set_defaults(handler=evaluate_extraction)

    mrr = subparsers.add_parser("search-mrr", help="Run labeled-query MRR through /v1/search.")
    mrr.add_argument("--queries", required=True, help="JSON object with corpus_source and queries.")
    mrr.add_argument("--base-url", required=True)
    mrr.add_argument("--bearer-token")
    mrr.add_argument("--timeout-seconds", type=float, default=30.0)
    mrr.add_argument("--limit", type=int, default=20)
    mrr.add_argument("--expected-queries", type=int, default=50)
    mrr.add_argument("--modes", nargs="+", default=["keyword", "semantic", "hybrid"])
    mrr.add_argument("--production-gate", action="store_true")
    mrr.add_argument("--output")
    mrr.set_defaults(handler=evaluate_search_mrr)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = args.handler(args)
        _write_report(report, args.output)
        if report.get("gate_pass") is False:
            return 3
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
