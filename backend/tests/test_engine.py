"""Decision engine unit tests: one block per demo scenario and per reason code (pure, no DB)."""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.core.enums import Decision
from app.core.policy_defaults import DEFAULT_POLICY
from app.engine.decide import PoLineView, PoView, SupplierView, decide
from app.engine.policy import Tolerances
from app.engine.types import DocLine, InvoiceDoc
from tests.fixtures.invoices import KESAR_GSTIN, PLANT_X_GSTIN, SAHYADRI_GSTIN

TODAY = date(2026, 11, 12)
TOL = Tolerances.from_policy(DEFAULT_POLICY)
ACCT, IFSC = "50120034417921", "SHYG0123456"
SUPPLIER_KESAR = SupplierView(KESAR_GSTIN, 45, ACCT, IFSC)
SUPPLIER_SAHYADRI = SupplierView(SAHYADRI_GSTIN, 60, ACCT, IFSC)


def line(no, code, qty, uom, price, rate=18, intra=True, desc="item", hsn=None) -> DocLine:
    qty, price = D(str(qty)), D(str(price))
    value = (qty * price).quantize(D("0.01"))
    tax = (value * D(rate) / 100).quantize(D("0.01"))
    half = (tax / 2).quantize(D("0.01"))
    return DocLine(no, code, desc, hsn, qty, uom, price, value, D(rate),
                   half if intra else D(0), (tax - half) if intra else D(0), D(0) if intra else tax)


def invoice(lines, supplier_gstin=KESAR_GSTIN, po="4500001003", pos="24", **kw) -> InvoiceDoc:
    taxable = sum((ln.taxable_value for ln in lines), D(0))
    cgst = sum((ln.cgst for ln in lines), D(0))
    sgst = sum((ln.sgst for ln in lines), D(0))
    igst = sum((ln.igst for ln in lines), D(0))
    base = InvoiceDoc("INV-0042", date(2026, 11, 5), supplier_gstin, PLANT_X_GSTIN, pos, po, "INR",
                      taxable, cgst, sgst, igst, taxable + cgst + sgst + igst, tuple(lines), ACCT, IFSC)
    return replace(base, **kw)


def po_line(id_, code, qty, uom, price, rate=18, received=0, invoiced=0, accepted=0, desc=None) -> PoLineView:
    return PoLineView(id_, id_ * 10, code, desc or code, D(str(qty)), uom, D(str(price)), D(rate),
                      received_qty=D(str(received)), invoiced_qty=D(str(invoiced)), accepted_value=D(str(accepted)))


def po(lines, gstin=KESAR_GSTIN, number="4500001003", service=False, status="open", terms=45) -> PoView:
    return PoView(number, gstin, status, "INR", terms, service, tuple(lines))


def run(doc, po_view, supplier=SUPPLIER_KESAR):
    out = decide(doc, po_view, supplier, TOL, PLANT_X_GSTIN, TODAY)
    return out, {(r.code, r.severity.value) for r in out.reasons}


# --- Scenario 1: clean catalyst invoice (inter-state IGST), with and without UoM conversion
def test_s1_clean_catalyst_approves():
    p = po([po_line(1, "CAT-ZN-01", "1.5", "MT", "850000.00", received="1.5")], SAHYADRI_GSTIN, terms=60)
    doc = invoice([line(1, "CAT-ZN-01", "1.5", "MT", "850000.00", intra=False)], SAHYADRI_GSTIN, pos="24")
    out, codes = run(doc, p, SUPPLIER_SAHYADRI)
    assert out.decision == Decision.APPROVE and codes == set()
    assert doc.total == D("1504500.00")
    assert out.line_map == {1: 1}


def test_s1_invoice_in_kg_against_po_in_mt_is_converted():
    p = po([po_line(1, "CAT-ZN-01", "1.5", "MT", "850000.00", received="1.5")], SAHYADRI_GSTIN, terms=60)
    doc = invoice([line(1, "CAT-ZN-01", "1500", "KG", "850.00", intra=False)], SAHYADRI_GSTIN)
    out, codes = run(doc, p, SUPPLIER_SAHYADRI)
    assert out.decision == Decision.APPROVE and codes == {("UOM_CONVERTED", "info")}
    assert out.matrix[0].invoice_qty == D("1.5") and out.matrix[0].uom == "MT"


# --- Scenario 2: price 3.2% above PO -> FLAG with exact rupee difference
def test_s2_price_variance_flags_with_exact_amount():
    p = po([po_line(1, "ADD-AO-1010", 2000, "KG", "620.00", received=2000)])
    out, codes = run(invoice([line(1, "ADD-AO-1010", 2000, "KG", "639.84")]), p)
    assert out.decision == Decision.FLAG and codes == {("PRICE_VARIANCE", "flag")}
    r = out.reasons[0]
    assert r.evidence["variance_amount"] == "39680.00" and r.evidence["variance_pct"] == "3.20"
    assert "₹39,680.00" in r.message


