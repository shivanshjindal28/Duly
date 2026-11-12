"""Seed data v1: Plant X, six fictional suppliers, one user per role, default policy.

Everything here is synthetic. GSTINs carry a valid check digit but are generated from a
fixed random seed; bank names and IFSC prefixes are invented. Every record is flagged
`is_synthetic=True`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import pyotp
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_str
from app.core.db import create_all, drop_all
from app.core.passwords import hash_password
from app.core.policy_defaults import DEFAULT_POLICY
from app.models import Organisation, Policy, Supplier, User
from app.models.enums import EnterpriseType, MsmeCategory, Role
from app.validation.gstin import make_gstin

DEMO_PASSWORD = "Duly@2026"
_rng = random.Random(20261112)


def _pan(holder_type: str, name: str) -> str:
    """Synthetic PAN: 3 random letters, holder type (C company, F firm, P person), name initial, 4 digits, letter."""
    letters = "".join(_rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(3))
    digits = f"{_rng.randint(1000, 9999)}"
    return f"{letters}{holder_type}{name[0].upper()}{digits}{_rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}"


def _account() -> str:
    return "".join(str(_rng.randint(0, 9)) for _ in range(14))


@dataclass(frozen=True)
class SupplierSeed:
    code: str
    name: str
    category: str
    state: str
    holder: str
    msme: MsmeCategory
    udyam: str | None
    enterprise: EnterpriseType
    e_invoice: bool
    terms: int
    written_agreement: bool
    bank_name: str
    ifsc_prefix: str
    city: str
    user_name: str
    user_email: str


SUPPLIERS: list[SupplierSeed] = [
    SupplierSeed("V100101", "Sahyadri Catalysts & Additives Ltd", "Catalysts & additives", "27", "C",
                 MsmeCategory.NONE, None, EnterpriseType.MANUFACTURER, True, 60, True,
                 "Sahyog Bank (fictional)", "SHYG", "Navi Mumbai, Maharashtra",
                 "Anil Joshi", "billing@sahyadri-catalysts.example"),
    SupplierSeed("V100102", "Navrang Packaging Works", "Packaging", "24", "P",
                 MsmeCategory.MICRO, "UDYAM-GJ-24-0012345", EnterpriseType.MANUFACTURER, False, 45, True,
                 "Narmada Co-operative Bank (fictional)", "NRMD", "Vapi, Gujarat",
                 "Hetal Shah", "accounts@navrang-pack.example"),
    SupplierSeed("V100103", "Kesar Engineering Spares", "MRO spares", "24", "F",
                 MsmeCategory.SMALL, "UDYAM-GJ-07-0045678", EnterpriseType.MANUFACTURER, False, 45, True,
                 "Sahyog Bank (fictional)", "SHYG", "Ankleshwar, Gujarat",
                 "Dinesh Patel", "invoices@kesar-spares.example"),
    SupplierSeed("V100104", "Tapti Turnaround Services", "Maintenance services", "24", "F",
                 MsmeCategory.SMALL, "UDYAM-GJ-22-0078901", EnterpriseType.SERVICES, False, 45, True,
                 "Narmada Co-operative Bank (fictional)", "NRMD", "Surat, Gujarat",
                 "Farhan Qureshi", "billing@tapti-services.example"),
    SupplierSeed("V100105", "Konkan Bulk Carriers", "Freight", "27", "C",
                 MsmeCategory.NONE, None, EnterpriseType.SERVICES, False, 30, True,
                 "Sahyog Bank (fictional)", "SHYG", "Panvel, Maharashtra",
                 "Swati Kamat", "freight@konkan-bulk.example"),
    SupplierSeed("V100106", "Dakshin Calibration Labs", "Lab & QC calibration", "29", "F",
                 MsmeCategory.MICRO, "UDYAM-KR-03-0023456", EnterpriseType.SERVICES, False, 30, False,
                 "Kaveri Gramin Bank (fictional)", "KVRG", "Bengaluru, Karnataka",
                 "Lakshmi Rao", "lab@dakshin-cal.example"),
]

# (email, full name, title, role, approver level)
STAFF: list[tuple[str, str, str, Role, int | None]] = [
    ("asha.kulkarni@plantx.example", "Asha Kulkarni", "AP Clerk", Role.CLERK, None),
    ("nikhil.verma@plantx.example", "Nikhil Verma", "AP Clerk", Role.CLERK, None),
    ("rohan.mehta@plantx.example", "Rohan Mehta", "Finance Manager (L1)", Role.APPROVER, 1),
    ("kavita.desai@plantx.example", "Kavita Desai", "Plant Head (L2)", Role.APPROVER, 2),
    ("vikram.rao@plantx.example", "Vikram Rao", "CFO (L3)", Role.APPROVER, 3),
    ("imran.shaikh@plantx.example", "Imran Shaikh", "Stores / Receiving", Role.STORES, None),
    ("meera.iyer@plantx.example", "Meera Iyer", "Internal Auditor", Role.AUDITOR, None),
    ("sanjay.patil@plantx.example", "Sanjay Patil", "System Admin", Role.ADMIN, None),
]


def seed(db: Session) -> dict[str, int]:
    """Insert seed data into an empty schema. Returns counts per entity."""
    plant_pan = _pan("C", "Plant X")
    db.add(Organisation(
        name="Plant X Polymers Pvt Ltd",
        gstin=make_gstin("24", plant_pan),
        pan=plant_pan,
        state_code="24",
        address="Plot 7, GIDC Polymer Estate, Dahej, Bharuch, Gujarat (fictional)",
    ))

    password_hash = hash_password(DEMO_PASSWORD)  # one hash reused: Argon2 is slow by design

    for s in SUPPLIERS:
        pan = _pan(s.holder, s.name)
        account = _account()
        supplier = Supplier(
            code=s.code, name=s.name, category=s.category,
            gstin=make_gstin(s.state, pan), pan=pan, state_code=s.state,
            address=f"{s.city} (fictional)", msme_category=s.msme, udyam_no=s.udyam,
            enterprise_type=s.enterprise, e_invoice_applicable=s.e_invoice,
            payment_terms_days=s.terms, written_agreement=s.written_agreement,
            bank_account_enc=encrypt_str(account), bank_account_last4=account[-4:],
            bank_ifsc=f"{s.ifsc_prefix}0{_rng.randint(100000, 999999)}", bank_name=s.bank_name,
            contact_email=s.user_email,
        )
        db.add(supplier)
        db.flush()
        db.add(User(email=s.user_email, full_name=s.user_name, title=f"Accounts, {s.name}",
                    role=Role.SUPPLIER, supplier_id=supplier.id, password_hash=password_hash))

    for email, name, title, role, level in STAFF:
        user = User(email=email, full_name=name, title=title, role=role, approver_level=level,
                    password_hash=password_hash)
        if role == Role.APPROVER:
            user.mfa_secret_enc = encrypt_str(pyotp.random_base32())
            user.mfa_enabled = True
        db.add(user)

    db.add(Policy(version=1, name="Default policy (assumptions)", data=DEFAULT_POLICY, is_active=True))
    db.commit()
    return {
        "organisations": 1,
        "suppliers": len(SUPPLIERS),
        "users": len(SUPPLIERS) + len(STAFF),
        "policies": 1,
    }


def reset_and_seed(db: Session) -> dict[str, int]:
    db.close()
    drop_all()
    create_all()
    return seed(db)
