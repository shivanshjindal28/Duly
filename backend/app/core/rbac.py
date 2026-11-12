"""Human-readable role permissions (spec section 4). Shown on each user's Overview page.

Enforcement lives in the API dependencies (`require_roles`, `get_scope`) and, for
segregation of duties, in the workflow layer. This table documents what they enforce.
"""
from __future__ import annotations

from app.core.enums import Role

PERMISSIONS: dict[Role, dict[str, list[str]]] = {
    Role.SUPPLIER: {
        "can": [
            "Upload invoices and credit notes",
            "See only your own invoices and payments",
            "See block reasons in plain language",
            "Request a bank detail change",
            "Use the payment chatbot, in English or Hindi",
        ],
        "cannot": ["See any other supplier's data", "Approve anything"],
    },
    Role.CLERK: {
        "can": [
            "Work the invoice queue and review extractions",
            "Correct extracted fields (every correction is logged)",
            "Resolve exceptions and route invoices for approval",
            "Request goods receipts or service entry sheets from stores",
            "Run duplicate checks",
        ],
        "cannot": ["Approve invoices you processed", "Edit vendor master bank details"],
    },
    Role.APPROVER: {
        "can": [
            "Approve or reject invoices within your threshold",
            "Add comments, send back to the clerk, request information",
            "Delegate approvals while away (time-boxed, logged)",
        ],
        "cannot": ["Approve above your limit", "Approve invoices for POs you created", "Override a BLOCK"],
    },
    Role.STORES: {
        "can": ["Post goods receipts against POs", "Post service entry sheets for services"],
        "cannot": ["View or change invoices"],
    },
    Role.AUDITOR: {
        "can": [
            "Read all data",
            "Generate the controls report",
            "Verify the audit chain",
            "Export evidence",
        ],
        "cannot": ["Change anything"],
    },
    Role.ADMIN: {
        "can": [
            "Manage users and roles",
            "Edit the approval matrix and tolerance profiles (versioned)",
            "Use demo controls (reset, clock)",
        ],
        "cannot": ["Approve invoices (segregation of duties)"],
    },
}