@pytest.mark.parametrize(("price", "expected"), [
    ("620.50", ("PRICE_VARIANCE", "info")),       # 0.08% and ₹200 on 400 kg: within PP tolerance
    ("620.004", ("SMALL_DIFFERENCE", "info")),     # ₹8 on 2000 kg: BD auto-accept
    ("660.00", ("PRICE_VARIANCE", "block")),       # 6.45% > 5% hard limit
    ("600.00", ("PRICE_VARIANCE", "info")),        # billed below PO: no action
])
def test_price_tolerance_bands(price, expected):
    qty = 2000 if price != "620.50" else 400  # 400 x ₹0.50 = ₹200: within both 1% and ₹500
    p = po([po_line(1, "ADD-AO-1010", 2000, "KG", "620.00", received=2000)])
    out, codes = run(invoice([line(1, "ADD-AO-1010", qty, "KG", price)]), p)
    assert expected in codes
    assert out.decision == (Decision.BLOCK if expected[1] == "block" else Decision.APPROVE)


def test_price_within_pct_but_above_abs_tolerance_flags():
    # 0.5% above PO but ₹1,000 extra: tolerance is the LOWER of 1% and ₹500, so this flags.
    p = po([po_line(1, "ADD-AO-1010", 2000, "KG", "100.00", received=2000)])
    out, codes = run(invoice([line(1, "ADD-AO-1010", 2000, "KG", "100.50")]), p)
    assert codes == {("PRICE_VARIANCE", "flag")}


# --- Scenario 3: 100 billed, 80 received -> cumulative quantity check
def test_s3_qty_exceeds_gr_blocks_with_cumulative_view():
    p = po([po_line(1, "BRG-6205", 100, "NOS", "450.00", received=80)])
    out, codes = run(invoice([line(1, "BRG-6205", 100, "NOS", "450.00")]), p)
    assert out.decision == Decision.BLOCK and codes == {("QTY_EXCEEDS_GR", "block")}
    ev = out.reasons[0].evidence
    assert (ev["received"], ev["previously_invoiced"], ev["excess"]) == ("80", "0", "20")
    assert out.matrix[0].qty_variance == D(20)


@pytest.mark.parametrize(("billed", "expected"), [
    (20, Decision.APPROVE),   # 80 received, 60 already invoiced: 20 open
    (21, Decision.FLAG),      # 1 over = 1.25% of received: flag
    (25, Decision.BLOCK),     # 5 over = 6.25%: block
])
def test_partial_deliveries_cumulative(billed, expected):
    p = po([po_line(1, "BRG-6205", 100, "NOS", "450.00", received=80, invoiced=60)])
    out, _ = run(invoice([line(1, "BRG-6205", billed, "NOS", "450.00")]), p)
    assert out.decision == expected


def test_bulk_mt_weighbridge_tolerance():
    p = po([po_line(1, "PP-H110", 20, "MT", "95000.00", received="20")], terms=45)
    out, codes = run(invoice([line(1, "PP-H110", "20.08", "MT", "95000.00")]), p)  # +0.4% within 0.5%
    assert out.decision == Decision.APPROVE and codes == {("QTY_EXCEEDS_GR", "info")}


# --- Scenario 4: invoice before goods arrive, then GR posted -> released
def test_s4_missing_gr_blocks_then_releases_after_gr():
    doc = invoice([line(1, "PKG-FFS-25", 20000, "NOS", "14.50")])
    out, codes = run(doc, po([po_line(1, "PKG-FFS-25", 20000, "NOS", "14.50", received=0)]))
    assert out.decision == Decision.BLOCK and codes == {("MISSING_GR", "block")}
    out2, codes2 = run(doc, po([po_line(1, "PKG-FFS-25", 20000, "NOS", "14.50", received=20000)]))
    assert out2.decision == Decision.APPROVE and codes2 == set()


# --- Scenario 6: bank details differ from vendor master -> BLOCK
def test_s6_bank_mismatch_blocks_and_masks():
    p = po([po_line(1, "PUMP-IMP-50", 10, "NOS", "6800.00", received=10)])
    doc = invoice([line(1, "PUMP-IMP-50", 10, "NOS", "6800.00")], bank_account="99887766554433", bank_ifsc="FAKE0999999")
    out, codes = run(doc, p)
    assert out.decision == Decision.BLOCK and codes == {("BANK_MISMATCH", "block")}
    assert "99887766554433" not in out.reasons[0].message  # masked in messages and evidence
    assert out.reasons[0].evidence["invoice_account"] == "XXXXXX4433"


