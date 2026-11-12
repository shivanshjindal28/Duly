"""SAP-ready by design (D6): ERP adapters and the S/4HANA posting preview."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import delete, select

from app.core.enums import InvoiceStatus
from app.core.ratelimit import limiter
from app.erp import LocalErpAdapter, S4HanaAdapterStub, get_adapter
from app.erp.base import sap_fiscal_year, tax_code
from app.erp.s4hana import odata_date
from app.models import Invoice, InvoiceLine, PurchaseOrder, Supplier

CLERK = "asha.kulkarni@plantx.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


@pytest.fixture(autouse=True)
def _cleanup(db):
    """These invoices bypass the workflow: remove them so they do not consume PO quantities in later tests."""
    yield
    db.rollback()
    ids = list(db.scalars(select(Invoice.id).where(Invoice.invoice_number.like("%/ERP/%"))))
    if ids:
        db.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id.in_(ids)))
        db.execute(delete(Invoice).where(Invoice.id.in_(ids)))
        db.commit()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200


def _invoice(db, po_number: str, number: str, status=InvoiceStatus.APPROVED) -> Invoice:
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == po_number))
    s = db.get(Supplier, po.supplier_id)
    inv = Invoice(supplier_id=s.id, po_id=po.id, invoice_number=number, invoice_number_norm=number.replace("/", ""),
                  invoice_date=date(2026, 11, 9), supplier_gstin=s.gstin, status=status, current_owner="x")
    db.add(inv)
    db.flush()
    taxable = D(0)
    for n, pl in enumerate(po.lines, start=1):
        value = (pl.qty * pl.unit_price).quantize(D("0.01"))
        half = (value * pl.gst_rate / 200).quantize(D("0.01"))
        db.add(InvoiceLine(invoice_id=inv.id, line_no=n, item_code=pl.item_code, description=pl.description,
                           hsn_sac=pl.hsn_sac, qty=pl.qty, uom=pl.uom, unit_price=pl.unit_price, taxable_value=value,
                           gst_rate=pl.gst_rate, cgst=half, sgst=half, po_line_id=pl.id))
        taxable += value
    inv.taxable_total = taxable
    inv.cgst = inv.sgst = (taxable * D("0.09")).quantize(D("0.01"))
    inv.total = taxable + inv.cgst + inv.sgst
    db.commit()
    db.refresh(inv)
    return inv


def test_helpers():
    assert odata_date(date(1970, 1, 2)) == "/Date(86400000)/"
    assert sap_fiscal_year(date(2026, 11, 12)) == "2026" and sap_fiscal_year(date(2027, 2, 1)) == "2026"
    assert tax_code(18, inter_state=False) == "G3" and tax_code(18, inter_state=True) == "I3"


def test_s4_payload_for_goods_invoice_references_po_and_gr(db):
    inv = _invoice(db, "4500001003", "KES/ERP/0001")  # bearings + seals, GR posted
    p = S4HanaAdapterStub(db).post_supplier_invoice(inv)
    assert p.dry_run and p.method == "POST" and p.url.endswith("API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice")
    body = p.payload
    assert body["CompanyCode"] == "PX01" and body["InvoicingParty"] == "V100103"
    assert body["SupplierInvoiceIDByInvcgParty"] == "KES/ERP/0001" and body["PaymentBlockingReason"] == ""
    assert body["InvoiceGrossAmount"] == f"{inv.total:.2f}" and body["DocumentDate"].startswith("/Date(")
    items = body["to_SuplrInvcItemPurOrdRef"]["results"]
    assert [i["PurchaseOrderItem"] for i in items] == ["00010", "00020"]
    assert all(i["PurchaseOrder"] == "4500001003" and i["ReferenceDocument"] and i["TaxCode"] == "G3" for i in items)
    tax = body["to_SupplierInvoiceTax"]["results"]
    assert len(tax) == 1 and D(tax[0]["TaxAmount"]) == sum(l.cgst + l.sgst for l in inv.lines)
    assert body["to_SupplierInvoiceWhldgTax"]["results"][0]["WithholdingTaxType"] == "TQ"  # Kesar: goods
    assert p.payment_block is None and not [w for w in p.warnings if "block" in w]


def test_s4_payload_for_services_uses_ses_and_blocked_invoice_gets_block_r(db):
    inv = _invoice(db, "4500001006", "TTS/ERP/0001", status=InvoiceStatus.BLOCKED)
    p = S4HanaAdapterStub(db).post_supplier_invoice(inv)
    item = p.payload["to_SuplrInvcItemPurOrdRef"]["results"][0]
    assert item["ServiceEntrySheet"] and "ReferenceDocument" not in item
    assert p.payload["PaymentBlockingReason"] == "R" and p.payment_block == "R"
    assert p.payload["to_SupplierInvoiceWhldgTax"]["results"][0]["WithholdingTaxType"] == "TC"  # contractor


def test_local_adapter_reads_and_factory(db):
    local = get_adapter(db)
    assert isinstance(local, LocalErpAdapter) and isinstance(get_adapter(db, "s4hana_stub"), S4HanaAdapterStub)
    po = local.read_purchase_order("4500001003")
    assert po.data["items"][0]["material"] == "BRG-6205"
    grs = local.read_goods_receipts("4500001003")
    assert grs.data and grs.data[0]["movement_type"] == "101"
    stub_read = S4HanaAdapterStub(db).read_goods_receipts("4500001003")
    assert "GoodsMovementType eq '101'" in stub_read.url and stub_read.data is None


def test_sap_preview_endpoint_and_access(client, db):
    inv = _invoice(db, "4500001012", "KES/ERP/0002")
    login(client, CLERK)
    r = client.get(f"/api/invoices/{inv.id}/sap-preview")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ready"] and j["posting"]["payload"]["CompanyCode"] == "PX01" and len(j["reads"]) == 2
    assert "MIRO" in j["transaction"]
    login(client, "invoices@kesar-spares.example")
    assert client.get(f"/api/invoices/{inv.id}/sap-preview").status_code == 403
