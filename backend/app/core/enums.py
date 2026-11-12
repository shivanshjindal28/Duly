"""String enums shared by models, API schemas and the decision engine."""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    SUPPLIER = "supplier"
    CLERK = "clerk"
    APPROVER = "approver"
    STORES = "stores"
    AUDITOR = "auditor"
    ADMIN = "admin"


class MsmeCategory(StrEnum):
    NONE = "none"
    MICRO = "micro"
    SMALL = "small"
    MEDIUM = "medium"


class EnterpriseType(StrEnum):
    MANUFACTURER = "manufacturer"
    SERVICES = "services"
    TRADER = "trader"


class InvoiceStatus(StrEnum):
    RECEIVED = "received"
    NEEDS_REVIEW = "needs_review"
    FLAGGED = "flagged"
    BLOCKED = "blocked"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


class Decision(StrEnum):
    APPROVE = "APPROVE"
    FLAG = "FLAG"
    BLOCK = "BLOCK"


class Severity(StrEnum):
    INFO = "info"
    FLAG = "flag"
    BLOCK = "block"


class StepStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class BankChangeStatus(StrEnum):
    REQUESTED = "requested"  # by the supplier
    PROPOSED = "proposed"
    COOLING = "cooling"
    APPROVED = "approved"
    REJECTED = "rejected"
