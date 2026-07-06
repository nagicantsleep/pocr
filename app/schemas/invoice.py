"""Pydantic schemas for invoice extraction API."""

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional


class InvoiceLineItem(BaseModel):
    """A single line item on an invoice."""

    line_no: int
    description: Optional[str] = None
    item_code: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[int] = None
    tax_rate: Optional[str] = None  # "8%" | "10%" | "non_taxable" | "exempt" | "unknown"
    tax_amount: Optional[int] = None
    amount_excluding_tax: Optional[int] = None
    amount_including_tax: Optional[int] = None
    discount: Optional[int] = None
    note: Optional[str] = None
    confidence: Optional[float] = None
    needs_review: Optional[bool] = None
    source_cells: Optional[dict] = None


class TaxBreakdown(BaseModel):
    """Tax breakdown by rate."""

    model_config = ConfigDict(populate_by_name=True)

    eight_pct: Optional[int] = Field(None, alias="8%")
    ten_pct: Optional[int] = Field(None, alias="10%")


class FieldEvidence(BaseModel):
    """Evidence for a single extracted field."""

    source_text: Optional[str] = None
    bbox: Optional[dict] = None
    confidence: Optional[float] = None
    candidate_rank: Optional[int] = None


class ValidationIssue(BaseModel):
    """A single validation warning or error."""

    code: str
    severity: str  # "error" | "warning"
    message: str
    field: Optional[str] = None


class InvoiceValidationResult(BaseModel):
    """Result of invoice validation."""

    is_valid: bool
    warnings: list[ValidationIssue] = Field(default_factory=list)
    errors: list[ValidationIssue] = Field(default_factory=list)


class InvoiceData(BaseModel):
    """Extracted invoice fields."""

    issuer_name: Optional[str] = None
    issuer_registration_number: Optional[str] = None
    recipient_name: Optional[str] = None
    invoice_number: Optional[str] = None
    transaction_date: Optional[str] = None
    payment_due_date: Optional[str] = None
    subtotal_by_tax_rate: Optional[dict] = None
    consumption_tax_by_rate: Optional[dict] = None
    total_amount: Optional[int] = None
    line_items: list[InvoiceLineItem] = Field(default_factory=list)
    bank_account: Optional[dict] = None


class InvoiceExtractResponse(BaseModel):
    """Response for invoice extraction."""

    request_id: str
    status: str  # "success" | "error"
    document_type: Optional[str] = None
    invoice: InvoiceData = Field(default_factory=InvoiceData)
    confidence: Optional[dict] = None
    line_items_status: str = "not_extracted"  # "extracted" | "partial" | "not_extracted"
    validation: InvoiceValidationResult = Field(default_factory=lambda: InvoiceValidationResult(is_valid=True))
    needs_review: bool = False
    ocr: Optional[dict] = None


class InvoiceDebugResponse(InvoiceExtractResponse):
    """Debug mode: adds layout, regex candidates, table candidates, validation trace."""

    layout: Optional[dict] = None
    regex_candidates: Optional[dict] = None
    table_candidates: Optional[list] = None
    validation_trace: Optional[list] = None


class InvoiceBatchItem(BaseModel):
    """Single result in a batch invoice extraction."""

    filename: str
    status: str
    invoice: Optional[InvoiceData] = None
    error: Optional[str] = None


class InvoiceBatchResponse(BaseModel):
    """Response for batch invoice extraction."""

    request_id: str
    status: str
    results: list[InvoiceBatchItem] = Field(default_factory=list)
