"""Plain-language explanation of a decision, written from the reason codes only (spec C3 "Explain").

Inputs are the decision, the invoice status and the stored reason codes (code, severity, the
engine's own sentence with evidence values, line). Nothing else: no document text, no AI output,
no vendor master. The explanation can therefore never contradict or change the decision; the
rules engine decided, this only says it in plain words, why it matters and who acts next.

The team runs Duly with AI offline, so explanations come from these reviewed templates. A live
model could be asked to rephrase the same facts; it would get exactly these inputs and nothing more.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.engine.catalog import info

# code -> (why it matters, how it gets fixed, who acts)
GUIDE: dict[str, tuple[str, str, str]] = {
    "NO_PO": ("Plant X pays only against an approved purchase order (\"No PO, no pay\"); without one nobody agreed to buy this.",
              "The supplier re-sends the invoice quoting the right PO, or the buyer raises a PO first.", "supplier"),
    "PO_CLOSED": ("The purchase order is closed, so nothing more may be billed against it.",
                  "The buyer reopens or replaces the PO, or the supplier bills the correct PO.", "buyer"),
    "SUPPLIER_MISMATCH": ("The company billing us is not the company we ordered from. This is a classic fraud pattern.",
                          "Check the PO number with the supplier; never pay a different company than the PO names.", "clerk"),
    "BILL_TO_MISMATCH": ("The invoice is addressed to another GSTIN, so Plant X could not claim the GST input credit.",
                         "The supplier sends a corrected invoice billed to Plant X.", "supplier"),
    "CURRENCY_MISMATCH": ("The invoice currency differs from the PO, so the amounts cannot be compared.",
                          "The supplier re-bills in the PO currency, or the buyer amends the PO.", "supplier"),
    "PAYMENT_TERMS_MISMATCH": ("The supplier's terms differ from the PO; paying on their terms could mean paying early.",
                               "The clerk checks the terms; Duly pays on the PO terms unless finance agrees otherwise.", "clerk"),
    "LINE_NOT_ON_PO": ("Something was billed that was never ordered.",
                       "The supplier removes the line (credit note or corrected invoice), or the buyer adds it to the PO.", "supplier"),
    "NO_LINES": ("No item lines could be read, so nothing can be checked against the PO.",
                 "The clerk enters the lines from the document, or the supplier sends a clearer copy.", "clerk"),
    "PRICE_VARIANCE": ("The unit price is higher than the agreed PO price, beyond the allowed tolerance (SAP key PP).",
                       "The supplier sends a credit note for the difference, or the buyer confirms the new price and a clerk "
                       "overrides the flag with a written reason (needs two approvers).", "supplier"),
    "QTY_EXCEEDS_GR": ("More is billed than Plant X has received, counting earlier invoices (SAP key DQ). Paying it would pay "
                       "for goods we do not have.", "The supplier delivers the rest (stores posts a receipt) or enters a credit "
                       "note for the excess; Duly then re-checks automatically.", "supplier"),
    "MISSING_GR": ("The goods have not been received yet. Plant X never pays for goods it has not received.",
                   "Stores posts the goods receipt when the goods arrive; Duly re-checks and releases the invoice by itself.",
                   "stores"),
    "MISSING_SES": ("Nobody has confirmed the service was done yet.",
                    "The person who ordered the service records a service entry sheet; Duly re-checks automatically.", "stores"),
    "SES_VALUE_EXCEEDED": ("More is billed than the value of services accepted.",
                           "The supplier enters a credit note for the excess, or more work is accepted first.", "supplier"),
    "TAX_MISMATCH": ("The GST is not what the law requires for this supply (rate or CGST/SGST vs IGST). Wrong GST can cost "
                     "Plant X its input credit.", "The supplier sends a corrected invoice.", "supplier"),
    "MATH_ERROR": ("The amounts on the invoice do not add up.",
                   "The clerk checks the document; if the supplier's arithmetic is wrong, they send a corrected invoice.", "clerk"),
    "GSTIN_INVALID": ("The supplier's GSTIN fails the government check digit, so it is not a valid registration.",
                      "The supplier corrects the GSTIN; if it was misread, the clerk corrects the field.", "supplier"),
    "INVOICE_NO_INVALID": ("GST rules limit invoice numbers to 16 characters of a set format.",
                           "The supplier issues the invoice with a valid number.", "supplier"),
    "DATE_INVALID": ("The invoice date is in the future or too old to accept.",
                     "The supplier sends the invoice with the correct date.", "supplier"),
    "INJECTION_ATTEMPT": ("The document hides text that tries to instruct an AI (for example to approve it). It changed nothing: "
                          "the rules engine decides, and any AI reading was quarantined.",
                          "The clerk looks at the hidden text and the supplier is asked why it is there.", "clerk"),
    "QR_MISMATCH": ("The printed invoice does not match the government-signed e-invoice QR: the PDF was edited after signing.",
                    "Do not pay. The supplier must send the genuine e-invoice; treat it as possible fraud.", "clerk"),
    "QR_SIGNATURE_INVALID": ("The e-invoice QR is not signed by the government portal, so it is not genuine.",
                             "Do not pay; ask the supplier for the genuine e-invoice.", "clerk"),
    "EINVOICE_QR_MISSING": ("This supplier must issue e-invoices, but no signed QR was found.",
                            "The supplier sends the e-invoice with its signed QR.", "supplier"),
    "DUPLICATE": ("This invoice was already received (same number, IRN or file). Paying it would pay twice.",
                  "Nothing to fix: the original is processed; this copy should be rejected.", "clerk"),
    "POSSIBLE_DUPLICATE": ("It looks very like an earlier invoice (same supplier, amount, items, dates).",
                           "The clerk compares the two side by side and confirms whether it is a separate supply.", "clerk"),
    "BANK_ACCOUNT_SHARED": ("The same bank account is on file for another supplier, which can mean a fake supplier.",
                            "Finance checks both vendor records before any payment.", "clerk"),
    "BANK_MISMATCH": ("The bank account printed on the invoice is not the verified one on file. This is how payment-diversion "
                      "(BEC) fraud works.", "Duly pays only the verified account. A genuine change goes through a bank change "
                      "request with a call-back, a 72 h cooling period and a second approver.", "clerk"),
    "LINE_MAPPED": ("The item code does not match the PO, so Duly matched the line by its description. That is only a "
                    "suggestion: paying on a wrong match would pay for the wrong item.",
                    "The clerk confirms the match (or picks the right PO line), or marks the line as not on the PO.", "clerk"),
    "EMAIL_SENDER_UNVERIFIED": ("The invoice came from an email address not on the vendor master (possibly a lookalike domain).",
                                "The clerk calls the supplier on the number on file before anything is paid.", "clerk"),
    "ERS_PO_INVOICE": ("This PO is settled automatically from receipts (ERS), so a supplier invoice risks paying twice.",
                       "The clerk checks it against the ERS settlements and rejects any trip already settled.", "clerk"),
}
# Blocks that no correction can release: the document itself must not be paid.
DO_NOT_PAY = {"DUPLICATE", "QR_MISMATCH", "QR_SIGNATURE_INVALID"}
WHO = {"supplier": "Supplier", "clerk": "AP clerk", "stores": "Plant X stores", "buyer": "Buyer"}


@dataclass(frozen=True)
class ReasonFact:
    code: str
    severity: str  # block | flag | info
    message: str
    line_no: int | None = None


@dataclass
class Point:
    code: str
    title: str
    severity: str
    what: str
    why: str
    fix: str
    who: str


@dataclass
class Explanation:
    decision: str
    headline: str
    points: list[Point] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    next_step: str = ""
    footer: str = ""
    source: str = "template"
    inputs: list[str] = field(default_factory=list)


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def explain(decision: str, status: str, reasons: list[ReasonFact], engine_version: str = "", policy_version: int | None = None) -> Explanation:
    blocks = [r for r in reasons if r.severity == "block"]
    flags = [r for r in reasons if r.severity == "flag"]
    infos = [r for r in reasons if r.severity == "info"]
    if decision == "BLOCK":
        headline = (f"Blocked: this invoice cannot be paid until {_count(len(blocks), 'problem')} "
                    f"{'is' if len(blocks) == 1 else 'are'} fixed. Nobody can override a block.")
    elif decision == "FLAG":
        headline = (f"Flagged: {_count(len(flags), 'point')} need{'s' if len(flags) == 1 else ''} a person to look before "
                    "it can be approved.")
    else:
        headline = "Approved by the checks: the invoice matches the PO and what was received, within tolerance."
    out = Explanation(decision, headline)
    seen = set()
    for r in blocks + flags:
        if (r.code, r.line_no) in seen:
            continue
        seen.add((r.code, r.line_no))
        why, fix, who = GUIDE.get(r.code, ("This does not meet a Plant X invoice rule.",
                                           "The AP clerk reviews it.", "clerk"))
        title = info(r.code).title + (f" (line {r.line_no})" if r.line_no else "")
        out.points.append(Point(r.code, title, r.severity, r.message, why, fix, WHO[who]))
    out.notes = [f"{info(r.code).title}: {r.message}" for r in infos]

    if status == "needs_review":
        out.next_step = "First a clerk confirms the fields that were hard to read; the checks then run again."
    elif decision == "BLOCK" and all(p.code in DO_NOT_PAY for p in out.points if p.severity == "block"):
        out.next_step = ("Do not pay this document: there is nothing the supplier can correct on it. The AP clerk confirms "
                         "and rejects it; any genuine claim comes as a new, valid invoice.")
    elif decision == "BLOCK":
        actors = sorted({p.who for p in out.points if p.severity == "block"})
        out.next_step = (f"Waiting for: {', '.join(actors)}. When the cause is fixed (receipt posted, credit note, corrected "
                         "invoice), Duly re-runs the checks automatically; no one needs to remember it.")
    elif decision == "FLAG":
        out.next_step = ("The AP clerk reviews the flagged points. If they are acceptable, the clerk can override with a written "
                         "justification, and the invoice then needs two approval levels.")
    elif status == "paid":
        out.next_step = "Paid. The payment and its UTR are visible to the supplier."
    elif status == "approved":
        out.next_step = "Approved. It will be paid in a payment run on its due date (MSME suppliers first)."
    else:
        out.next_step = ("It goes to the approvers set by the delegation of authority for its value; small clean invoices are "
                         "approved by policy P-01 without a person.")
    version = f" (engine {engine_version}, policy v{policy_version})" if engine_version else ""
    out.footer = (f"Written from the {_count(len(reasons), 'reason code')} of the latest check only. The rules engine made "
                  f"the decision{version}; this explanation cannot change it, and AI took no part in either.")
    out.inputs = sorted({r.code for r in reasons})
    return out
