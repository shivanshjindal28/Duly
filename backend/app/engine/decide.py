"""Three-way match and decision engine (spec C3). Pure and deterministic: no I/O, no AI.

Input: the invoice (as the rules see it), its PO, receipts (GR/SES) and invoicing history
per PO line, the supplier master, and the tolerance policy.
Output: APPROVE / FLAG / BLOCK, the reason codes with evidence, and a per-line match matrix.
Any BLOCK reason blocks; otherwise any FLAG flags; otherwise the invoice is approved
(routed to the approval workflow, which may approve it by policy if it is small).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal

from rapidfuzz import fuzz

from app.engine import units
from app.engine.policy import Tolerances
from app.engine.types import DocLine, InvoiceDoc, Reason, fmt_money
from app.engine.types import fmt_num as _n
from app.core.enums import Decision, Severity
from app.validation.rules import validate

ENGINE_VERSION = "engine-1.1"
FUZZY_MIN = 85  # rapidfuzz token_set_ratio needed to map a line by description
ZERO = Decimal(0)
HUNDRED = Decimal(100)

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
    packs: tuple[units.Pack, ...] = ()  # item pack sizes, e.g. (("BOX", 10, "NOS"),)


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
    invoice_uom: str = ""  # unit as billed
    invoice_qty_billed: Decimal | None = None  # quantity as billed (before unit conversion)
    currency: str = "INR"  # currency of the PO (prices above)


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
    return units.norm(u)


def _norm_text(s: str) -> str:
    """Lowercase and turn punctuation into spaces: '6205-2RS' and '6205 2rs' compare equal."""
    return " ".join("".join(ch if ch.isalnum() else " " for ch in s.lower()).split())


def map_lines(doc: InvoiceDoc, po: PoView) -> dict[int, tuple[PoLineView, str]]:
    """Invoice line_no -> (PO line, how it was matched: 'confirmed' | 'item_code' | 'description')."""
    out: dict[int, tuple[PoLineView, str]] = {}
    used: set[int] = set()
    for ln in doc.lines:
        if ln.mapping_rejected:  # a person said this line is not on the PO
            continue
        if ln.confirmed_po_line_id is not None:
            hit = next((p for p in po.lines if p.id == ln.confirmed_po_line_id and p.id not in used), None)
            if hit is not None:
                used.add(hit.id)
                out[ln.line_no] = (hit, "confirmed")
                continue
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


def _fx(from_ccy: str, to_ccy: str, tol: Tolerances) -> Decimal | None:
    """Units of `to_ccy` per one `from_ccy`, via INR; None if the policy has no rate."""
    a, b = tol.rate(from_ccy), tol.rate(to_ccy)
    if a is None or b is None or not b:
        return None
    return a / b


def _header_checks(doc: InvoiceDoc, po: PoView | None, supplier: SupplierView, tol: Tolerances) -> list[Reason]:
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
                          f"Invoice {'tax ID' if doc.foreign else 'GSTIN'} {doc.supplier_gstin} is not the PO supplier "
                          f"({po.supplier_gstin}).",
                          {"invoice_gstin": doc.supplier_gstin, "po_supplier_gstin": po.supplier_gstin}))
    if doc.currency != po.currency:
        fx = _fx(doc.currency, po.currency, tol)
        if fx is None:
            out.append(Reason("CURRENCY_MISMATCH", Severity.BLOCK,
                              f"Invoice currency {doc.currency} differs from PO currency {po.currency}, and the policy "
                              f"has no exchange rate for it, so the amounts cannot be compared.",
                              {"invoice_currency": doc.currency, "po_currency": po.currency}))
        else:
            out.append(Reason("CURRENCY_CONVERTED", Severity.FLAG,
                              f"Invoice in {doc.currency} against a PO in {po.currency}: prices converted at the policy "
                              f"rate 1 {doc.currency} = {fx:.6g} {po.currency} (rates as of {tol.fx_as_of or 'policy'}). "
                              "A person must confirm the supplier may bill in this currency.",
                              {"invoice_currency": doc.currency, "po_currency": po.currency, "rate": f"{fx:.6f}",
                               "rates_as_of": tol.fx_as_of}))
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


def _price_check(ln: DocLine, p: PoLineView, qty: Decimal, price: Decimal, tol: Tolerances,
                 ccy: str = "INR") -> list[Reason]:
    _inr = lambda v: fmt_money(v, ccy)  # noqa: E731
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
                   f"{_inr(amount)} more on {_n(qty)} units.", ev, ln.line_no)]


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
                       f"{where}: billed {_n(excess)} {uom} over received, within the {allowed_pct}% quantity tolerance.",
                       ev, ln.line_no)]
    sev = Severity.BLOCK if excess_pct > tol.dq_block_pct else Severity.FLAG
    return [Reason("QTY_EXCEEDS_GR", sev,
                   f"{where}: billed {_n(qty)} {uom}, but only {_n(open_qty)} {uom} is received and not yet invoiced "
                   f"({_n(p.received_qty)} received, {_n(p.invoiced_qty)} already invoiced). Excess {_n(excess)} {uom}.",
                   ev, ln.line_no)]


def _service_check(ln: DocLine, p: PoLineView, tol: Tolerances, ccy: str = "INR") -> list[Reason]:
    _inr = lambda v: fmt_money(v, ccy)  # noqa: E731
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
           plant_gstin: str, today, extra_reasons: tuple[Reason, ...] = ()) -> MatchOutcome:
    """extra_reasons: findings computed outside the engine from other invoices (duplicates)."""
    reasons: list[Reason] = list(validate(doc, plant_gstin, today))
    reasons += extra_reasons
    reasons += _header_checks(doc, po, supplier, tol)
    reasons += _bank_check(doc, supplier)
    matrix: list[MatrixRow] = []
    line_map: dict[int, int] = {}

    if not doc.lines:
        # Without lines there is nothing to match against the PO and GR: never approve.
        reasons.append(Reason("NO_LINES", Severity.BLOCK,
                              "No line items could be read from the invoice, so it cannot be matched to the PO "
                              "and goods receipt. Enter the lines or ask the supplier for a clearer copy.",
                              {"lines_read": 0, "invoice_total": str(doc.total)}))

    if po is not None:
        ccy = po.currency
        fx = _fx(doc.currency, ccy, tol) if doc.currency != ccy else Decimal(1)
        if fx is None:
            fx = Decimal(1)  # CURRENCY_MISMATCH already blocks; compare as printed
        # Rupee tolerances (PP absolute, BD) expressed in the PO's currency.
        po_rate = tol.rate(ccy)
        if ccy != "INR" and po_rate:
            tol = replace(tol, pp_flag_abs=tol.pp_flag_abs / po_rate, bd_abs=tol.bd_abs / po_rate)
        mapping = map_lines(doc, po)
        for ln in doc.lines:
            hit = mapping.get(ln.line_no)
            if hit is None:
                reasons.append(Reason("LINE_NOT_ON_PO", Severity.BLOCK,
                                      f"Line {ln.line_no} ({ln.item_code or ln.description}) is not on PO {po.po_number}.",
                                      {"item_code": ln.item_code, "description": ln.description}, ln.line_no))
                matrix.append(MatrixRow(ln.line_no, None, None, ln.description, None, None, None, None, ln.qty,
                                        ln.unit_price, ln.uom, None, None, None, ln.uom, ln.qty, doc.currency))
                continue
            p, how = hit
            line_map[ln.line_no] = p.id
            inv_uom, po_uom = _norm_uom(ln.uom), _norm_uom(p.uom)
            # Prices in the PO currency; quantities net of credit notes.
            qty, price = ln.qty - ln.credited_qty, ln.unit_price * fx
            if inv_uom != po_uom:
                factor = units.factor(inv_uom, po_uom, p.packs)
                if factor is None:
                    reasons.append(Reason("UOM_MISMATCH", Severity.BLOCK,
                                          f"Line {ln.line_no}: billed in {ln.uom}, which cannot be converted to the PO unit "
                                          f"{p.uom} (no standard conversion and no pack size for {p.item_code}).",
                                          {"invoice_uom": ln.uom, "po_uom": p.uom, "item_code": p.item_code}, ln.line_no))
                    matrix.append(MatrixRow(ln.line_no, p.id, p.line_no, p.description, p.qty, p.unit_price, None, None,
                                            ln.qty, _q2(price), ln.uom, None, None, None, ln.uom, ln.qty, ccy))
                    continue
                qty, price = (ln.qty - ln.credited_qty) * factor, price / factor
                reasons.append(Reason("UOM_CONVERTED", Severity.INFO,
                                      f"Line {ln.line_no}: {_n(ln.qty)} {inv_uom} = {_n(qty)} {po_uom} "
                                      f"({units.describe(inv_uom, po_uom, p.packs)}); price "
                                      f"{fmt_money(ln.unit_price * fx, ccy)}/{inv_uom} = {fmt_money(price, ccy)}/{po_uom}.",
                                      {"from": f"{ln.qty} {inv_uom}", "to": f"{qty} {po_uom}",
                                       "rule": units.describe(inv_uom, po_uom, p.packs)}, ln.line_no))
            if how == "description":  # a suggestion only: a person must confirm it before it can be approved
                reasons.append(Reason("LINE_MAPPED", Severity.FLAG,
                                      f"Line {ln.line_no} looks like PO line {p.line_no} ({p.item_code}) by description; "
                                      "a clerk must confirm the match.",
                                      {"invoice_description": ln.description, "po_description": p.description,
                                       "po_line_id": p.id, "po_line_no": p.line_no, "po_item_code": p.item_code},
                                      ln.line_no))
            elif how == "confirmed":
                reasons.append(Reason("LINE_MAPPED", Severity.INFO,
                                      f"Line {ln.line_no} matched to PO line {p.line_no} ({p.item_code}), confirmed by a clerk.",
                                      {"invoice_description": ln.description, "po_description": p.description,
                                       "po_line_id": p.id, "confirmed": True}, ln.line_no))
            if ln.gst_rate != p.gst_rate and not doc.foreign:
                reasons.append(Reason("TAX_MISMATCH", Severity.FLAG,
                                      f"Line {ln.line_no}: GST {_n(ln.gst_rate)}% differs from the PO rate {_n(p.gst_rate)}%.",
                                      {"invoice_rate": str(ln.gst_rate), "po_rate": str(p.gst_rate)}, ln.line_no))
            reasons += _price_check(ln, p, qty, price, tol, ccy)
            if po.is_service:
                net = replace(ln, taxable_value=(ln.taxable_value - ln.credited_value) * fx)
                reasons += _service_check(net, p, tol, ccy)
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
                inv_uom, ln.qty, ccy,
            ))

    if any(r.severity == Severity.BLOCK for r in reasons):
        decision = Decision.BLOCK
    elif any(r.severity == Severity.FLAG for r in reasons):
        decision = Decision.FLAG
    else:
        decision = Decision.APPROVE
    return MatchOutcome(decision, tuple(reasons), tuple(matrix), line_map, ENGINE_VERSION, tol.version)
