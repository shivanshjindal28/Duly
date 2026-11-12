"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""
from app.models.invoice import Document, ExtractionResult, Invoice, InvoiceLine, MatchResult, ReasonCode
from app.models.org import Organisation, Supplier, User
from app.models.procurement import GoodsReceipt, GRLine, POLine, PurchaseOrder, ServiceEntrySheet
from app.models.workflow import (AppSetting, ApprovalStep, AuditEvent, BankChangeRequest, ChatSession, Delegation,
                                 Payment, Policy)

__all__ = [
    "AppSetting",
    "ApprovalStep",
    "AuditEvent",
    "BankChangeRequest",
    "ChatSession",
    "Delegation",
    "Document",
    "ExtractionResult",
    "GRLine",
    "GoodsReceipt",
    "Invoice",
    "InvoiceLine",
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
