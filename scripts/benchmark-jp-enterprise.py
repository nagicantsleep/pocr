#!/usr/bin/env python3
"""Benchmark the live JP enterprise API with explicit workload provenance.

The script never creates documents unless --allow-write is supplied. A
benchmark is not a production gate unless its manifest declares a non-synthetic
corpus and the caller identifies the reference machine.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import mimetypes
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


PRODUCTION_SOURCES = {"real", "public_real", "consented_real", "approved_real"}


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _request(
    url: str,
    method: str,
    headers: dict[str, str],
    timeout_seconds: float,
    body: bytes | None = None,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _multipart_upload(
    url: str,
    file_path: Path,
    headers: dict[str, str],
    timeout_seconds: float,
    idempotency_key: str,
) -> tuple[int, dict[str, Any]]:
    boundary = f"----jp-benchmark-{uuid.uuid4().hex}"
    content = file_path.read_bytes()
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    status, payload = _request(
        url,
        "POST",
        {
            **headers,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Idempotency-Key": idempotency_key,
        },
        timeout_seconds,
        body,
    )
    try:
        return status, json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        return status, {"raw": payload.decode("utf-8", errors="replace")}


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _non_synthetic(manifest: dict[str, Any]) -> bool:
    return str(manifest.get("corpus_source", "")).strip().casefold() in PRODUCTION_SOURCES


def _validate_provenance(manifest: dict[str, Any], reference_machine: str | None) -> None:
    if not _non_synthetic(manifest):
        raise RuntimeError("manifest.corpus_source must identify a non-synthetic corpus")
    if manifest.get("production_gate_eligible") is not True:
        blocker = manifest.get(
            "production_gate_blocker",
            "manifest does not attest product-field adjudication",
        )
        raise RuntimeError(str(blocker))
    if not reference_machine:
        raise RuntimeError("--reference-machine is required for a production performance gate")


def _job_document_ids(response: dict[str, Any]) -> list[str]:
    document_ids = [response["document_id"]] if isinstance(response.get("document_id"), str) else []
    for item in response.get("results", []):
        if isinstance(item, dict) and isinstance(item.get("document_id"), str):
            document_ids.append(item["document_id"])
    return list(dict.fromkeys(document_ids))


def _wait_for_job(
    base_url: str,
    job_id: str,
    headers: dict[str, str],
    timeout_seconds: float,
    poll_seconds: float,
) -> tuple[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status, payload = _request(
            f"{base_url}/v1/jobs/{urllib.parse.quote(job_id)}",
            "GET",
            headers,
            timeout_seconds=min(timeout_seconds, 30.0),
        )
        if status != 200:
            return f"status_http_{status}", {}
        response = json.loads(payload.decode("utf-8"))
        state = str(response.get("status", "unknown")).casefold()
        if state in {"completed", "success"}:
            if _job_document_ids(response):
                return "completed", response
            return "completed_without_document", response
        if state in {"failed", "cancelled"}:
            return state, response
        time.sleep(poll_seconds)
    return "timeout", {}


def benchmark_ingest(args: argparse.Namespace) -> dict[str, Any]:
    if not args.allow_write:
        raise RuntimeError("ingest sends real write traffic; rerun with --allow-write")
    manifest = _load_json(Path(args.manifest).resolve())
    if not isinstance(manifest, dict) or not isinstance(manifest.get("documents"), list):
        raise RuntimeError("Ingest manifest must contain a documents array.")
    _validate_provenance(manifest, args.reference_machine)
    documents = manifest["documents"]
    if len(documents) != args.expected_documents:
        raise RuntimeError(
            f"Expected exactly {args.expected_documents} workload documents, found {len(documents)}."
        )
    source_ids = [item.get("source_id") for item in documents if isinstance(item, dict)]
    if len(source_ids) != len(documents) or any(not isinstance(value, str) or not value for value in source_ids):
        raise RuntimeError("Every workload document requires a non-empty source_id.")
    if len(set(source_ids)) != len(source_ids):
        raise RuntimeError("Workload source_id values must be unique.")
    base_url, headers = args.base_url.rstrip("/"), _headers(args.bearer_token)
    started = time.perf_counter()

    def one(index: int, item: dict[str, Any]) -> dict[str, Any]:
        path_value = item.get("path")
        if not isinstance(path_value, str):
            return {"index": index, "state": "invalid_manifest"}
        file_path = (Path(args.manifest).parent / path_value).resolve()
        if not file_path.is_file():
            return {"index": index, "state": "missing_file", "path": str(file_path)}
        sent_at = time.perf_counter()
        status, response = _multipart_upload(
            f"{base_url}/v1/invoice-jp/extract:async",
            file_path,
            headers,
            args.request_timeout_seconds,
            f"benchmark-{uuid.uuid4().hex}",
        )
        accepted_seconds = time.perf_counter() - sent_at
        if status not in {200, 201, 202} or not isinstance(response.get("job_id"), str):
            return {"index": index, "state": f"submit_http_{status}", "accepted_seconds": accepted_seconds}
        terminal, job_response = _wait_for_job(
            base_url,
            response["job_id"],
            headers,
            args.job_timeout_seconds,
            args.poll_seconds,
        )
        return {
            "index": index,
            "job_id": response["job_id"],
            "state": terminal,
            "document_ids": _job_document_ids(job_response),
            "accepted_seconds": accepted_seconds,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda pair: one(*pair), enumerate(documents)))
    elapsed = time.perf_counter() - started
    accepted = [row["accepted_seconds"] for row in results if "accepted_seconds" in row]
    completed_rows = [row for row in results if row["state"] == "completed"]
    completed_document_ids = [
        document_id
        for row in completed_rows
        for document_id in row.get("document_ids", [])
    ]
    unique_completed_document_ids = set(completed_document_ids)
    one_document_per_input = all(len(row.get("document_ids", [])) == 1 for row in completed_rows)
    all_inputs_completed = len(completed_rows) == len(documents)
    distinct_documents_completed = len(unique_completed_document_ids) == len(documents)
    report = {
        "kind": "jp_ingest_benchmark",
        "scope": "production_candidate",
        "reference_machine": args.reference_machine,
        "corpus_source": manifest["corpus_source"],
        "requested_documents": len(documents),
        "completed_documents": len(unique_completed_document_ids),
        "completed_jobs": len(completed_rows),
        "one_document_per_input": one_document_per_input,
        "distinct_documents_completed": distinct_documents_completed,
        "elapsed_seconds": elapsed,
        "within_30_minutes": (
            all_inputs_completed
            and one_document_per_input
            and distinct_documents_completed
            and elapsed <= 1800
        ),
        "submit_latency_seconds": {
            "p50": _percentile(accepted, 0.50),
            "p95": _percentile(accepted, 0.95),
        },
        "results": results,
    }
    report["gate_pass"] = bool(report["within_30_minutes"])
    return report


def benchmark_search_latency(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _load_json(Path(args.queries).resolve())
    if not isinstance(manifest, dict) or not isinstance(manifest.get("queries"), list):
        raise RuntimeError("Search manifest must contain a queries array.")
    _validate_provenance(manifest, args.reference_machine)
    if int(manifest.get("document_count", 0)) != args.expected_documents:
        raise RuntimeError(
            f"Manifest must attest document_count={args.expected_documents}; "
            "the current API has no corpus-count endpoint."
        )
    base_url, headers = args.base_url.rstrip("/"), _headers(args.bearer_token)
    latencies: list[float] = []
    failures: list[dict[str, Any]] = []
    for iteration in range(args.iterations):
        for query in manifest["queries"]:
            query_text = query.get("query") if isinstance(query, dict) else None
            if not isinstance(query_text, str) or not query_text:
                raise RuntimeError("Every search query must have a non-empty query string.")
            url = f"{base_url}/v1/search?{urllib.parse.urlencode({'q': query_text, 'mode': args.mode, 'limit': args.limit})}"
            started = time.perf_counter()
            status, payload = _request(url, "GET", headers, args.timeout_seconds)
            elapsed = time.perf_counter() - started
            if status == 200:
                response = json.loads(payload.decode("utf-8"))
                if response.get("degraded"):
                    failures.append({"iteration": iteration, "query": query_text, "error": "degraded"})
                else:
                    latencies.append(elapsed)
            else:
                failures.append({"iteration": iteration, "query": query_text, "error": f"http_{status}"})
    p95 = _percentile(latencies, 0.95)
    report = {
        "kind": "jp_search_latency_benchmark",
        "scope": "attested_workload",
        "reference_machine": args.reference_machine,
        "corpus_source": manifest["corpus_source"],
        "attested_document_count": manifest["document_count"],
        "corpus_verification": "attested_only; the public API exposes no corpus-count or full-index coverage endpoint",
        "mode": args.mode,
        "successful_requests": len(latencies),
        "failures": failures,
        "latency_seconds": {
            "p50": _percentile(latencies, 0.50),
            "p95": p95,
            "max": max(latencies) if latencies else None,
            "mean": statistics.fmean(latencies) if latencies else None,
        },
        "meets_500ms_p95": p95 is not None and p95 <= 0.5 and not failures,
    }
    report["gate_pass"] = bool(report["meets_500ms_p95"])
    return report


def benchmark_api_latency(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _load_json(Path(args.requests).resolve())
    if not isinstance(manifest, dict) or not isinstance(manifest.get("requests"), list):
        raise RuntimeError("API manifest must contain a requests array.")
    _validate_provenance(manifest, args.reference_machine)
    base_url, headers = args.base_url.rstrip("/"), _headers(args.bearer_token)
    latencies: list[float] = []
    failures: list[dict[str, Any]] = []
    for iteration in range(args.iterations):
        for item in manifest["requests"]:
            method = str(item.get("method", "GET")).upper()
            path = item.get("path")
            if method != "GET" or not isinstance(path, str) or not path.startswith("/"):
                raise RuntimeError("API latency manifests currently permit only safe GET paths.")
            expected_status = int(item.get("expected_status", 200))
            started = time.perf_counter()
            status, _ = _request(f"{base_url}{path}", method, headers, args.timeout_seconds)
            elapsed = time.perf_counter() - started
            if status == expected_status:
                latencies.append(elapsed)
            else:
                failures.append({"iteration": iteration, "path": path, "error": f"http_{status}"})
    p95 = _percentile(latencies, 0.95)
    baseline_p95: float | None = None
    if args.baseline_report:
        baseline = _load_json(Path(args.baseline_report).resolve())
        candidate = baseline.get("latency_seconds", {}).get("p95") if isinstance(baseline, dict) else None
        if not isinstance(candidate, (int, float)):
            raise RuntimeError("Baseline report must contain latency_seconds.p95.")
        baseline_p95 = float(candidate)
    report = {
        "kind": "jp_api_latency_benchmark",
        "scope": "production_candidate",
        "reference_machine": args.reference_machine,
        "corpus_source": manifest["corpus_source"],
        "successful_requests": len(latencies),
        "failures": failures,
        "latency_seconds": {
            "p50": _percentile(latencies, 0.50),
            "p95": p95,
            "max": max(latencies) if latencies else None,
            "mean": statistics.fmean(latencies) if latencies else None,
        },
        "no_p95_regression": None if baseline_p95 is None or p95 is None else p95 <= baseline_p95,
        "baseline_p95_seconds": baseline_p95,
    }
    report["gate_pass"] = bool(report["no_p95_regression"]) and not failures
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

    ingest = subparsers.add_parser("ingest-1k", help="Submit and wait for an exact 1k-document workload.")
    ingest.add_argument("--manifest", required=True)
    ingest.add_argument("--base-url", required=True)
    ingest.add_argument("--bearer-token")
    ingest.add_argument("--reference-machine", required=True)
    ingest.add_argument("--expected-documents", type=int, default=1000)
    ingest.add_argument("--concurrency", type=int, default=4)
    ingest.add_argument("--request-timeout-seconds", type=float, default=60.0)
    ingest.add_argument("--job-timeout-seconds", type=float, default=1800.0)
    ingest.add_argument("--poll-seconds", type=float, default=1.0)
    ingest.add_argument("--allow-write", action="store_true")
    ingest.add_argument("--output")
    ingest.set_defaults(handler=benchmark_ingest)

    search = subparsers.add_parser("search-10k", help="Measure /v1/search p95 against an attested 10k corpus.")
    search.add_argument("--queries", required=True)
    search.add_argument("--base-url", required=True)
    search.add_argument("--bearer-token")
    search.add_argument("--reference-machine", required=True)
    search.add_argument("--expected-documents", type=int, default=10000)
    search.add_argument("--mode", choices=["keyword", "semantic", "hybrid"], default="hybrid")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--iterations", type=int, default=5)
    search.add_argument("--timeout-seconds", type=float, default=30.0)
    search.add_argument("--output")
    search.set_defaults(handler=benchmark_search_latency)

    api = subparsers.add_parser("api-latency", help="Measure safe API GET p95 for review-console regression.")
    api.add_argument("--requests", required=True)
    api.add_argument("--base-url", required=True)
    api.add_argument("--bearer-token")
    api.add_argument("--reference-machine", required=True)
    api.add_argument("--iterations", type=int, default=10)
    api.add_argument("--timeout-seconds", type=float, default=30.0)
    api.add_argument("--baseline-report", required=True)
    api.add_argument("--output")
    api.set_defaults(handler=benchmark_api_latency)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = args.handler(args)
        _write_report(report, args.output)
        if report.get("gate_pass") is False:
            return 3
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
