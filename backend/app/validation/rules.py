"""Deterministic invoice validation (spec C2 step 6). Pure functions, no I/O.

Each check returns Reason objects using the decision-engine reason codes, so the engine
can merge them directly: GSTIN_INVALID and BILL_TO_MISMATCH block; MATH_ERROR,
TAX_MISMATCH, INVOICE_NO_INVALID and DATE_INVALID flag.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from app.engine.types import InvoiceDoc, Reason
from app.core.enums import Severity
from app.validation import hsn
from app.validation.gstin import STATE_CODES, is_valid_gstin

ROUNDING = Decimal("1.00")  # rupee rounding tolerance
_INV_NO = re.compile(r"^[A-Za-z0-9/\-]{1,16}$")


def fiscal_year(d: date) -> str:
    """Indian financial year, April to March: 2026-11-05 -> '2026-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _fy_start(d: date) -> date:
    return date(d.year if d.month >= 4 else d.year - 1, 4, 1)


def _state(code: str | None) -> str:
    return f"{STATE_CODES.get(code or '', 'state')} ({code})"


def check_gstins(doc: InvoiceDoc, buyer_gstin_expected: str) -> list[Reason]:
    out: list[Reason] = []
    if not doc.supplier_gstin or not is_valid_gstin(doc.supplier_gstin):
        out.append(Reason("GSTIN_INVALID", Severity.BLOCK,
                          f"Supplier GSTIN {doc.supplier_gstin or '(missing)'} fails the format or check-digit test.",
                          {"supplier_gstin": doc.supplier_gstin}))
    if doc.buyer_gstin != buyer_gstin_expected:
        out.append(Reason("BILL_TO_MISMATCH", Severity.BLOCK,
                          f"Invoice is billed to GSTIN {doc.buyer_gstin or '(missing)'}, not Plant X ({buyer_gstin_expected}).",
                          {"invoice_buyer_gstin": doc.buyer_gstin, "plant_x_gstin": buyer_gstin_expected}))
    return out


def check_header(doc: InvoiceDoc, today: date) -> list[Reason]:
    out: list[Reason] = []
    if not _INV_NO.match(doc.invoice_number or ""):
        out.append(Reason("INVOICE_NO_INVALID", Severity.FLAG,
                          f"Invoice number '{doc.invoice_number}' must be 1 to 16 characters (letters, digits, / and -).",
                          {"invoice_number": doc.invoice_number}))
    if doc.invoice_date is None:
        out.append(Reason("DATE_INVALID", Severity.FLAG, "Invoice date is missing.", {}))
    elif doc.invoice_date > today:
        out.append(Reason("DATE_INVALID", Severity.FLAG,
                          f"Invoice date {doc.invoice_date:%d-%m-%Y} is in the future.",
                          {"invoice_date": doc.invoice_date.isoformat(), "today": today.isoformat()}))
    elif doc.invoice_date < date(_fy_start(today).year - 1, 4, 1):
        out.append(Reason("DATE_INVALID", Severity.FLAG,
                          f"Invoice date {doc.invoice_date:%d-%m-%Y} is older than the previous financial year.",
                          {"invoice_date": doc.invoice_date.isoformat(), "fiscal_year": fiscal_year(doc.invoice_date)}))
    return out


