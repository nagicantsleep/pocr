"""Source registry: maps schema source names to extraction functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.services.invoice_rules import (
    find_dates,
    find_issuer_name,
    find_registration_number,
    find_total_amount,
    find_invoice_number,
)


@dataclass(frozen=True)
class SourceEntry:
    """A registered extraction source."""

    func: Callable | None
    input_type: str  # "plain_text" or "lines"


class SourceRegistry:
    """Maps schema source names to extraction functions."""

    def __init__(self) -> None:
        self._sources: dict[str, SourceEntry] = {}

    def register(
        self,
        name: str,
        func: Callable | None,
        input_type: str = "plain_text",
    ) -> None:
        """Register an extraction function for a source name.

        Args:
            name: Source name matching schema field.sources entries.
            func: Extraction callable, or None for a placeholder.
            input_type: "plain_text" (str) or "lines" (list[dict]).
        """
        self._sources[name] = SourceEntry(func=func, input_type=input_type)

    def get(self, name: str) -> Callable | None:
        """Get extraction function by name. Returns None if unregistered or placeholder."""
        entry = self._sources.get(name)
        return entry.func if entry else None

    def get_input_type(self, name: str) -> str:
        """Get the expected input type for a registered source."""
        entry = self._sources.get(name)
        return entry.input_type if entry else "plain_text"

    def list_sources(self) -> list[str]:
        """List all registered source names."""
        return list(self._sources.keys())


# Default instance with invoice-jp source registrations.
# input_type must match what the underlying function actually accepts.
source_registry = SourceRegistry()
source_registry.register("regex_reg_no", find_registration_number, input_type="plain_text")
source_registry.register("regex_vendor", find_issuer_name, input_type="lines")
source_registry.register("layout_header", find_issuer_name, input_type="lines")
source_registry.register("llm_fallback", None)  # placeholder for Stage 3+
source_registry.register("regex_wareki", find_dates, input_type="lines")
source_registry.register("regex_western", find_dates, input_type="lines")
source_registry.register("layout_label_no", find_invoice_number, input_type="lines")
source_registry.register("regex_invoice_no", find_invoice_number, input_type="lines")
source_registry.register("layout_label_total", find_total_amount, input_type="lines")
source_registry.register("regex_amount_max", find_total_amount, input_type="lines")
