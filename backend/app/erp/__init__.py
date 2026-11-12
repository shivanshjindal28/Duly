"""ERP adapters (D6): Duly is a side-car in front of SAP S/4HANA; SAP stays the system of record.

  ErpAdapter         the interface the rest of Duly talks to (PO / GR reads, supplier-invoice post)
  LocalErpAdapter    our SQLite PO / GR / SES data (used in the demo)
  S4HanaAdapterStub  builds the exact OData requests and payloads for S/4HANA without calling it
"""
from __future__ import annotations

from app.erp.base import ErpAdapter, ErpPosting, ErpRead
from app.erp.local import LocalErpAdapter
from app.erp.s4hana import S4HanaAdapterStub

__all__ = ["ErpAdapter", "ErpPosting", "ErpRead", "LocalErpAdapter", "S4HanaAdapterStub", "get_adapter"]


def get_adapter(db, name: str = "local") -> ErpAdapter:
    return S4HanaAdapterStub(db) if name == "s4hana_stub" else LocalErpAdapter(db)
