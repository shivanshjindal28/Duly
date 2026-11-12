"""Offline payment assistant: a keyword intent matcher over the same tools the AI uses, with
answers composed from the reviewed en/hi templates. Works with no network and no API key."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.chat.i18n import t
from app.chat.tools import ToolCall, run_tool

# (intent, keywords in English, Hindi and Hinglish). Order matters: first match wins.
INTENTS = [
    ("get_block_reason", r"why|hold|block|stuck|problem|issue|reject|क्यों|रुका|रोका|अटका|kyu|kyon"),
    ("get_msme_due_date", r"msme|45[ -]?day|due date|deadline|देय|उद्यम"),
    ("get_payment_schedule", r"\butr\b|payments? (made|received|history)|paid so far|upcoming|schedule|कितना भुगतान|भुगतान इतिहास"),
    ("get_invoice_status", r"when|paid|pay(ment)?|status|where|kab|कब|कहाँ|कहां|स्थिति|भुगतान"),
    ("list_my_invoices", r"(my|all|list).*(invoices|bills)|invoices|बिल|इनवॉइस"),
]
_NUMBER = re.compile(r"\b[A-Z]{2,5}[/\-]?[A-Z0-9/\-]*\d[A-Z0-9/\-]*\b|\b\d{3,}\b", re.IGNORECASE)
_ITEM_WORDS = re.compile(r"[A-Za-z]{4,}")
_STOP = {"when", "will", "paid", "payment", "invoice", "where", "status", "what", "why", "hold", "blocked",
         "please", "tell", "about", "money", "get", "for", "the", "msme", "date", "show", "list", "all", "with"}


def detect(message: str) -> str | None:
    low = message.lower()
    for intent, pattern in INTENTS:
        if re.search(pattern, low):
            return intent
    return None


def invoice_ref(message: str) -> str | None:
    m = _NUMBER.search(message)
    if m:
        return m.group()
    words = [w for w in _ITEM_WORDS.findall(message) if w.lower() not in _STOP]
    return " ".join(words) or None


def compose(lang: str, call: ToolCall) -> str:
    r = call.result
    if r.get("error") == "not_found":
        return t(lang, "chat.not_found", ref=call.ref or "", example=r.get("example", ""))
    if r.get("error") == "ambiguous":
        return t(lang, "chat.ask_which", options=", ".join(r["candidates"]))
    if call.name == "list_my_invoices":
        if not r["invoices"]:
            return t(lang, "chat.no_invoices")
        items = "\n".join("• " + t(lang, "chat.list_item", number=i["invoice_number"], amount=i["amount"], stage=i["stage"])
                          for i in r["invoices"])
        return t(lang, "chat.list_intro", count=len(r["invoices"])) + "\n" + items
    if call.name == "get_payment_schedule":
        parts = []
        if r["upcoming"]:
            parts.append(t(lang, "chat.upcoming_intro") + "\n" + "\n".join(
                f"• {u['invoice_number']} ({u['amount']}): {u['expected_payment']}" for u in r["upcoming"]))
        if r["paid"]:
            parts.append(t(lang, "chat.payments_intro") + "\n" + "\n".join(
                f"• {p['invoice_number']}: {p['net']} on {p['date']}, UTR {p['utr']}" for p in r["paid"]))
        return "\n\n".join(parts) or t(lang, "chat.no_payments")
    status = t(lang, "chat.status_line", number=r["invoice_number"], amount=r["amount"], stage=r["stage"])
    if call.name == "get_block_reason":
        reasons = r["you_need_to"] + r["plant_x_is"]
        if not reasons:
            return status + " " + t(lang, "chat.nothing_blocking", number=r["invoice_number"])
        return status + "\n" + t(lang, "chat.on_hold_intro") + "\n" + "\n".join("• " + x for x in reasons)
    if call.name == "get_msme_due_date":
        if not r["msme_eligible"]:
            return t(lang, "chat.msme_not_eligible", days=r["payment_terms_days"])
        if r["msme_due_date"] is None:
            return t(lang, "chat.msme_none", number=r["invoice_number"])
        days = r["msme_days_left"]
        if days is not None and days < 0:
            return t(lang, "chat.msme_overdue", date=r["msme_due_date"], days=-days)
        return status + " " + t(lang, "chat.msme_line", date=r["msme_due_date"], days=days)
    # get_invoice_status
    if r["paid"]:
        p = r["paid"]
        return status + " " + t(lang, "chat.paid_line", date=p["date"], net=p["net"], tds=p["tds"], utr=p["utr"])
    if r["expected_payment"]:
        extra = t(lang, "chat.expected", date=r["expected_payment"])
    elif r["status"] in ("blocked", "flagged"):
        extra = t(lang, "chat.expected_after_fix")
    else:
        extra = t(lang, "chat.expected_after_approval")
    tail = ("\n" + t(lang, "chat.on_hold_intro") + "\n" + "\n".join("• " + x for x in r["you_need_to"])) \
        if r["you_need_to"] else ""
    return f"{status} {extra}{tail}"


def answer(db: Session, supplier_id: int, message: str, lang: str) -> tuple[str, list[ToolCall]]:
    intent = detect(message)
    if intent is None and _NUMBER.fullmatch(message.strip().rstrip("?.!")):
        intent = "get_invoice_status"  # just an invoice number (e.g. the reply to "which invoice?")
    if intent is None:
        return t(lang, "chat.help"), []
    args = {"only_open": False} if intent == "list_my_invoices" else {}
    if intent in ("get_invoice_status", "get_block_reason", "get_msme_due_date"):
        ref = invoice_ref(message)
        if ref is None:
            call = run_tool(db, supplier_id, "list_my_invoices", {"only_open": True}, lang)
            return compose(lang, call), [call]
        args = {"invoice": ref}
    call = run_tool(db, supplier_id, intent, args, lang)
    return compose(lang, call), [call]
