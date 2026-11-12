"""The only things the payment assistant can look up. Every tool takes the supplier id from
the server session (or the clerk's chosen supplier); it is never a tool parameter, so neither
the model nor the user can point a tool at another supplier's data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.api.portal import PortalInvoice, PortalOut, build_portal
from app.chat.i18n import exists, t
from app.ingestion.pipeline import normalise_invoice_number
from app.models import Invoice

# Tool definitions for Claude (strict schemas; no supplier id anywhere).
_REF = {"type": "string", "description": "Invoice number (any formatting) or a word for an item on it, e.g. 'bearings'."}
TOOL_SPECS = [
    {"name": "list_my_invoices", "description": "List this supplier's invoices with their current stage.",
     "input_schema": {"type": "object", "properties": {"only_open": {"type": "boolean"}},
                      "required": ["only_open"], "additionalProperties": False}},
    {"name": "get_invoice_status", "description": "Where one invoice is, its expected payment date, and its timeline.",
     "input_schema": {"type": "object", "properties": {"invoice": _REF}, "required": ["invoice"],
                      "additionalProperties": False}},
    {"name": "get_payment_schedule", "description": "Upcoming expected payments and payments already made (with UTR).",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_block_reason", "description": "Why an invoice is on hold and what the supplier needs to do.",
     "input_schema": {"type": "object", "properties": {"invoice": _REF}, "required": ["invoice"],
                      "additionalProperties": False}},
    {"name": "get_msme_due_date", "description": "The statutory MSME payment due date for an invoice, and days left.",
     "input_schema": {"type": "object", "properties": {"invoice": _REF}, "required": ["invoice"],
                      "additionalProperties": False}},
]
for _spec in TOOL_SPECS:
    _spec["strict"] = True


@dataclass
class ToolCall:
    name: str
    ref: str | None
    result: dict


def _inr(v) -> str:
    from decimal import Decimal

    d = Decimal(str(v)).quantize(Decimal("0.01"))
    whole, frac = f"{d:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join(([head] if head else []) + parts + [tail])
    return f"₹{whole}.{frac}"


def _date(d) -> str | None:
    return d.strftime("%d %b %Y") if d else None


def _todo_text(lang: str, code: str, params: dict) -> str:
    params = {k: (_inr(v)[1:] if k in ("credit", "po_price") else v) for k, v in params.items()}
    return t(lang, f"todo.{code}", **params) if exists(lang, f"todo.{code}") else t(lang, "todo.default", code=code)


def resolve(db: Session, portal: PortalOut, ref: str | None) -> tuple[PortalInvoice | None, list[PortalInvoice]]:
    """Find the supplier's own invoice by number (any formatting) or by an item word. Returns
    (match, candidates): one match, or several candidates to ask about."""
    invoices = portal.invoices
    if not ref or not invoices:
        return None, []
    norm = normalise_invoice_number(ref)
    exact = [i for i in invoices if i.invoice_number.upper() == ref.strip().upper()
             or (len(norm) >= 2 and normalise_invoice_number(i.invoice_number) == norm)]
    if exact:
        # "INV/0042" and its blocked copy "INV-42" normalise alike: the literal number wins, then the original.
        exact.sort(key=lambda i: (i.invoice_number.upper() != ref.strip().upper(),
                                  any(x.code == "DUPLICATE" for x in i.todos)))
        return exact[0], []
    words = [w for w in re.findall(r"[A-Za-z]{3,}", ref.lower()) if w not in {"invoice", "the", "for", "bill", "my"}]
    scored = []
    for inv in invoices:
        row = db.get(Invoice, inv.id)
        text = " ".join(f"{ln.item_code or ''} {ln.description}" for ln in row.lines).lower()
        best = max((fuzz.partial_ratio(w.rstrip("s"), text) for w in words), default=0)
        if best >= 80:
            scored.append((best, inv))
    if not scored:
        return None, []
    scored.sort(key=lambda x: (-x[0], x[1].status in ("paid", "rejected")))
    top = [inv for s, inv in scored if s == scored[0][0]]
    genuine = [i for i in top if not any(x.code == "DUPLICATE" for x in i.todos)]
    top = genuine or top  # a blocked duplicate is not the invoice the supplier means
    open_top = [i for i in top if i.status not in ("paid", "rejected")]
    if len(open_top) == 1 or len(top) == 1:
        return (open_top or top)[0], []
    # Several: ask about the open ones (a supplier asking "when" means an unpaid invoice), newest five.
    return None, sorted(open_top or top, key=lambda i: -i.id)[:5]


def _status_payload(lang: str, inv: PortalInvoice, portal: PortalOut) -> dict:
    paid = next((p for p in portal.payments if p.invoice_number == inv.invoice_number), None)
    return {
        "invoice_number": inv.invoice_number, "amount": _inr(inv.total), "status": inv.status,
        "stage": t(lang, inv.stage), "expected_payment": _date(inv.expected_payment),
        "msme_due_date": _date(inv.msme_due_date),
        "msme_days_left": inv.msme_days_left,
        "you_need_to": [_todo_text(lang, x.code, x.params) for x in inv.todos if x.you_act],
        "plant_x_is": [_todo_text(lang, x.code, x.params) for x in inv.todos if not x.you_act],
        "paid": {"date": _date(paid.paid_at), "net": _inr(paid.net), "tds": _inr(paid.tds), "utr": paid.utr} if paid else None,
    }


def run_tool(db: Session, supplier_id: int, name: str, args: dict, lang: str) -> ToolCall:
    """Execute one tool for `supplier_id` (from the session, never from the model)."""
    portal = build_portal(db, supplier_id)
    ref = args.get("invoice")
    if name == "list_my_invoices":
        items = [i for i in portal.invoices if not args.get("only_open") or i.status not in ("paid", "rejected")]
        return ToolCall(name, None, {"invoices": [{"invoice_number": i.invoice_number, "amount": _inr(i.total),
                                                    "stage": t(lang, i.stage)} for i in items]})
    if name == "get_payment_schedule":
        upcoming = [{"invoice_number": i.invoice_number, "amount": _inr(i.total), "expected_payment": _date(i.expected_payment)}
                    for i in portal.invoices if i.expected_payment and i.status not in ("paid", "rejected")]
        paid = [{"invoice_number": p.invoice_number, "date": _date(p.paid_at), "net": _inr(p.net), "utr": p.utr}
                for p in portal.payments]
        return ToolCall(name, None, {"upcoming": upcoming, "paid": paid})
    if name in ("get_invoice_status", "get_block_reason", "get_msme_due_date"):
        inv, candidates = resolve(db, portal, ref)
        if inv is None:
            return ToolCall(name, ref, {"error": "not_found" if not candidates else "ambiguous",
                                        "candidates": [c.invoice_number for c in candidates],
                                        "example": portal.invoices[0].invoice_number if portal.invoices else "INV-001"})
        payload = _status_payload(lang, inv, portal)
        payload["msme_eligible"] = portal.msme_eligible
        payload["payment_terms_days"] = portal.payment_terms_days
        return ToolCall(name, inv.invoice_number, payload)
    return ToolCall(name, ref, {"error": "unknown_tool"})
