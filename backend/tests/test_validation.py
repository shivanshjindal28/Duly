from dataclasses import replace
from datetime import date
from decimal import Decimal as D

from app.engine.types import DocLine, InvoiceDoc
from app.ingestion.pipeline import normalise_invoice_number
from app.validation.rules import fiscal_year, validate
from tests.fixtures.invoices import KESAR_GSTIN, PLANT_X_GSTIN, SAHYADRI_GSTIN

TODAY = date(2026, 11, 12)


def doc(**kw) -> InvoiceDoc:
    lines = (DocLine(1, "BRG-6205", "Ball bearing", "8482", D(100), "NOS", D("450.00"), D("45000.00"), D(18),
                     D("4050.00"), D("4050.00"), D(0)),)
    base = InvoiceDoc("KES/26-27/0042", date(2026, 11, 5), KESAR_GSTIN, PLANT_X_GSTIN, "24", "4500001234", "INR",
                      D("45000.00"), D("4050.00"), D("4050.00"), D(0), D("53100.00"), lines)
    return replace(base, **kw)


def codes(d: InvoiceDoc) -> list[str]:
    return [r.code for r in validate(d, PLANT_X_GSTIN, TODAY)]


def test_clean_invoice_has_no_issues():
    assert codes(doc()) == []


def test_invalid_gstin_check_digit_blocks():
    bad = KESAR_GSTIN[:14] + ("0" if KESAR_GSTIN[14] != "0" else "1")
    r = validate(doc(supplier_gstin=bad), PLANT_X_GSTIN, TODAY)
    assert [x.code for x in r] == ["GSTIN_INVALID"] and r[0].severity == "block"


def test_bill_to_must_be_plant_x():
    assert codes(doc(buyer_gstin=SAHYADRI_GSTIN)) == ["BILL_TO_MISMATCH"]


def test_intra_state_igst_is_tax_mismatch():
    line = replace(doc().lines[0], cgst=D(0), sgst=D(0), igst=D("8100.00"))
    d = doc(cgst=D(0), sgst=D(0), igst=D("8100.00"), lines=(line,))
    assert codes(d) == ["TAX_MISMATCH"]


def test_inter_state_cgst_is_tax_mismatch():
    d = doc(supplier_gstin=SAHYADRI_GSTIN)  # Maharashtra supplier, place of supply Gujarat
    assert codes(d) == ["TAX_MISMATCH"]


def test_wrong_gst_rate_for_hsn():
    line = replace(doc().lines[0], gst_rate=D(12), cgst=D("2700.00"), sgst=D("2700.00"))
    d = doc(cgst=D("2700.00"), sgst=D("2700.00"), total=D("50400.00"), lines=(line,))
    assert codes(d) == ["TAX_MISMATCH"]


def test_arithmetic_errors():
    line = replace(doc().lines[0], taxable_value=D("46000.00"))
    assert "MATH_ERROR" in codes(doc(lines=(line,)))
    assert codes(doc(total=D("53200.00"))) == ["MATH_ERROR"]
    assert codes(doc(total=D("53100.80"))) == []  # rounding within one rupee is fine


def test_date_and_number_rules():
    assert codes(doc(invoice_date=date(2026, 12, 1))) == ["DATE_INVALID"]
    assert codes(doc(invoice_date=date(2024, 3, 31))) == ["DATE_INVALID"]
    assert codes(doc(invoice_date=date(2025, 4, 1))) == []
    assert codes(doc(invoice_number="KES/2026-2027/000042")) == ["INVOICE_NO_INVALID"]


def test_fiscal_year():
    assert fiscal_year(date(2026, 11, 5)) == "2026-27"
    assert fiscal_year(date(2027, 3, 31)) == "2026-27"
    assert fiscal_year(date(2027, 4, 1)) == "2027-28"


def test_invoice_number_normalisation():
    assert normalise_invoice_number("INV/0042") == normalise_invoice_number("INV-42") == "42"
    assert normalise_invoice_number("inv 0O42") == "42"
    assert normalise_invoice_number("KES/26-27/0042") != normalise_invoice_number("KES/26-27/0043")
