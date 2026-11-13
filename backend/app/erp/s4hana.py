"""S/4HANA adapter stub: builds the requests Duly would send, never calls a real system.

Modelled on the SAP S/4HANA Cloud OData V2 APIs:
  API_SUPPLIERINVOICE_PROCESS_SRV  A_SupplierInvoice (deep insert with PO-reference items, tax, withholding tax)
  API_PURCHASEORDER_PROCESS_SRV    A_PurchaseOrder + to_PurchaseOrderItem
  API_MATERIAL_DOCUMENT_SRV        A_MaterialDocumentItem (goods movement type 101 = GR for PO)
Field names follow those entity types; values and keys (company code, tax codes, WHT types) are
fictional customer configuration from `erp/base.py`. Verify against the target system's metadata.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.core import clock
from app.core.crypto import decrypt_str
from app.core.enums import InvoiceStatus
from app.erp.base import (BUSINESS_PLACE, COMPANY_CODE, PLANT, WHT_TYPES, ErpAdapter, ErpPosting, ErpRead,
                          payment_terms_key, sap_fiscal_year, tax_code)
from app.models import GoodsReceipt, GRLine, Invoice, Organisation, POLine, PurchaseOrder, ServiceEntrySheet, Supplier
from app.models.base import as_utc
from app.payments import tds as tds_mod

SYSTEM = "S/4HANA (stub: not called)"
BASE = "/sap/opu/odata/sap"
SI_URL = f"{BASE}/API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice"


def odata_date(d: date | datetime | None) -> str | None:
    """OData V2 Edm.DateTime literal: /Date(<ms since epoch, UTC midnight>)/."""
    if d is None:
        return None
    if isinstance(d, datetime):
        d = as_utc(d).astimezone(clock.IST).date()
    return f"/Date({(d - date(1970, 1, 1)).days * 86_400_000})/"


def amt(v: Decimal | int | float) -> str:
    return f"{Decimal(str(v)):.2f}"


class S4HanaAdapterStub(ErpAdapter):
    name = "s4hana_stub"

    def read_purchase_order(self, po_number: str) -> ErpRead:
        return ErpRead(SYSTEM, "GET", f"{BASE}/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder('{po_number}')"
                       "?$expand=to_PurchaseOrderItem&$format=json",
                       note="ME23N in the SAP GUI. Not called: the demo reads the local copy.")

    def read_goods_receipts(self, po_number: str) -> ErpRead:
        return ErpRead(SYSTEM, "GET", f"{BASE}/API_MATERIAL_DOCUMENT_SRV/A_MaterialDocumentItem"
                       f"?$filter=PurchaseOrder eq '{po_number}' and GoodsMovementType eq '101'&$format=json",
                       note="MIGO movement type 101 in the SAP GUI. Not called: the demo reads the local copy.")

    def _item_refs(self, inv: Invoice, po: PurchaseOrder | None, inter_state: bool,
                   imported: bool = False) -> tuple[list[dict], list[str]]:
        from app.engine import units
        from app.workflow.matching import item_packs

        items, warnings = [], []
        for n, line in enumerate(inv.lines, start=1):
            pl = self.db.get(POLine, line.po_line_id) if line.po_line_id else None
            if pl is None:
                warnings.append(f"Invoice line {line.line_no} is not mapped to a PO line; SAP would reject this item.")
            po_qty = line.qty
            if pl is not None and units.norm(line.uom) != units.norm(pl.uom):
                f = units.factor(line.uom, pl.uom, item_packs(self.db, pl.item_code))
                if f is None:
                    warnings.append(f"Invoice line {line.line_no}: {line.uom} cannot be converted to the order unit {pl.uom}.")
                else:
                    po_qty = line.qty * f
            ref: dict = {
                "SupplierInvoice": "", "FiscalYear": "",  # assigned by SAP on post
                "SupplierInvoiceItem": f"{n:06d}",
                "PurchaseOrder": po.po_number if po else (inv.po_number_text or ""),
                "PurchaseOrderItem": f"{pl.line_no:05d}" if pl else "",
                "Plant": PLANT,
                "TaxCode": tax_code(float(line.gst_rate), inter_state, imported),
                "DocumentCurrency": inv.currency,
                "SupplierInvoiceItemAmount": amt(line.taxable_value),
                "PurchaseOrderQuantityUnit": pl.uom if pl else line.uom,
                # MIRO posts the quantity in the order unit: convert what was billed (e.g. 12 BOX -> 120 NOS).
                "QuantityInPurchaseOrderUnit": f"{po_qty:.3f}",
                "SupplierInvoiceItemText": line.description[:50],
            }
            if pl is not None and po is not None and po.is_service:
                q = select(ServiceEntrySheet).where(ServiceEntrySheet.po_line_id == pl.id)
                if inv.origin == "ers":  # an ERS settlement belongs to exactly one service entry
                    q = q.where(ServiceEntrySheet.ses_number == inv.invoice_number.removeprefix("ERS-"))
                ses = self.db.scalar(q.order_by(ServiceEntrySheet.id.desc()))
                if ses:
                    ref |= {"ServiceEntrySheet": ses.ses_number, "ServiceEntrySheetItem": "1"}
                else:
                    warnings.append(f"No service entry sheet for PO item {pl.line_no}.")
            elif pl is not None:
                gr = self.db.execute(select(GoodsReceipt, GRLine).join(GRLine, GRLine.gr_id == GoodsReceipt.id)
                                     .where(GRLine.po_line_id == pl.id).order_by(GoodsReceipt.id.desc())).first()
                if gr:
                    g, gl = gr
                    gr_items = [x.id for x in sorted(g.lines, key=lambda x: x.id)]
                    ref |= {"ReferenceDocument": g.gr_number,
                            "ReferenceDocumentFiscalYear": sap_fiscal_year(as_utc(g.posted_at).astimezone(clock.IST).date()),
                            "ReferenceDocumentItem": f"{gr_items.index(gl.id) + 1:04d}"}
                else:
                    warnings.append(f"No goods receipt (MIGO 101) for PO item {pl.line_no}.")
            items.append(ref)
        return items, warnings

    def post_supplier_invoice(self, inv: Invoice, dry_run: bool = True) -> ErpPosting:
        s = self.db.get(Supplier, inv.supplier_id) if inv.supplier_id else None
        po = self.db.get(PurchaseOrder, inv.po_id) if inv.po_id else None
        org = self.db.scalar(select(Organisation))
        inter_state = bool(inv.igst and inv.igst > 0)
        imported = bool(s and (s.country or "IN") != "IN")
        items, warnings = self._item_refs(inv, po, inter_state, imported)
        if inv.currency != "INR":
            warnings.append(f"Posted in {inv.currency}; SAP translates it to INR with its own exchange-rate table (OB08). "
                            f"Duly's INR figure (rate {inv.fx_rate:.4f}) is indicative.")
        doc_date = inv.invoice_date or clock.today()
        post_date = clock.today()
        approved = inv.status in (InvoiceStatus.APPROVED, InvoiceStatus.PAID)
        block = None if approved else "R"
        if block:
            warnings.append(f"Invoice is {inv.status}: it would be posted with payment block R (invoice verification).")

        # GST per tax code (header tax lines).
        tax: dict[str, dict] = {}
        for line in inv.lines:
            code = tax_code(float(line.gst_rate), inter_state, imported)
            t = tax.setdefault(code, {"TaxCode": code, "DocumentCurrency": inv.currency,
                                      "TaxAmount": Decimal(0), "TaxBaseAmountInTransCrcy": Decimal(0)})
            t["TaxAmount"] += line.cgst + line.sgst + line.igst
            t["TaxBaseAmountInTransCrcy"] += line.taxable_value
        tax_rows = [{**t, "TaxAmount": amt(t["TaxAmount"]), "TaxBaseAmountInTransCrcy": amt(t["TaxBaseAmountInTransCrcy"])}
                    for t in tax.values()]

        wht = []
        if s and s.tds_section in WHT_TYPES:
            wtype, wcode = WHT_TYPES[s.tds_section]
            label = tds_mod.DEFAULT_TDS[s.tds_section]["label"]
            wht.append({"WithholdingTaxType": wtype, "WithholdingTaxCode": wcode, "DocumentCurrency": inv.currency,
                        "WithholdingTaxBaseAmount": amt(inv.taxable_total), "_comment": f"{label}; computed at payment"})

        payload = {
            "CompanyCode": COMPANY_CODE,
            "DocumentDate": odata_date(doc_date),
            "PostingDate": odata_date(post_date),
            "SupplierInvoiceIDByInvcgParty": inv.invoice_number,
            "InvoicingParty": s.code if s else "",
            "DocumentCurrency": inv.currency,
            "InvoiceGrossAmount": amt(inv.total),
            "TaxIsCalculatedAutomatically": False,
            "DueCalculationBaseDate": odata_date(inv.accepted_at or doc_date),
            "PaymentTerms": payment_terms_key(s.payment_terms_days) if s else "",
            "PaymentBlockingReason": block or "",
            "AccountingDocumentType": "RE",
            "BusinessPlace": BUSINESS_PLACE,
            "TaxDeterminationDate": odata_date(doc_date),
            "DocumentHeaderText": f"Duly #{inv.id} {inv.irn[:20] if inv.irn else ''}".strip()[:25],
            "SupplierPostingLineItemText": (f"GSTIN {inv.supplier_gstin}" if inv.supplier_gstin else "")[:50],
            "to_SuplrInvcItemPurOrdRef": {"results": items},
            "to_SupplierInvoiceTax": {"results": tax_rows},
            "to_SupplierInvoiceWhldgTax": {"results": wht},
        }
        if inv.bank_account_enc and s:
            if decrypt_str(inv.bank_account_enc) != decrypt_str(s.bank_account_enc):
                warnings.append("Bank account on the invoice differs from the vendor master; SAP pays the master account only.")
        if inv.origin == "ers":
            warnings.append("Evaluated receipt settlement: in SAP this document is created by MRRL from the receipt "
                            "(ERS indicator on the vendor and PO item); the payload shows the equivalent supplier invoice.")
        if org and inv.buyer_gstin and inv.buyer_gstin != org.gstin:
            warnings.append("Buyer GSTIN on the invoice is not Plant X's GSTIN.")
        return ErpPosting(
            system=SYSTEM, dry_run=True, method="POST", url=SI_URL,
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "x-csrf-token": "<fetched with a GET + 'x-csrf-token: Fetch' first>",
                     "Authorization": "<OAuth 2.0 or basic auth from the communication arrangement>"},
            payload=payload, document_number=None, fiscal_year=sap_fiscal_year(post_date),
            payment_block=block, warnings=warnings)
