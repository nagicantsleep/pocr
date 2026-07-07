"""Register receipt-jp specific source functions with the source registry."""

from __future__ import annotations

from app.services.extraction_kernel import SourceRegistry
from app.services.extraction_kernel.receipt_sources import (
    find_change_amount,
    find_payment_method,
    find_store_address,
    find_store_phone,
    find_subtotal,
    find_tax_amount,
)


def register_receipt_sources(source_registry: SourceRegistry) -> None:
    """Register additional source functions for receipt-jp processing."""
    source_registry.register("regex_phone", find_store_phone)
    source_registry.register("regex_payment_method", find_payment_method)
    source_registry.register("regex_change", find_change_amount)
    source_registry.register("regex_tax", find_tax_amount)
    source_registry.register("regex_subtotal", find_subtotal)
    source_registry.register("layout_label_address", find_store_address)
