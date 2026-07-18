#!/usr/bin/env python3
"""Download a pinned, labeled real-JP receipt corpus for live evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DATASET_ID = "llm-jp/jawildtext"
CONFIG = "receipt_kie"
SPLIT = "train"
ROWS_PAGE_SIZE = 100
GATE_BLOCKER = "store_name is not adjudicated as the product legal issuer field"


def _request_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "pocr-evaluation-preparer/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, destination: Path) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "pocr-evaluation-preparer/1.0"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            handle.write(chunk)
    return digest.hexdigest()


def _field_value(fields: dict[str, Any], name: str) -> str | None:
    value = fields.get(name)
    if not isinstance(value, dict):
        return None
    result = value.get("value")
    return result.strip() if isinstance(result, str) and result.strip() else None


def expected_fields(row: dict[str, Any]) -> dict[str, str]:
    """Map only semantically equivalent public labels to product fields."""
    fields = row.get("fields")
    if not isinstance(fields, dict):
        raise ValueError("row.fields must be an object")
    mapped = {
        "transaction_date": _field_value(fields, "date"),
        "total_amount": _field_value(fields, "total_amount"),
    }
    return {name: value for name, value in mapped.items() if value is not None}


def _rows(offset: int, length: int, revision: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "dataset": DATASET_ID,
            "config": CONFIG,
            "split": SPLIT,
            "offset": offset,
            "length": length,
            "revision": revision,
        }
    )
    payload = _request_json(f"https://datasets-server.huggingface.co/rows?{query}")
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("Hugging Face rows response omitted rows")
    return [item["row"] for item in rows if isinstance(item, dict) and isinstance(item.get("row"), dict)]


def prepare(output: Path, count: int, revision: str | None = None) -> dict[str, Any]:
    if output.exists():
        if any(output.iterdir()):
            raise RuntimeError(f"{output} already exists and is not empty")
    else:
        output.mkdir(parents=True)
    requested_revision = revision
    metadata_path = (
        f"/revision/{urllib.parse.quote(requested_revision, safe='')}"
        if requested_revision
        else ""
    )
    metadata = _request_json(f"https://huggingface.co/api/datasets/{DATASET_ID}{metadata_path}")
    revision = metadata.get("sha") if isinstance(metadata, dict) else None
    card_data = metadata.get("cardData") if isinstance(metadata, dict) else None
    license_name = card_data.get("license") if isinstance(card_data, dict) else None
    if not isinstance(revision, str) or not revision:
        raise RuntimeError("Dataset metadata omitted immutable revision sha")
    if requested_revision and revision != requested_revision:
        raise RuntimeError(
            f"Requested revision {requested_revision!r} did not resolve to the same immutable revision"
        )
    if license_name != "apache-2.0":
        raise RuntimeError(f"Expected Apache-2.0 corpus, found {license_name!r}")

    documents: list[dict[str, str]] = []
    written = 0
    try:
        for offset in range(0, count, ROWS_PAGE_SIZE):
            for row in _rows(offset, min(ROWS_PAGE_SIZE, count - offset), revision):
                if row.get("subset") != CONFIG:
                    raise RuntimeError(f"Expected {CONFIG!r} row, found {row.get('subset')!r}")
                image = row.get("image")
                image_url = image.get("src") if isinstance(image, dict) else None
                if not isinstance(image_url, str) or not image_url:
                    raise RuntimeError(f"Receipt row {written} omitted an image URL")
                if f"/{revision}/" not in urllib.parse.urlparse(image_url).path:
                    raise RuntimeError(
                        f"Receipt row {written} image URL is not pinned to revision {revision}"
                    )
                filename = str(row.get("filename") or f"receipt-{written:04}.jpg")
                suffix = Path(filename).suffix.casefold() or ".jpg"
                image_path = output / f"receipt-{written:04}{suffix}"
                image_sha256 = _download(image_url, image_path)
                stem = output / f"receipt-{written:04}"
                ground_truth = {"fields": expected_fields(row)}
                metadata_path = stem.with_suffix(".meta.json")
                expected_path = stem.with_suffix(".json")
                expected_path.write_text(
                    json.dumps(ground_truth, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                metadata_path.write_text(
                    json.dumps(
                        {
                            "source": "public_real",
                            "dataset": DATASET_ID,
                            "revision": revision,
                            "config": CONFIG,
                            "split": SPLIT,
                            "image_id": row.get("image_id"),
                            "filename": filename,
                            "license": license_name,
                            "image_sha256": image_sha256,
                            "production_gate_eligible": False,
                            "production_gate_blocker": GATE_BLOCKER,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                documents.append(
                    {
                        "source_id": str(row.get("image_id") or written),
                        "path": str(image_path.relative_to(output)).replace("\\", "/"),
                    }
                )
                written += 1
                if written == count:
                    break
            if written == count:
                break
        if written != count:
            raise RuntimeError(f"Dataset supplied {written} receipt rows, expected {count}")
        manifest = {
            "corpus_source": "public_real",
            "dataset": DATASET_ID,
            "revision": revision,
            "config": CONFIG,
            "split": SPLIT,
            "license": license_name,
            "production_gate_eligible": False,
            "production_gate_blocker": GATE_BLOCKER,
            "document_count": written,
            "documents": documents,
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest
    except Exception:
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--revision", help="Immutable Hugging Face revision SHA to download.")
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 1151:
        parser.error("--count must be between 1 and 1151 for receipt_kie")
    try:
        manifest = prepare(args.output.resolve(), args.count, args.revision)
    except (OSError, RuntimeError, ValueError, urllib.error.URLError) as exc:
        print(f"corpus preparation failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"prepared {manifest['document_count']} {manifest['corpus_source']} receipts "
        f"at {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
