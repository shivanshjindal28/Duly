"""The simulated AP mailbox (email-in demo): three emails, built from seeded POs and master data.

1. Navrang emails a clean invoice for FIBC liners from its registered domain -> APPROVE (touchless).
2. "Kesar" emails a bearings invoice from kesar-spare.example, a lookalike of the registered
   kesar-spares.example -> FLAG EMAIL_SENDER_UNVERIFIED + security alert.
3. Navrang emails a statement of account as a spreadsheet -> attachment rejected (not an invoice).

Message-IDs are fixed, so fetching the mailbox again never imports an email twice.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.ingestion.email_in import Attachment, build_message
from app.samples.invoice_pdf import render_invoice_pdf
from app.samples.scenarios import parties, po_line, spec_for

LOOKALIKE_SENDER = "billing@kesar-spare.example"


def sample_emails(db: Session, today: date) -> list[bytes]:
    buyer, sup = parties(db)
    npw, kes = sup["V100102"], sup["V100103"]
    liners = render_invoice_pdf(spec_for(buyer, npw, "NPW-318", today - timedelta(days=1), "4500001016",
                                         [po_line("4500001016")]))
    bearings = render_invoice_pdf(spec_for(buyer, kes, "INV/0081", today - timedelta(days=1), "4500001017",
                                           [po_line("4500001017")]))
    # A tiny stand-in for an .xlsx file (zip magic bytes): never parsed, only refused by type.
    statement = b"PK\x03\x04" + b"\x00" * 60
    return [
        build_message(npw.email, "Hetal Shah, Navrang Packaging Works", "Invoice NPW-318 for PO 4500001016",
                      "Dear AP team,\n\nPlease find attached our invoice NPW-318 for 400 FIBC liners delivered "
                      "against PO 4500001016.\n\nRegards,\nHetal Shah\nNavrang Packaging Works",
                      [Attachment("NPW-318.pdf", "application/pdf", liners)],
                      message_id="<npw-318.duly-demo@navrang-pack.example>"),
        build_message(LOOKALIKE_SENDER, "Kesar Engineering Spares", "URGENT: Invoice INV/0081 - please pay today",
                      "Hello,\n\nAttached is invoice INV/0081 for 30 bearings (PO 4500001017). Kindly release payment "
                      "today to avoid supply stoppage.\n\nThanks,\nAccounts, Kesar Engineering Spares",
                      [Attachment("INV-0081.pdf", "application/pdf", bearings)],
                      message_id="<inv-0081.duly-demo@kesar-spare.example>"),
        build_message(npw.email, "Hetal Shah, Navrang Packaging Works", "Statement of account, October 2026",
                      "Dear AP team,\n\nOur statement of account for October is attached for your reconciliation."
                      "\n\nRegards,\nHetal Shah",
                      [Attachment("Navrang_SOA_Oct-2026.xlsx",
                                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", statement)],
                      message_id="<npw-soa-2026-10.duly-demo@navrang-pack.example>"),
    ]
