"""ERP adapter interface and the SAP-side configuration Duly assumes for Plant X.

Every value below is customer configuration in a real SAP system (company code, plant, tax codes,
withholding tax types, payment terms keys). They are fictional assumptions for the demo.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models import Invoice

COMPANY_CODE = "PX01"  # fictional company code for Plant X Polymers
PLANT = "PX10"  # fictional plant code (Dahej)
BUSINESS_PLACE = "PX24"  # GST business place (Gujarat)

# GST tax codes: (intra/inter-state, rate) -> tax code. ASSUMPTION: company-specific config.
TAX_CODES = {("intra", 5): "G1", ("intra", 12): "G2", ("intra", 18): "G3", ("intra", 28): "G4", ("intra", 0): "G0",
             ("inter", 5): "I1", ("inter", 12): "I2", ("inter", 18): "I3", ("inter", 28): "I4", ("inter", 0): "I0"}
# TDS section -> extended withholding tax type / code. ASSUMPTION: company-specific config.
WHT_TYPES = {"contractor": ("TC", "C2"), "technical": ("TJ", "J2"), "professional": ("TJ", "J1"), "goods": ("TQ", "Q1")}


def sap_fiscal_year(d: date) -> str:
    """Indian companies typically use fiscal year variant V3 (April-March), named by the start year."""
    return str(d.year if d.month >= 4 else d.year - 1)


def tax_code(rate: float, inter_state: bool) -> str:
    return TAX_CODES.get(("inter" if inter_state else "intra", int(round(rate))), "G?")


def payment_terms_key(days: int) -> str:
    return f"Z{days:03d}"  # e.g. Z045: net 45 days (fictional key naming)


@dataclass
class ErpRead:
    """A read from the ERP: the request it takes and (for the local adapter) the data."""
    system: str
    method: str
    url: str
    data: dict | list | None = None
    note: str = ""


@dataclass
class ErpPosting:
    """A supplier-invoice post (MIRO equivalent)."""
    system: str
    dry_run: bool
    method: str
    url: str
    headers: dict
    payload: dict
    document_number: str | None
    fiscal_year: str
    payment_block: str | None  # "R" = blocked for invoice verification
    warnings: list[str] = field(default_factory=list)


class ErpAdapter(ABC):
    name: str

    def __init__(self, db: Session):
        self.db = db

    @abstractmethod
    def read_purchase_order(self, po_number: str) -> ErpRead: ...

    @abstractmethod
    def read_goods_receipts(self, po_number: str) -> ErpRead: ...

    @abstractmethod
    def post_supplier_invoice(self, inv: Invoice, dry_run: bool = True) -> ErpPosting: ...
