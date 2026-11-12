"""Reason-code catalog: title, SAP-style payment block and the SAP transaction a human uses today.

Used by the UI (chips, tooltips) and by docs/DECISION_ENGINE.md. Severity is decided by
the rules at run time (several codes can flag or block depending on tolerance).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodeInfo:
    title: str
    sap_block: str  # SAP-style payment block shown in the UI
    sap_tcode: str  # where a human would look in SAP today


_R = "Payment block R: invoice verification"
_A = "Payment block A: blocked for payment"

CATALOG: dict[str, CodeInfo] = {
    "NO_PO": CodeInfo("No PO, no pay", _A, "ME23N display PO"),
    "PO_CLOSED": CodeInfo("PO is closed", _A, "ME23N display PO"),
    "SUPPLIER_MISMATCH": CodeInfo("Supplier does not match the PO", _A, "ME23N / XK03 vendor"),
    "BILL_TO_MISMATCH": CodeInfo("Not billed to Plant X", _A, "MIRO header"),
    "CURRENCY_MISMATCH": CodeInfo("Currency differs from the PO", _A, "ME23N / MIRO"),
    "PAYMENT_TERMS_MISMATCH": CodeInfo("Payment terms differ", _R, "ME23N terms / XK03"),
    "LINE_NOT_ON_PO": CodeInfo("Invoice line not on the PO", _R, "ME23N items"),
    "NO_LINES": CodeInfo("No line items read", _R, "MIRO items"),
    "PRICE_VARIANCE": CodeInfo("Price differs from the PO", _R + " (tolerance key PP)", "MIRO price variance"),
    "QTY_EXCEEDS_GR": CodeInfo("Billed more than received", _R + " (tolerance key DQ)", "MIGO GR history / MIRO"),
    "MISSING_GR": CodeInfo("No goods receipt yet", _R, "MIGO movement type 101"),
    "MISSING_SES": CodeInfo("No service entry sheet", _R, "ML81N service entry"),
    "SES_VALUE_EXCEEDED": CodeInfo("Billed more than accepted services", _R, "ML81N / MIRO"),
    "LINE_MAPPED": CodeInfo("Line matched by description", _R + " until a clerk confirms", "ME23N items"),
    "UOM_CONVERTED": CodeInfo("Unit of measure converted", "None (information)", "MIRO quantity in order unit"),
    "SMALL_DIFFERENCE": CodeInfo("Small difference auto-accepted", "None (tolerance key BD)", "MIRO small differences"),
    "TAX_MISMATCH": CodeInfo("GST does not match the rules", _R, "MIRO tax / J1IG"),
    "MATH_ERROR": CodeInfo("Arithmetic does not add up", _R, "MIRO balance"),
    "GSTIN_INVALID": CodeInfo("Supplier GSTIN invalid", _A, "XK03 tax numbers"),
    "INVOICE_NO_INVALID": CodeInfo("Invoice number format", _R, "MIRO reference"),
    "DATE_INVALID": CodeInfo("Invoice date not acceptable", _R, "MIRO invoice date"),
    "INJECTION_ATTEMPT": CodeInfo("Hidden instructions in the document", _R, "None (Duly control)"),
    "QR_MISMATCH": CodeInfo("Printed invoice differs from signed e-invoice", _A, "J1IG e-invoice / IRP portal"),
    "QR_SIGNATURE_INVALID": CodeInfo("e-invoice QR not signed by the IRP", _A, "J1IG e-invoice / IRP portal"),
    "EINVOICE_QR_MISSING": CodeInfo("Signed e-invoice QR missing", _R, "J1IG e-invoice"),
    "EINVOICE_VERIFIED": CodeInfo("Signed e-invoice verified", "None (information)", "J1IG e-invoice"),
    "EINVOICE_NOT_APPLICABLE": CodeInfo("e-invoice not applicable", "None (information)", "J1IG e-invoice"),
    "DUPLICATE": CodeInfo("Duplicate invoice", _A, "MIRO duplicate invoice check (message M8108)"),
    "POSSIBLE_DUPLICATE": CodeInfo("Possible duplicate", _R, "MIRO duplicate invoice check"),
    "BANK_ACCOUNT_SHARED": CodeInfo("Bank account used by another supplier", _A, "XK03 bank details / FBL1N"),
    "BANK_MISMATCH": CodeInfo("Bank details differ from vendor master", _A, "XK03 bank details"),
    "ERS_SETTLEMENT": CodeInfo("Self-billed from the receipt (ERS)", "None (information)", "MRRL evaluated receipt settlement"),
    "EMAIL_RECEIVED": CodeInfo("Received by email from a registered address", "None (information)", "VIM / inbound channel"),
    "EMAIL_SENDER_UNVERIFIED": CodeInfo("Emailed from an address not on the vendor master", _R, "XK03 vendor email / call-back"),
    "CREDIT_NOTE_APPLIED": CodeInfo("Credit note applied", "None (information)", "MIRO credit memo / FB60"),
    "ERS_PO_INVOICE": CodeInfo("Supplier invoice on an ERS purchase order", _R, "MRRL / ME23N ERS indicator"),
}


def info(code: str) -> CodeInfo:
    return CATALOG.get(code, CodeInfo(code.replace("_", " ").title(), _R, "MIRO"))