# --- Scenario 9: tax rules
def test_s9_intra_state_igst_flags():
    p = po([po_line(1, "SEAL-M60", 6, "NOS", "9400.00", received=6)])
    out, codes = run(invoice([line(1, "SEAL-M60", 6, "NOS", "9400.00", intra=False)]), p)
    assert out.decision == Decision.FLAG and codes == {("TAX_MISMATCH", "flag")}


def test_s9_invalid_gstin_blocks():
    bad = KESAR_GSTIN[:14] + ("0" if KESAR_GSTIN[14] != "0" else "1")
    p = po([po_line(1, "SEAL-M60", 6, "NOS", "9400.00", received=6)], gstin=bad)
    out, codes = run(invoice([line(1, "SEAL-M60", 6, "NOS", "9400.00")], supplier_gstin=bad), p)
    assert out.decision == Decision.BLOCK and ("GSTIN_INVALID", "block") in codes


def test_gst_rate_differs_from_po():
    p = po([po_line(1, "SEAL-M60", 6, "NOS", "9400.00", rate=12, received=6)])
    out, codes = run(invoice([line(1, "SEAL-M60", 6, "NOS", "9400.00", rate=18)]), p)
    assert ("TAX_MISMATCH", "flag") in codes


# --- Scenario 11: services against a service entry sheet
def test_s11_service_with_ses_approves():
    p = po([po_line(1, "SRV-TA-01", 1, "LS", "420000.00", accepted="420000.00")], service=True)
    out, codes = run(invoice([line(1, "SRV-TA-01", 1, "LS", "420000.00")]), p)
    assert out.decision == Decision.APPROVE and codes == set()


def test_service_without_ses_blocks():
    p = po([po_line(1, "SRV-TA-01", 1, "LS", "420000.00")], service=True)
    out, codes = run(invoice([line(1, "SRV-TA-01", 1, "LS", "420000.00")]), p)
    assert codes == {("MISSING_SES", "block")}


def test_service_billed_above_accepted_value():
    p = po([po_line(1, "FRT-TNK-01", 10, "TRIP", "38000.00", rate=12, accepted="152000.00")], service=True)
    out, codes = run(invoice([line(1, "FRT-TNK-01", 5, "TRIP", "38000.00", rate=12)]), p)
    assert codes == {("SES_VALUE_EXCEEDED", "block")}  # 5 trips billed, 4 accepted: 25% over


# --- Header checks
def test_no_po_no_pay():
    out, codes = run(invoice([line(1, "BRG-6205", 1, "NOS", "450.00")], po=None), None)
    assert out.decision == Decision.BLOCK and codes == {("NO_PO", "block")}


def test_po_closed_supplier_mismatch_currency():
    p = po([po_line(1, "BRG-6205", 100, "NOS", "450.00", received=100)], gstin=SAHYADRI_GSTIN, status="closed")
    doc = invoice([line(1, "BRG-6205", 1, "NOS", "450.00")], currency="USD")
    _, codes = run(doc, p)
    assert {("PO_CLOSED", "block"), ("SUPPLIER_MISMATCH", "block"), ("CURRENCY_MISMATCH", "block")} <= codes


def test_payment_terms_mismatch_flags():
    p = po([po_line(1, "BRG-6205", 100, "NOS", "450.00", received=100)], terms=30)
    out, codes = run(invoice([line(1, "BRG-6205", 1, "NOS", "450.00")]), p)
    assert out.decision == Decision.FLAG and codes == {("PAYMENT_TERMS_MISMATCH", "flag")}


# --- Line mapping
def test_line_mapped_by_description_when_code_differs():
    p = po([po_line(1, "BRG-6205", 100, "NOS", "450.00", received=100, desc="Ball bearing 6205 2RS")])
    doc = invoice([line(1, "KES-0099", 10, "NOS", "450.00", desc="Ball Bearing 6205-2RS")])
    out, codes = run(doc, p)
    assert out.decision == Decision.APPROVE and codes == {("LINE_MAPPED", "info")}


def test_line_not_on_po_blocks():
    p = po([po_line(1, "BRG-6205", 100, "NOS", "450.00", received=100, desc="Ball bearing 6205 2RS")])
    out, codes = run(invoice([line(1, "GLV-01", 10, "NOS", "90.00", desc="Safety gloves")]), p)
    assert codes == {("LINE_NOT_ON_PO", "block")}


# --- Responsible AI: the engine never imports the AI package
def test_engine_has_no_ai_or_io_imports():
    backend = Path(__file__).resolve().parents[1]
    code = ("import sys; import app.engine.decide; "
            "bad=[m for m in sys.modules if m.startswith(('app.ai','app.models','app.core.db','sqlalchemy','anthropic'))]; "
            "print(bad); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=backend, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    import_ai = re.compile(r"^\s*(from|import)\s+app\.ai\b", re.MULTILINE)
    for f in (backend / "app" / "engine").glob("*.py"):
        assert not import_ai.search(f.read_text(encoding="utf-8")), f.name