def check_arithmetic(doc: InvoiceDoc) -> list[Reason]:
    out: list[Reason] = []
    for ln in doc.lines:
        expected = ln.qty * ln.unit_price
        if abs(expected - ln.taxable_value) > ROUNDING:
            out.append(Reason("MATH_ERROR", Severity.FLAG,
                              f"Line {ln.line_no}: {ln.qty} x {ln.unit_price} = {expected:.2f}, invoice shows {ln.taxable_value:.2f}.",
                              {"qty": str(ln.qty), "unit_price": str(ln.unit_price),
                               "expected": f"{expected:.2f}", "printed": f"{ln.taxable_value:.2f}"}, ln.line_no))
    if doc.lines:
        lines_sum = sum((ln.taxable_value for ln in doc.lines), Decimal(0))
        if abs(lines_sum - doc.taxable_total) > ROUNDING:
            out.append(Reason("MATH_ERROR", Severity.FLAG,
                              f"Lines add up to {lines_sum:.2f} but the taxable total is {doc.taxable_total:.2f}.",
                              {"lines_sum": f"{lines_sum:.2f}", "taxable_total": f"{doc.taxable_total:.2f}"}))
    expected_total = doc.taxable_total + doc.cgst + doc.sgst + doc.igst
    if abs(expected_total - doc.total) > ROUNDING:
        out.append(Reason("MATH_ERROR", Severity.FLAG,
                          f"Taxable {doc.taxable_total:.2f} + tax {doc.cgst + doc.sgst + doc.igst:.2f} = {expected_total:.2f}, "
                          f"but the invoice total is {doc.total:.2f}.",
                          {"expected_total": f"{expected_total:.2f}", "printed_total": f"{doc.total:.2f}"}))
    return out


def check_tax(doc: InvoiceDoc) -> list[Reason]:
    """Same state -> CGST+SGST; different state -> IGST. GST rate must be valid for the HSN."""
    out: list[Reason] = []
    supplier_state = (doc.supplier_gstin or "")[:2] or None
    pos = doc.place_of_supply
    if supplier_state and pos:
        intra = supplier_state == pos
        if intra and doc.igst > 0:
            out.append(Reason("TAX_MISMATCH", Severity.FLAG,
                              f"Intra-state supply ({_state(supplier_state)} to {_state(pos)}) must charge CGST+SGST, "
                              f"but IGST {doc.igst:.2f} was charged.",
                              {"supplier_state": supplier_state, "place_of_supply": pos, "igst": f"{doc.igst:.2f}"}))
        if not intra and (doc.cgst > 0 or doc.sgst > 0):
            out.append(Reason("TAX_MISMATCH", Severity.FLAG,
                              f"Inter-state supply ({_state(supplier_state)} to {_state(pos)}) must charge IGST, "
                              f"but CGST/SGST {doc.cgst + doc.sgst:.2f} was charged.",
                              {"supplier_state": supplier_state, "place_of_supply": pos,
                               "cgst": f"{doc.cgst:.2f}", "sgst": f"{doc.sgst:.2f}"}))
    for ln in doc.lines:
        known = hsn.lookup(ln.hsn_sac)
        if known and ln.gst_rate not in known[2]:
            allowed = ", ".join(f"{r:g}%" for r in sorted(known[2]))
            out.append(Reason("TAX_MISMATCH", Severity.FLAG,
                              f"Line {ln.line_no}: GST {ln.gst_rate:g}% is not valid for HSN {ln.hsn_sac} ({known[1]}); expected {allowed}.",
                              {"hsn_sac": ln.hsn_sac, "gst_rate": str(ln.gst_rate), "allowed": allowed}, ln.line_no))
        line_tax = ln.cgst + ln.sgst + ln.igst
        expected = ln.taxable_value * ln.gst_rate / 100
        if abs(line_tax - expected) > ROUNDING:
            out.append(Reason("TAX_MISMATCH", Severity.FLAG,
                              f"Line {ln.line_no}: tax {line_tax:.2f} does not equal {ln.gst_rate:g}% of {ln.taxable_value:.2f} ({expected:.2f}).",
                              {"line_tax": f"{line_tax:.2f}", "expected": f"{expected:.2f}"}, ln.line_no))
    return out


def validate(doc: InvoiceDoc, buyer_gstin_expected: str, today: date) -> list[Reason]:
    """Run every deterministic validation check."""
    return (check_gstins(doc, buyer_gstin_expected) + check_header(doc, today)
            + check_arithmetic(doc) + check_tax(doc))
