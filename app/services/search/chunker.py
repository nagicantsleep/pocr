"""Layout-aware document chunking for search indexing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DocumentChunk:
    """A chunk of text from a document for indexing."""

    chunk_id: str
    document_id: str
    chunk_type: str  # "header", "table", "paragraph", "line_item"
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None


def chunk_document(
    document_id: str,
    extracted_json: dict[str, Any],
    ocr_lines: list[dict[str, Any]] | None = None,
) -> list[DocumentChunk]:
    """Break an extracted document into searchable chunks.

    Strategy:
    - Header fields (issuer_name, registration_number, date) -> one header chunk
    - Each line item -> one chunk
    - Table data -> one chunk per table
    - Full text -> one overview chunk
    """
    chunks: list[DocumentChunk] = []

    # Header chunk from scalar metadata fields
    header_fields = [
        "issuer_name",
        "registration_number",
        "date",
        "invoice_number",
        "total_amount",
        "currency",
        "tax_amount",
        "due_date",
        "vendor_name",
        "recipient_name",
    ]
    header_parts: list[str] = []
    header_meta: dict[str, Any] = {}
    for field_name in header_fields:
        value = extracted_json.get(field_name)
        if value is not None and value != "":
            header_parts.append(f"{field_name}: {value}")
            header_meta[field_name] = value

    page_no = extracted_json.get("page_no")
    if page_no is not None:
        header_meta["page_no"] = page_no

    if header_parts:
        chunks.append(
            DocumentChunk(
                chunk_id=str(uuid.uuid4()),
                document_id=document_id,
                chunk_type="header",
                text="\n".join(header_parts),
                metadata=header_meta,
            )
        )

    # Line items -> individual chunks
    line_items = extracted_json.get("line_items") or extracted_json.get("items") or []
    if isinstance(line_items, list):
        for idx, item in enumerate(line_items):
            if isinstance(item, dict):
                text_parts = [f"{k}: {v}" for k, v in item.items() if v is not None]
                meta: dict[str, Any] = {"item_index": idx}
                if page_no is not None:
                    meta["page_no"] = page_no
                table_id = item.get("table_id")
                if table_id is not None:
                    meta["table_id"] = table_id
                if text_parts:
                    chunks.append(
                        DocumentChunk(
                            chunk_id=str(uuid.uuid4()),
                            document_id=document_id,
                            chunk_type="line_item",
                            text="\n".join(text_parts),
                            metadata=meta,
                        )
                    )

    # Tables (excluding already-captured line items)
    tables = extracted_json.get("tables") or []
    if isinstance(tables, list):
        for tbl_idx, table in enumerate(tables):
            if isinstance(table, dict):
                rows = table.get("rows") or table.get("data") or []
                table_meta: dict[str, Any] = {"table_id": table.get("id", tbl_idx)}
                if page_no is not None:
                    table_meta["page_no"] = page_no
                if isinstance(rows, list) and rows:
                    text_lines: list[str] = []
                    for row in rows:
                        if isinstance(row, list):
                            text_lines.append(" | ".join(str(c) for c in row))
                        elif isinstance(row, dict):
                            text_lines.append(
                                " | ".join(str(v) for v in row.values())
                            )
                        else:
                            text_lines.append(str(row))
                    chunks.append(
                        DocumentChunk(
                            chunk_id=str(uuid.uuid4()),
                            document_id=document_id,
                            chunk_type="table",
                            text="\n".join(text_lines),
                            metadata=table_meta,
                        )
                    )

    # Overview chunk: full text of the extracted data
    overview_text = _flatten_to_text(extracted_json)
    if overview_text:
        overview_meta: dict[str, Any] = {"scope": "overview"}
        if page_no is not None:
            overview_meta["page_no"] = page_no
        chunks.append(
            DocumentChunk(
                chunk_id=str(uuid.uuid4()),
                document_id=document_id,
                chunk_type="paragraph",
                text=overview_text,
                metadata=overview_meta,
            )
        )

    # If nothing was extracted, create a single overview chunk
    if not chunks:
        fallback_text = _flatten_to_text(extracted_json) or "empty document"
        chunks.append(
            DocumentChunk(
                chunk_id=str(uuid.uuid4()),
                document_id=document_id,
                chunk_type="paragraph",
                text=fallback_text,
                metadata={"scope": "overview"},
            )
        )

    return chunks


def _flatten_to_text(data: Any, prefix: str = "") -> str:
    """Recursively flatten a dict/list into readable text."""
    lines: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                nested = _flatten_to_text(value, prefix=f"{prefix}{key}.")
                if nested:
                    lines.append(nested)
            elif value is not None and value != "":
                lines.append(f"{key}: {value}")
    elif isinstance(data, list):
        for item in data:
            nested = _flatten_to_text(item, prefix=prefix)
            if nested:
                lines.append(nested)
    elif data is not None and data != "":
        lines.append(str(data))
    return "\n".join(lines)
