"""Offline extractor: label regexes and a right-to-left table row parser over positioned text.

Works on the PDF text layer and on OCR output (which often drops spaces, e.g.
"InvoiceNo:KES/26-27/0042"), so every label pattern tolerates missing whitespace.
This is the "AI: offline (OCR)" path: no network, no model, deterministic.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.ai.schema import HEADER_FIELDS, ExtractedField, ExtractedInvoice
from app.ingestion.tokens import TextLine, Token, group_lines

VERSION = "offline-regex-1.0"

_AMT = r"([0-9][0-9,]*\.\d{2})"
_GSTIN = r"([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z])"
_I = re.IGNORECASE

HEADER_PATTERNS: dict[str, re.Pattern] = {
    "invoice_number": re.compile(r"invoice\s*(?:no|number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{0,30})", _I),
    "invoice_date": re.compile(r"invoice\s*date\s*[:\-]?\s*(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})", _I),
    "po_number": re.compile(r"\bP\.?\s*O\.?\s*(?:no|number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{3,20})", _I),
    "place_of_supply": re.compile(r"place\s*of\s*supply\s*[:\-]?[^(]*\((\d{2})\)", _I),
    "buyer_gstin": re.compile(r"buyer\s*gstin\s*[:\-]?\s*" + _GSTIN, _I),
    "supplier_gstin": re.compile(r"(?<![A-Za-z])gstin\s*[:\-]?\s*" + _GSTIN, _I),
    "taxable_total": re.compile(r"taxable\s*value\s*[:\-]?\s*" + _AMT, _I),
    "cgst": re.compile(r"^\s*cgst\s*[:\-]?\s*" + _AMT + r"\s*$", _I),
    "sgst": re.compile(r"^\s*sgst\s*[:\-]?\s*" + _AMT + r"\s*$", _I),
    "igst": re.compile(r"^\s*igst\s*[:\-]?\s*" + _AMT + r"\s*$", _I),
    "total": re.compile(r"(?:total\s*invoice\s*value|grand\s*total|invoice\s*total)\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*" + _AMT, _I),
    "bank_account": re.compile(r"a\s*/?\s*c\s*(?:no|number)?\.?\s*[:\-]?\s*(\d{9,18})\b", _I),
    "bank_ifsc": re.compile(r"ifsc\s*(?:code)?\s*[:\-]?\s*([A-Z]{4}0[A-Z0-9]{6})", _I),
    "irn": re.compile(r"\birn\s*[:\-]?\s*([0-9a-f]{64})", _I),
}

_MONEY_RE = re.compile(r"^[0-9][0-9,]*\.\d{2}$")
_NUM_RE = re.compile(r"^[0-9][0-9,]*(?:\.\d+)?$")
_HSN_RE = re.compile(r"^\d{4,8}$")
_UOM_RE = re.compile(r"^[A-Za-z]{1,5}$")
# Row tokenizer. OCR glues neighbouring cells, so split amounts ("4,050.004,050.00") and
# quantity+unit ("100NOS") before falling back to whitespace-separated pieces.
_PIECE_RE = re.compile(
    r"(?<![\w.,])[0-9][0-9,]*\.\d{2}"
    r"|(?<![\w.,])[0-9][0-9,]*(?:\.\d+)?(?=[A-Za-z]{2,5}(?:\s|$))"
    r"|\S+"
)


def _num(s: str) -> str | None:
    try:
        return str(Decimal(s.replace(",", "")))
    except InvalidOperation:
        return None


def _date(s: str) -> str | None:
    s = re.sub(r"[/.]", "-", s)
    for fmt in ("%d-%m-%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _field(line: TextLine, span: tuple[int, int], value: str | None, factor: float = 1.0) -> ExtractedField:
    bbox, conf = line.locate(*span)
    source = line.tokens[0].source
    base = 0.98 if source == "text" else conf * 0.97
    return ExtractedField(value=value, confidence=round(max(0.0, min(1.0, base * factor)), 3),
                          page=line.page, bbox=bbox, source=source)


def _normalise(name: str, raw: str) -> str | None:
    if name in {"taxable_total", "cgst", "sgst", "igst", "total"}:
        return _num(raw)
    if name == "invoice_date":
        return _date(raw)
    if name in {"supplier_gstin", "buyer_gstin", "bank_ifsc", "po_number", "invoice_number"}:
        return raw.upper()
    if name == "irn":
        return raw.lower()
    return raw


def _parse_header(lines: list[TextLine]) -> dict[str, ExtractedField]:
    header: dict[str, ExtractedField] = {}
    for name, pat in HEADER_PATTERNS.items():
        for line in lines:
            m = pat.search(line.text)
            if not m:
                continue
            # The supplier GSTIN pattern must not pick up the buyer's line.
            if name == "supplier_gstin" and re.search(r"buyer\s*$", line.text[: m.start()], _I):
                continue
            value = _normalise(name, m.group(1))
            header[name] = _field(line, m.span(1), value, 1.0 if value is not None else 0.5)
            break
    # Supplier name: the first line of page 1 (the letterhead).
    first = next((ln for ln in lines if ln.page == 1), None)
    if first:
        header["supplier_name"] = _field(first, (0, len(first.text)), first.text.strip(), 0.92)
    # Currency is rarely printed on domestic invoices; INR is assumed and marked as a rule.
    if "currency" not in header:
        header["currency"] = ExtractedField(value="INR", confidence=0.9, source="rule")
    for name in HEADER_FIELDS:
        header.setdefault(name, ExtractedField())
    return header


def _parse_row(line: TextLine) -> dict[str, ExtractedField] | None:
    """Parse a table row from the right: igst sgst cgst [gst%] taxable rate uom qty hsn | [no] code [desc].

    On poor photos OCR can lose the GST % cell or the description. Then the rate is derived
    from tax / taxable value and the description left empty, both at low confidence so a
    human confirms them; the row is not thrown away.
    """
    # Amounts first, so glued cells like "4,050.004,050.00" split into two amounts.
    pieces = [(m.group(), m.span()) for m in _PIECE_RE.finditer(line.text)]
    if len(pieces) < 8:
        return None
    igst, sgst, cgst = pieces[-1], pieces[-2], pieces[-3]
    rest = pieces[:-3]
    rate_pct = None
    if rest and _NUM_RE.match(rest[-1][0]) and not _MONEY_RE.match(rest[-1][0]):
        rate_pct, rest = rest[-1], rest[:-1]
    if len(rest) < 6:
        return None
    taxable, unit_price, uom, qty = rest[-1], rest[-2], rest[-3], rest[-4]
    if not all(_MONEY_RE.match(p[0]) for p in (igst, sgst, cgst, taxable, unit_price)):
        return None
    if not (_UOM_RE.match(uom[0]) and _NUM_RE.match(qty[0])):
        return None
    head = rest[:-4]
    if head and head[0][0].isdigit() and len(head[0][0]) <= 3:
        head = head[1:]  # leading line number (OCR sometimes drops it, so it is optional)
    if len(head) < 2 or not _HSN_RE.match(head[-1][0]):
        return None
    hsn, code = head[-1], head[0]
    desc_span = (head[1][1][0], head[-2][1][1]) if len(head) > 2 else None

    # On OCR text a broken row equation usually means a misread digit: lower numeric confidence.
    q, p, v = (Decimal(_num(x[0]) or "0") for x in (qty, unit_price, taxable))
    consistent = abs(q * p - v) <= Decimal("1.00")
    num_factor = 1.0 if (consistent or line.tokens[0].source == "text") else 0.8

    def f(piece, value, factor=1.0):
        return _field(line, piece[1], value, factor)

    if rate_pct is not None:
        gst_rate = f(rate_pct, _num(rate_pct[0]))
    else:  # derived: (cgst + sgst + igst) / taxable, rounded to a whole percent
        tax = sum((Decimal(_num(x[0]) or "0") for x in (cgst, sgst, igst)), Decimal(0))
        derived = str((tax / v * 100).quantize(Decimal("1"))) if v else None
        gst_rate = _field(line, (cgst[1][0], igst[1][1]), derived, 0.6)
    if desc_span is not None:
        description = f((None, desc_span), line.text[desc_span[0]:desc_span[1]])
    else:
        description = ExtractedField(value=None, source=line.tokens[0].source)

    return {
        "item_code": f(code, code[0].upper()),
        "description": description,
        "hsn_sac": f(hsn, hsn[0]),
        "qty": f(qty, _num(qty[0]), num_factor),
        "uom": f(uom, uom[0].upper()),
        "unit_price": f(unit_price, _num(unit_price[0]), num_factor),
        "taxable_value": f(taxable, _num(taxable[0]), num_factor),
        "gst_rate": gst_rate,
        "cgst": f(cgst, _num(cgst[0])),
        "sgst": f(sgst, _num(sgst[0])),
        "igst": f(igst, _num(igst[0])),
    }


def parse(tokens: list[Token], method: str) -> ExtractedInvoice:
    lines = group_lines(tokens)
    rows = [r for r in (_parse_row(ln) for ln in lines) if r]
    return ExtractedInvoice(header=_parse_header(lines), lines=rows, method=method,
                            extractor="offline-regex", extractor_version=VERSION)
