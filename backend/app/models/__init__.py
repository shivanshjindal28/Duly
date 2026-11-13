"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""
from app.models.invoice import CreditNote, CreditNoteLine, Document, ExtractionResult, Invoice, InvoiceLine, MatchResult, ReasonCode
from app.models.org import Organisation, Supplier, User
from app.models.procurement import GoodsReceipt, GRLine, ItemUnit, POLine, PurchaseOrder, ServiceEntrySheet
from app.models.workflow import (AppSetting, ApprovalStep, AuditEvent, BankChangeRequest, ChatSession, Delegation,
                                 InboundEmail, Payment, Policy)

__all__ = [
    "AppSetting",
    "ApprovalStep",
    "AuditEvent",
    "BankChangeRequest",
    "ChatSession",
    "CreditNote",
    "CreditNoteLine",
    "Delegation",
    "Document",
    "ExtractionResult",
    "GRLine",
    "GoodsReceipt",
    "InboundEmail",
    "Invoice",
    "InvoiceLine",
    "ItemUnit",
    "MatchResult",
    "Organisation",
    "POLine",
    "Payment",
    "Policy",
    "PurchaseOrder",
    "ReasonCode",
    "ServiceEntrySheet",
    "Supplier",
    "User",
]
