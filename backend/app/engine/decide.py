"""Three-way match and decision engine (spec C3). Pure and deterministic: no I/O, no AI.

Input: the invoice (as the rules see it), its PO, receipts (GR/SES) and invoicing history
per PO line, the supplier master, and the tolerance policy.
Output: APPROVE / FLAG / BLOCK, the reason codes with evidence, and a per-line match matrix.
Any BLOCK reason blocks; otherwise any FLAG flags; otherwise the invoice is approved
(routed to the approval workflow, which may approve it by policy if it is small).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from rapidfuzz import fuzz

from app.engine.policy import Tolerances
from app.engine.types import DocLine, InvoiceDoc, Reason
from app.core.enums import Decision, Severity
from app.validation.rules import validate

ENGINE_VERSION = "engine-1.0"
FUZZY_MIN = 85  # rapidfuzz token_set_ratio needed to map a line by description
ZERO = Decimal(0)
HUNDRED = Decimal(100)

# Unit conversions to the PO's unit: (invoice uom, po uom) -> factor (po_qty = inv_qty * factor).
UOM_FACTORS: dict[tuple[str, str], Decimal] = {
    ("KG", "MT"): Decimal("0.001"), ("MT", "KG"): Decimal("1000"),
    ("G", "KG"): Decimal("0.001"), ("KG", "G"): Decimal("1000"),
    ("L", "KL"): Decimal("0.001"), ("KL", "L"): Decimal("1000"),
}
UOM_ALIASES = {"NO": "NOS", "NOS.": "NOS", "PCS": "NOS", "EA": "NOS", "KGS": "KG", "LTR": "L", "TON": "MT"}


@dataclass(frozen=True)
class PoLineView:
    id: int
    line_no: int
    item_code: str
    description: str
    qty: Decimal
    uom: str
    unit_price: Decimal
    gst_rate: Decimal
    received_qty: Decimal = ZERO  # GR quantity posted (goods), in PO unit
    accepted_value: Decimal = ZERO  # SES value accepted (services)
    invoiced_qty: Decimal = ZERO  # already invoiced on other invoices, in PO unit
    invoiced_value: Decimal = ZERO  # already invoiced value (services)


@dataclass(frozen=True)
class PoView:
    po_number: str
    supplier_gstin: str
    status: str
    currency: str
    payment_terms_days: int
    is_service: bool
    lines: tuple[PoLineView, ...]


@dataclass(frozen=True)
class SupplierView:
    gstin: str
    payment_terms_days: int
    bank_account: str
    bank_ifsc: str


@dataclass(frozen=True)
class MatrixRow:
    """One row of the match matrix grid: PO | GR | Invoice | Variance."""

    invoice_line_no: int
    po_line_id: int | None
    po_line_no: int | None
    description: str
    po_qty: Decimal | None
    po_price: Decimal | None
    received: Decimal | None  # GR qty (goods) or accepted SES value (services)
    previously_invoiced: Decimal | None
    invoice_qty: Decimal  # converted to the PO unit
    invoice_price: Decimal  # per PO unit
    uom: str
    price_variance_pct: Decimal | None
    price_variance_amount: Decimal | None
    qty_variance: Decimal | None


@dataclass(frozen=True)
class MatchOutcome:
    decision: Decision
    reasons: tuple[Reason, ...]
    matrix: tuple[MatrixRow, ...]
    line_map: dict[int, int] = field(default_factory=dict)  # invoice line_no -> po_line_id
    engine_version: str = ENGINE_VERSION
    policy_version: int = 1


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _norm_uom(u: str) -> str:
    u = (u or "").strip().upper()
    return UOM_ALIASES.get(u, u)


def _inr(v: Decimal) -> str:
    return f"₹{_q2(v):,.2f}"


def _norm_text(s: str) -> str:
    """Lowercase and turn punctuation into spaces: '6205-2RS' and '6205 2rs' compare equal."""
    return " ".join("".join(ch if ch.isalnum() else " " for ch in s.lower()).split())


def map_lines(doc: InvoiceDoc, po: PoView) -> dict[int, tuple[PoLineView, str]]:
    """Invoice line_no -> (PO line, how it was matched: 'item_code' | 'description')."""
    out: dict[int, tuple[PoLineView, str]] = {}
    used: set[int] = set()
    for ln in doc.lines:
        code = (ln.item_code or "").strip().upper()
        hit = next((p for p in po.lines if p.id not in used and p.item_code.upper() == code), None)
        how = "item_code"
        if hit is None:
            scored = [(fuzz.token_set_ratio(_norm_text(ln.description), _norm_text(p.description)), p)
                      for p in po.lines if p.id not in used]
            best = max(scored, key=lambda s: s[0], default=(0, None))
            if best[0] >= FUZZY_MIN:
                hit, how = best[1], "description"
        if hit is not None:
            used.add(hit.id)
            out[ln.line_no] = (hit, how)
    return out


def _header_checks(doc: InvoiceDoc, po: PoView | None, supplier: SupplierView) -> list[Reason]:
    out: list[Reason] = []
    if po is None:
        out.append(Reason("NO_PO", Severity.BLOCK,
                          "No PO, no pay: the invoice has no purchase order number we can find."
                          if doc.po_number else "No PO, no pay: the invoice does not quote a purchase order number.",
                          {"po_number_on_invoice": doc.po_number}))
        return out
    if po.status != "open":
        out.append(Reason("PO_CLOSED", Severity.BLOCK, f"PO {po.po_number} is {po.status}; it cannot be invoiced.",
                          {"po_number": po.po_number, "po_status": po.status}))
    if doc.supplier_gstin and doc.supplier_gstin != po.supplier_gstin:
        out.append(Reason("SUPPLIER_MISMATCH", Severity.BLOCK,
                          f"Invoice GSTIN {doc.supplier_gstin} is not the PO supplier ({po.supplier_gstin}).",
                          {"invoice_gstin": doc.supplier_gstin, "po_supplier_gstin": po.supplier_gstin}))
    if doc.currency != po.currency:
        out.append(Reason("CURRENCY_MISMATCH", Severity.BLOCK,
                          f"Invoice currency {doc.currency} differs from PO currency {po.currency}.",
                          {"invoice_currency": doc.currency, "po_currency": po.currency}))
    if po.payment_terms_days != supplier.payment_terms_days:
        out.append(Reason("PAYMENT_TERMS_MISMATCH", Severity.FLAG,
                          f"PO terms are {po.payment_terms_days} days but the vendor master says "
                          f"{supplier.payment_terms_days} days.",
                          {"po_terms_days": po.payment_terms_days, "vendor_terms_days": supplier.payment_terms_days}))
    return out


def _bank_check(doc: InvoiceDoc, supplier: SupplierView) -> list[Reason]:
    if not doc.bank_account and not doc.bank_ifsc:
        return []
    acct_differs = bool(doc.bank_account) and doc.bank_account != supplier.bank_account
    ifsc_differs = bool(doc.bank_ifsc) and doc.bank_ifsc != supplier.bank_ifsc
    if not (acct_differs or ifsc_differs):
        return []
    mask = lambda a: ("XXXXXX" + a[-4:]) if a else "(none)"  # noqa: E731
    return [Reason("BANK_MISMATCH", Severity.BLOCK,
                   f"Bank details on the invoice (a/c {mask(doc.bank_account)}, IFSC {doc.bank_ifsc}) differ from the "
                   f"vendor master (a/c {mask(supplier.bank_account)}, IFSC {supplier.bank_ifsc}). Possible payment fraud.",
                   {"invoice_account": mask(doc.bank_account), "invoice_ifsc": doc.bank_ifsc,
                    "master_account": mask(supplier.bank_account), "master_ifsc": supplier.bank_ifsc})]


def _price_check(ln: DocLine, p: PoLineView, qty: Decimal, price: Decimal, tol: Tolerances) -> list[Reason]:
    diff_unit = price - p.unit_price
    if diff_unit == 0:
        return []
    pct = diff_unit / p.unit_price * HUNDRED if p.unit_price else HUNDRED
    amount = _q2(diff_unit * qty)
    ev = {"po_price": str(p.unit_price), "invoice_price": str(_q2(price)), "variance_pct": f"{pct:.2f}",
          "variance_amount": str(amount), "qty": str(qty), "tolerance_pct": str(tol.pp_flag_pct),
          "tolerance_abs": str(tol.pp_flag_abs), "block_pct": str(tol.pp_block_pct)}
    where = f"Line {ln.line_no} ({p.item_code})"
    if diff_unit < 0:
        return [Reason("PRICE_VARIANCE", Severity.INFO,
                       f"{where}: billed {_inr(-amount)} below the PO price ({pct:.2f}%). No action needed.",
                       ev, ln.line_no)]
    if abs(amount) <= tol.bd_abs:
        return [Reason("SMALL_DIFFERENCE", Severity.INFO,
                       f"{where}: price difference of {_inr(amount)} is within the small-difference tolerance "
                       f"({_inr(tol.bd_abs)}) and auto-accepted.", ev, ln.line_no)]
    if pct <= tol.pp_flag_pct and amount <= tol.pp_flag_abs:
        return [Reason("PRICE_VARIANCE", Severity.INFO,
                       f"{where}: price {pct:.2f}% ({_inr(amount)}) above PO, within tolerance "
                       f"({tol.pp_flag_pct}% or {_inr(tol.pp_flag_abs)}, whichever is lower).", ev, ln.line_no)]
    sev = Severity.BLOCK if pct > tol.pp_block_pct else Severity.FLAG
    return [Reason("PRICE_VARIANCE", sev,
                   f"{where}: unit price {_inr(price)} is {pct:.2f}% above the PO price {_inr(p.unit_price)}; "
                   f"{_inr(amount)} more on {qty:g} units.", ev, ln.line_no)]


def _goods_qty_check(ln: DocLine, p: PoLineView, qty: Decimal, uom: str, tol: Tolerances) -> list[Reason]:
    where = f"Line {ln.line_no} ({p.item_code})"
    if p.received_qty <= 0:
        return [Reason("MISSING_GR", Severity.BLOCK,
                       f"{where}: no goods receipt has been posted for this item yet. Duly will re-check "
                       "automatically when stores posts the GR.",
                       {"po_line": p.line_no, "received": "0", "invoiced_now": str(qty)}, ln.line_no)]
    open_qty = p.received_qty - p.invoiced_qty
    excess = qty - open_qty
    if excess <= 0:
        return []
    allowed_pct = tol.dq_bulk_mt_pct if uom == "MT" else tol.dq_default_pct
    excess_pct = excess / p.received_qty * HUNDRED
    ev = {"received": str(p.received_qty), "previously_invoiced": str(p.invoiced_qty), "open_to_invoice": str(open_qty),
          "invoiced_now": str(qty), "excess": str(excess), "excess_pct": f"{excess_pct:.2f}",
          "tolerance_pct": str(allowed_pct), "uom": uom}
    if excess_pct <= allowed_pct:
        return [Reason("QTY_EXCEEDS_GR", Severity.INFO,
                       f"{where}: billed {excess:g} {uom} over received, within the {allowed_pct}% quantity tolerance.",
                       ev, ln.line_no)]
    sev = Severity.BLOCK if excess_pct > tol.dq_block_pct else Severity.FLAG
    return [Reason("QTY_EXCEEDS_GR", sev,
                   f"{where}: billed {qty:g} {uom}, but only {open_qty:g} {uom} is received and not yet invoiced "
                   f"({p.received_qty:g} received, {p.invoiced_qty:g} already invoiced). Excess {excess:g} {uom}.",
                   ev, ln.line_no)]


def _service_check(ln: DocLine, p: PoLineView, tol: Tolerances) -> list[Reason]:
    where = f"Line {ln.line_no} ({p.item_code})"
    if p.accepted_value <= 0:
        return [Reason("MISSING_SES", Severity.BLOCK,
                       f"{where}: no service entry sheet confirms these services were performed.",
                       {"po_line": p.line_no, "accepted_value": "0"}, ln.line_no)]
    open_value = p.accepted_value - p.invoiced_value
    excess = ln.taxable_value - open_value
    if excess <= tol.bd_abs:
        return []
    ev = {"accepted_value": str(p.accepted_value), "previously_invoiced": str(p.invoiced_value),
          "invoiced_now": str(ln.taxable_value), "excess": str(_q2(excess))}
    pct = excess / p.accepted_value * HUNDRED
    sev = Severity.BLOCK if pct > tol.dq_block_pct else Severity.FLAG
    return [Reason("SES_VALUE_EXCEEDED", sev,
                   f"{where}: billed {_inr(ln.taxable_value)} but only {_inr(open_value)} of services is accepted "
                   f"and not yet invoiced.", ev, ln.line_no)]


def decide(doc: InvoiceDoc, po: PoView | None, supplier: SupplierView, tol: Tolerances,
           plant_gstin: str, today) -> MatchOutcome:
    reasons: list[Reason] = list(validate(doc, plant_gstin, today))
    reasons += _header_checks(doc, po, supplier)
    reasons += _bank_check(doc, supplier)
    matrix: list[MatrixRow] = []
    line_map: dict[int, int] = {}

    if po is not None:
        mapping = map_lines(doc, po)
        for ln in doc.lines:
            hit = mapping.get(ln.line_no)
            if hit is None:
                reasons.append(Reason("LINE_NOT_ON_PO", Severity.BLOCK,
                                      f"Line {ln.line_no} ({ln.item_code or ln.description}) is not on PO {po.po_number}.",
                                      {"item_code": ln.item_code, "description": ln.description}, ln.line_no))
                matrix.append(MatrixRow(ln.line_no, None, None, ln.description, None, None, None, None, ln.qty,
                                        ln.unit_price, ln.uom, None, None, None))
                continue
            p, how = hit
            line_map[ln.line_no] = p.id
            inv_uom, po_uom = _norm_uom(ln.uom), _norm_uom(p.uom)
            qty, price = ln.qty, ln.unit_price
            if inv_uom != po_uom:
                factor = UOM_FACTORS.get((inv_uom, po_uom))
                if factor is None:
                    reasons.append(Reason("LINE_NOT_ON_PO", Severity.BLOCK,
                                          f"Line {ln.line_no}: unit {ln.uom} cannot be converted to the PO unit {p.uom}.",
                                          {"invoice_uom": ln.uom, "po_uom": p.uom}, ln.line_no))
                    continue
                qty, price = ln.qty * factor, ln.unit_price / factor
                reasons.append(Reason("UOM_CONVERTED", Severity.INFO,
                                      f"Line {ln.line_no}: {ln.qty:g} {inv_uom} converted to {qty:g} {po_uom} "
                                      f"(price {_inr(ln.unit_price)}/{inv_uom} = {_inr(price)}/{po_uom}).",
                                      {"from": f"{ln.qty} {inv_uom}", "to": f"{qty} {po_uom}"}, ln.line_no))
            if how == "description":
                reasons.append(Reason("LINE_MAPPED", Severity.INFO,
                                      f"Line {ln.line_no} matched to PO line {p.line_no} ({p.item_code}) by description.",
                                      {"invoice_description": ln.description, "po_description": p.description},
                                      ln.line_no))
            if ln.gst_rate != p.gst_rate:
                reasons.append(Reason("TAX_MISMATCH", Severity.FLAG,
                                      f"Line {ln.line_no}: GST {ln.gst_rate:g}% differs from the PO rate {p.gst_rate:g}%.",
                                      {"invoice_rate": str(ln.gst_rate), "po_rate": str(p.gst_rate)}, ln.line_no))
            reasons += _price_check(ln, p, qty, price, tol)
            if po.is_service:
                reasons += _service_check(ln, p, tol)
                received, prev = p.accepted_value, p.invoiced_value
                qty_var = None
            else:
                reasons += _goods_qty_check(ln, p, qty, po_uom, tol)
                received, prev = p.received_qty, p.invoiced_qty
                qty_var = qty - (p.received_qty - p.invoiced_qty)
            pct = ((price - p.unit_price) / p.unit_price * HUNDRED) if p.unit_price else None
            matrix.append(MatrixRow(
                ln.line_no, p.id, p.line_no, p.description, p.qty, p.unit_price, received, prev, qty,
                _q2(price), po_uom, _q2(pct) if pct is not None else None, _q2((price - p.unit_price) * qty), qty_var,
            ))

    if any(r.severity == Severity.BLOCK for r in reasons):
        decision = Decision.BLOCK
    elif any(r.severity == Severity.FLAG for r in reasons):
        decision = Decision.FLAG
    else:
        decision = Decision.APPROVE
    return MatchOutcome(decision, tuple(reasons), tuple(matrix), line_map, ENGINE_VERSION, tol.version)
