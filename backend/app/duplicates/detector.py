"""Duplicate-invoice detection (spec B1). Pure functions: no I/O.

Five layered signals between a new invoice and every earlier one:
  1. exact_number   same supplier GSTIN + same normalised invoice number + same financial year
                    (GST requires invoice numbers to be unique per FY); "INV/0042" == "INV-42"
  2. same_irn       same e-invoice IRN
  3. same_file      same file SHA-256 (the very same file uploaded again)
  4. near_match     same supplier, total within 0.5%, invoice date within 30 days, and the same
                    items and quantities (Jaccard similarity >= 0.8)
  5. visual         perceptual hash (pHash) of page 1 within a small Hamming distance
                    (the same paper invoice scanned again or photographed)
Plus a fraud signal: the same bank account printed on invoices of two different suppliers.

Any of 1-3 -> BLOCK DUPLICATE. Otherwise a combined probability >= 0.6 -> FLAG POSSIBLE_DUPLICATE.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.enums import Severity
from app.engine.types import Reason

NEAR_TOTAL_PCT = Decimal("0.5")
NEAR_DAYS = 30
NEAR_JACCARD = 0.8
PHASH_MAX_DISTANCE = 10
POSSIBLE_THRESHOLD = 0.6
VISUAL_WEIGHT = 0.35  # < POSSIBLE_THRESHOLD on purpose
EXACT = ("exact_number", "same_irn", "same_file")


@dataclass(frozen=True)
class DupView:
    invoice_id: int
    invoice_number: str
    number_norm: str
    supplier_id: int | None
    supplier_gstin: str | None
    fiscal_year: str | None
    irn: str | None
    sha256: str | None
    phash: str | None
    total: Decimal
    invoice_date: date | None
    lines: tuple[tuple[str, Decimal], ...] = ()  # (item code, qty)
    bank_account: str | None = None
    status: str = ""


@dataclass
class Signal:
    name: str
    score: float  # 0..1
    detail: str


@dataclass
class Match:
    invoice_id: int
    invoice_number: str
    probability: float
    signals: list[Signal] = field(default_factory=list)

    @property
    def exact(self) -> bool:
        return any(s.name in EXACT for s in self.signals)


def phash_distance(a: str | None, b: str | None) -> int | None:
    if not a or not b or len(a) != len(b):
        return None
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def jaccard(a: tuple[tuple[str, Decimal], ...], b: tuple[tuple[str, Decimal], ...]) -> float:
    sa = {(c.upper(), q.normalize()) for c, q in a}
    sb = {(c.upper(), q.normalize()) for c, q in b}
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def compare(new: DupView, old: DupView) -> Match | None:
    sig: list[Signal] = []
    same_supplier = bool(new.supplier_gstin) and new.supplier_gstin == old.supplier_gstin \
        or (new.supplier_id is not None and new.supplier_id == old.supplier_id)
    if same_supplier and new.number_norm and new.number_norm == old.number_norm and new.fiscal_year == old.fiscal_year:
        same_text = new.invoice_number == old.invoice_number
        sig.append(Signal("exact_number", 1.0, f"Invoice number {new.invoice_number!r} "
                          f"{'is identical to' if same_text else 'normalises to the same number as'} "
                          f"{old.invoice_number!r} (FY {new.fiscal_year})"))
    if new.irn and new.irn == old.irn:
        sig.append(Signal("same_irn", 1.0, "Same e-invoice IRN"))
    if new.sha256 and new.sha256 == old.sha256:
        sig.append(Signal("same_file", 1.0, "The same file was uploaded before (identical SHA-256)"))
    if same_supplier and old.total and new.invoice_date and old.invoice_date:
        diff_pct = abs(new.total - old.total) / old.total * 100
        days = abs((new.invoice_date - old.invoice_date).days)
        j = jaccard(new.lines, old.lines)
        if diff_pct <= NEAR_TOTAL_PCT and days <= NEAR_DAYS and j >= NEAR_JACCARD:
            sig.append(Signal("near_match", round(0.75 * j, 2), f"Total within {diff_pct:.2f}%, "
                              f"{'same date' if days == 0 else 'dated 1 day apart' if days == 1 else f'dated {days} days apart'}, "
                              f"{round(j * 100)}% of items and quantities identical"))
    d = phash_distance(new.phash, old.phash)
    if same_supplier and d is not None and d <= PHASH_MAX_DISTANCE:
        # Corroboration only: invoices printed from one supplier template look alike to pHash
        # (measured: a different invoice on the same template scores ~2, a phone photo of the same
        # invoice ~8), so this signal alone can never reach the POSSIBLE_DUPLICATE threshold.
        sig.append(Signal("visual", VISUAL_WEIGHT, f"Page 1 looks very similar (perceptual hash distance {d}/64)"))
    if not sig:
        return None
    p = 1.0
    for s in sig:
        p *= 1 - s.score
    return Match(old.invoice_id, old.invoice_number, round(1 - p, 3), sig)


def assess(new: DupView, earlier: list[DupView]) -> tuple[list[Match], list[Reason]]:
    """Compare against earlier invoices; return matches (best first) and reasons for the engine."""
    matches = sorted((m for m in (compare(new, o) for o in earlier) if m), key=lambda m: (-m.exact, -m.probability))
    reasons: list[Reason] = []
    if matches:
        best = matches[0]
        ev = {"duplicate_of_invoice_id": best.invoice_id, "duplicate_of": best.invoice_number,
              "probability": best.probability, "signals": [s.name for s in best.signals]}
        detail = "; ".join(s.detail for s in best.signals)
        if best.exact:
            reasons.append(Reason("DUPLICATE", Severity.BLOCK,
                                  f"Duplicate of invoice {best.invoice_number}: {detail}.", ev))
        elif best.probability >= POSSIBLE_THRESHOLD:
            reasons.append(Reason("POSSIBLE_DUPLICATE", Severity.FLAG,
                                  f"Probably the same as invoice {best.invoice_number} "
                                  f"({round(best.probability * 100)}% likely): {detail}.", ev))
    if new.bank_account:
        others = {o.supplier_id for o in earlier
                  if o.bank_account == new.bank_account and o.supplier_id not in (None, new.supplier_id)}
        if others:
            reasons.append(Reason("BANK_ACCOUNT_SHARED", Severity.FLAG,
                                  f"The bank account on this invoice (XXXXXX{new.bank_account[-4:]}) also appears on "
                                  f"invoices of {len(others)} other supplier(s). Possible fraud: verify before paying.",
                                  {"account": f"XXXXXX{new.bank_account[-4:]}", "other_suppliers": len(others)}))
    return matches, reasons
