"""Tests for layout-aware document chunking."""

from __future__ import annotations

from app.services.search.chunker import DocumentChunk, chunk_document


def test_header_fields_create_header_chunk():
    extracted = {
        "issuer_name": "Acme Corp",
        "registration_number": "REG-123",
        "date": "2024-01-15",
        "total_amount": 1500.00,
    }
    chunks = chunk_document("doc-1", extracted)

    header_chunks = [c for c in chunks if c.chunk_type == "header"]
    assert len(header_chunks) == 1
    hc = header_chunks[0]
    assert "Acme Corp" in hc.text
    assert "REG-123" in hc.text
    assert "2024-01-15" in hc.text
    assert hc.metadata["issuer_name"] == "Acme Corp"
    assert hc.document_id == "doc-1"


def test_line_items_create_individual_chunks():
    extracted = {
        "issuer_name": "Test Vendor",
        "line_items": [
            {"description": "Widget A", "quantity": 2, "price": 10.00},
            {"description": "Widget B", "quantity": 1, "price": 25.00},
        ],
    }
    chunks = chunk_document("doc-2", extracted)

    item_chunks = [c for c in chunks if c.chunk_type == "line_item"]
    assert len(item_chunks) == 2
    assert "Widget A" in item_chunks[0].text
    assert "Widget B" in item_chunks[1].text
    assert item_chunks[0].metadata["item_index"] == 0
    assert item_chunks[1].metadata["item_index"] == 1


def test_table_data_creates_table_chunk():
    extracted = {
        "tables": [
            {
                "id": "tbl-1",
                "rows": [
                    ["Item", "Qty", "Price"],
                    ["Apple", "3", "1.50"],
                    ["Banana", "5", "0.80"],
                ],
            }
        ],
    }
    chunks = chunk_document("doc-3", extracted)

    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert len(table_chunks) == 1
    tc = table_chunks[0]
    assert "Item" in tc.text
    assert "Apple" in tc.text
    assert tc.metadata["table_id"] == "tbl-1"


def test_metadata_preserves_field_names_and_page_numbers():
    extracted = {
        "issuer_name": "Acme",
        "page_no": 3,
        "line_items": [{"description": "Widget"}],
    }
    chunks = chunk_document("doc-4", extracted)

    header = next(c for c in chunks if c.chunk_type == "header")
    assert header.metadata["page_no"] == 3
    assert "issuer_name" in header.metadata

    item = next(c for c in chunks if c.chunk_type == "line_item")
    assert item.metadata["page_no"] == 3


def test_empty_extracted_json_creates_overview_chunk():
    chunks = chunk_document("doc-5", {})

    assert len(chunks) >= 1
    overview = chunks[-1]
    assert overview.chunk_type == "paragraph"
    assert overview.document_id == "doc-5"
