"""Extraction output schema shared by every extractor (offline parser now, Claude in Phase 2).

Each field carries its value as a normalised string, a confidence 0..1, and where on the
document it was read (page + bbox in page fractions), so the UI can highlight it.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

HEADER_FIELDS = (
    "supplier_name", "supplier_gstin", "buyer_gstin", "invoice_number", "invoice_date",
    "po_number", "place_of_supply", "currency", "taxable_total", "cgst", "sgst", "igst",
    "total", "bank_account", "bank_ifsc", "irn",
)
LINE_FIELDS = (
    "item_code", "description", "hsn_sac", "qty", "uom", "unit_price", "taxable_value",
    "gst_rate", "cgst", "sgst", "igst",
)


class ExtractedField(BaseModel):
    value: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    source: str = "none"  # text | ocr | ai | qr | rule | manual | none


class ExtractedInvoice(BaseModel):
    header: dict[str, ExtractedField]
    lines: list[dict[str, ExtractedField]]
    method: str  # "text" or "ocr"
    extractor: str  # e.g. "offline-regex"
    extractor_version: str

    def get(self, name: str) -> str | None:
        f = self.header.get(name)
        return f.value if f else None

    def all_fields(self) -> list[tuple[str, ExtractedField]]:
        """Flatten to (field_path, field) pairs, e.g. ("lines[0].qty", ...)."""
        out = [(k, v) for k, v in self.header.items()]
        for i, line in enumerate(self.lines):
            out += [(f"lines[{i}].{k}", v) for k, v in line.items()]
        return out
