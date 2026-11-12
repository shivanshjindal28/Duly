"""Local ERP adapter: the demo's PO / GR / SES data in SQLite plays the part of SAP."""
from __future__ import annotations

from sqlalchemy import select

from app.core import clock
from app.erp.base import ErpAdapter, ErpPosting, ErpRead
from app.models import GoodsReceipt, Invoice, PurchaseOrder, ServiceEntrySheet
from app.models.base import as_utc

SYSTEM = "Duly local ERP (SQLite)"


class LocalErpAdapter(ErpAdapter):
    name = "local"

    def _po(self, po_number: str) -> PurchaseOrder | None:
        return self.db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == po_number))

    def read_purchase_order(self, po_number: str) -> ErpRead:
        po = self._po(po_number)
        data = None if po is None else {
            "po_number": po.po_number, "status": po.status, "currency": po.currency, "is_service": po.is_service,
            "payment_terms_days": po.payment_terms_days,
            "items": [{"item": pl.line_no, "material": pl.item_code, "description": pl.description, "qty": str(pl.qty),
                       "uom": pl.uom, "net_price": str(pl.unit_price), "gst_rate": str(pl.gst_rate)} for pl in po.lines],
        }
        return ErpRead(SYSTEM, "GET", f"local://purchase_orders/{po_number}", data)

    def read_goods_receipts(self, po_number: str) -> ErpRead:
        po = self._po(po_number)
        if po is None:
            return ErpRead(SYSTEM, "GET", f"local://goods_receipts?po={po_number}", [])
        grs = [{"document": g.gr_number, "movement_type": g.movement_type,
                "posted": as_utc(g.posted_at).astimezone(clock.IST).date().isoformat(),
                "lines": [{"po_line_id": x.po_line_id, "qty": str(x.qty), "uom": x.uom} for x in g.lines]}
               for g in self.db.scalars(select(GoodsReceipt).where(GoodsReceipt.po_id == po.id))]
        ses = [{"document": s.ses_number, "value": str(s.value),
                "posted": as_utc(s.posted_at).astimezone(clock.IST).date().isoformat()}
               for s in self.db.scalars(select(ServiceEntrySheet).where(ServiceEntrySheet.po_id == po.id))]
        return ErpRead(SYSTEM, "GET", f"local://goods_receipts?po={po_number}", grs + ses)

    def post_supplier_invoice(self, inv: Invoice, dry_run: bool = True) -> ErpPosting:
        """In the demo Duly itself is the book of record: the S/4HANA payload is built for display only."""
        from app.erp.s4hana import S4HanaAdapterStub

        p = S4HanaAdapterStub(self.db).post_supplier_invoice(inv, dry_run=True)
        p.system = SYSTEM
        p.url = "local://supplier_invoices"
        return p
