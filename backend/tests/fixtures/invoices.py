"""Sample invoice specs for tests (synthetic parties with valid-format GSTINs)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from app.samples.invoice_pdf import InvoiceSpec, Line, Party
from app.validation.gstin import make_gstin

PLANT_X_GSTIN = make_gstin("24", "QWECP1234K")
KESAR_GSTIN = make_gstin("24", "RTYFK5678L")
SAHYADRI_GSTIN = make_gstin("27", "UIOCS9012M")

PLANT_X = Party("Plant X Polymers Pvt Ltd", PLANT_X_GSTIN, "Dahej, Gujarat (fictional)")


def bearings_invoice(**overrides) -> InvoiceSpec:
    spec = InvoiceSpec(
        supplier=Party("Kesar Engineering Spares", KESAR_GSTIN, "Ankleshwar, Gujarat (fictional)", pan=KESAR_GSTIN[2:12]),
        buyer=PLANT_X,
        invoice_number="KES/26-27/0042",
        invoice_date=date(2026, 11, 5),
        po_number="4500001234",
        lines=[
            Line("BRG-6205", "Ball bearing 6205 2RS", "8482", D("100"), "NOS", D("450.00"), D("18")),
            Line("SEAL-M40", "Mechanical seal 40 mm", "8484", D("4"), "NOS", D("7250.00"), D("18")),
        ],
        bank_name="Sahyog Bank (fictional)",
        bank_account="50120034417921",
        bank_ifsc="SHYG0123456",
    )
    for k, v in overrides.items():
        setattr(spec, k, v)
    return spec


def seeded_invoice(db, supplier_name: str = "Kesar Engineering Spares", **overrides) -> InvoiceSpec:
    """The bearings invoice, issued by a seeded supplier to the seeded Plant X GSTIN."""
    from sqlalchemy import select

    from app.models import Organisation, Supplier

    from app.core.crypto import decrypt_str

    s = db.scalar(select(Supplier).where(Supplier.name == supplier_name))
    org = db.scalar(select(Organisation))
    spec = bearings_invoice()
    spec.supplier = Party(s.name, s.gstin, s.address, pan=s.pan)
    spec.buyer = Party(org.name, org.gstin, org.address)
    spec.po_number = "4500001003"  # seeded: 100 bearings ordered, 80 received; 4 seals received
    spec.bank_name, spec.bank_account, spec.bank_ifsc = s.bank_name, decrypt_str(s.bank_account_enc), s.bank_ifsc
    for k, v in overrides.items():
        setattr(spec, k, v)
    return spec
