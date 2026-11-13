"""Seed data v1: Plant X, six fictional suppliers, one user per role, default policy.

Everything here is synthetic. GSTINs carry a valid check digit but are generated from a
fixed random seed; bank names and IFSC prefixes are invented. Every record is flagged
`is_synthetic=True`.
"""
from __future__ import annotations

import random
from decimal import Decimal
from dataclasses import dataclass

import pyotp
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_str
from app.core.db import create_all, drop_all
from app.core.passwords import hash_password
from app.core.policy_defaults import DEFAULT_POLICY
from app.models import Organisation, Policy, PurchaseOrder, Supplier, User
from app.core.enums import EnterpriseType, MsmeCategory, Role
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
    tds_section: str = "none"
    early_discount_pct: str = "0"
    early_discount_days: int = 0


SUPPLIERS: list[SupplierSeed] = [
    SupplierSeed("V100101", "Sahyadri Catalysts & Additives Ltd", "Catalysts & additives", "27", "C",
                 MsmeCategory.NONE, None, EnterpriseType.MANUFACTURER, True, 60, True,
                 "Sahyog Bank (fictional)", "SHYG", "Navi Mumbai, Maharashtra",
                 "Anil Joshi", "billing@sahyadri-catalysts.example", "goods", "1.00", 10),
    SupplierSeed("V100102", "Navrang Packaging Works", "Packaging", "24", "P",
                 MsmeCategory.MICRO, "UDYAM-GJ-24-0012345", EnterpriseType.MANUFACTURER, False, 45, True,
                 "Narmada Co-operative Bank (fictional)", "NRMD", "Vapi, Gujarat",
                 "Hetal Shah", "accounts@navrang-pack.example", "goods"),
    SupplierSeed("V100103", "Kesar Engineering Spares", "MRO spares", "24", "F",
                 MsmeCategory.SMALL, "UDYAM-GJ-07-0045678", EnterpriseType.MANUFACTURER, False, 45, True,
                 "Sahyog Bank (fictional)", "SHYG", "Ankleshwar, Gujarat",
                 "Dinesh Patel", "invoices@kesar-spares.example", "goods"),
    SupplierSeed("V100104", "Tapti Turnaround Services", "Maintenance services", "24", "F",
                 MsmeCategory.SMALL, "UDYAM-GJ-22-0078901", EnterpriseType.SERVICES, False, 45, True,
                 "Narmada Co-operative Bank (fictional)", "NRMD", "Surat, Gujarat",
                 "Farhan Qureshi", "billing@tapti-services.example", "contractor"),
    SupplierSeed("V100105", "Konkan Bulk Carriers", "Freight", "27", "C",
                 MsmeCategory.NONE, None, EnterpriseType.SERVICES, False, 30, True,
                 "Sahyog Bank (fictional)", "SHYG", "Panvel, Maharashtra",
                 "Swati Kamat", "freight@konkan-bulk.example", "contractor"),
    SupplierSeed("V100106", "Dakshin Calibration Labs", "Lab & QC calibration", "29", "F",
                 MsmeCategory.MICRO, "UDYAM-KR-03-0023456", EnterpriseType.SERVICES, False, 30, False,
                 "Kaveri Gramin Bank (fictional)", "KVRG", "Bengaluru, Karnataka",
                 "Lakshmi Rao", "lab@dakshin-cal.example", "technical"),
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


@dataclass(frozen=True)
class ForeignSupplierSeed:
    code: str
    name: str
    category: str
    country: str  # ISO code
    country_name: str
    currency: str
    tax_id: str  # fictional foreign VAT ID (stored in the gstin column)
    terms: int
    bank_name: str
    iban: str  # fictional
    bic: str  # fictional
    city: str
    user_name: str
    user_email: str


FOREIGN_SUPPLIERS: list[ForeignSupplierSeed] = [
    ForeignSupplierSeed("V200101", "Nordwerk Polymer Additives GmbH", "Imported polymer additives", "DE", "Germany",
                        "EUR", "DE-FICT-447101", 60, "Nordbank AG (fictional)", "DE00FICT0000447101000",
                        "FICTDEFFXXX", "Musterstadt, Germany", "Lena Brandt", "billing@nordwerk-additives.example"),
]

# Item master pack sizes: 1 `unit` of the item = `qty` `base_unit`. Lets suppliers bill (and stores receive)
# in boxes, bags, drums or bundles while the PO is in pieces or kilograms.
ITEM_UNITS: list[tuple[str, str, str, str]] = [
    ("BRG-6205", "BOX", "10", "NOS"), ("BRG-6310", "BOX", "5", "NOS"), ("SEAL-M40", "SET", "4", "NOS"),
    ("ADD-AO-1010", "BAG", "25", "KG"), ("NUC-AGT-77", "BAG", "20", "KG"), ("CAT-ZN-01", "DRUM", "200", "KG"),
    ("PKG-FFS-25", "BUNDLE", "100", "NOS"), ("PKG-FFS-50", "BUNDLE", "50", "NOS"), ("PKG-FIBC-1T", "BALE", "20", "NOS"),
]


def seed(db: Session, history: bool = False) -> dict[str, int]:
    """Insert seed data into an empty schema. Returns counts per entity.

    history=True also replays ~250 invoices over the last 90 days through the real engine and
    workflow (`app/seed_history.py`) for dashboards, payment runs and impact numbers."""
    global _rng
    _rng = random.Random(20261112)  # same synthetic GSTINs and accounts on every reset
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
            contact_email=s.user_email, tds_section=s.tds_section,
            early_discount_pct=Decimal(s.early_discount_pct), early_discount_days=s.early_discount_days,
        )
        db.add(supplier)
        db.flush()
        db.add(User(email=s.user_email, full_name=s.user_name, title=f"Accounts, {s.name}",
                    role=Role.SUPPLIER, supplier_id=supplier.id, password_hash=password_hash))

    for f in FOREIGN_SUPPLIERS:
        supplier = Supplier(
            code=f.code, name=f.name, category=f.category, gstin=f.tax_id, pan="", state_code="",
            address=f"{f.city} (fictional)", country=f.country, currency=f.currency,
            msme_category=MsmeCategory.NONE, udyam_no=None, enterprise_type=EnterpriseType.MANUFACTURER,
            e_invoice_applicable=False, payment_terms_days=f.terms, written_agreement=True,
            bank_account_enc=encrypt_str(f.iban), bank_account_last4=f.iban[-4:], bank_ifsc=f.bic,
            bank_name=f.bank_name, contact_email=f.user_email, tds_section="none",
        )
        db.add(supplier)
        db.flush()
        db.add(User(email=f.user_email, full_name=f.user_name, title=f"Accounts, {f.name}",
                    role=Role.SUPPLIER, supplier_id=supplier.id, password_hash=password_hash))

    from app.models import ItemUnit

    for item, unit, qty, base in ITEM_UNITS:
        db.add(ItemUnit(item_code=item, unit=unit, qty=Decimal(qty), base_unit=base))

    for email, name, title, role, level in STAFF:
        user = User(email=email, full_name=name, title=title, role=role, approver_level=level,
                    password_hash=password_hash)
        if role == Role.APPROVER:
            user.mfa_secret_enc = encrypt_str(pyotp.random_base32())
            user.mfa_enabled = True
        db.add(user)

    db.add(Policy(version=1, name="Default policy (assumptions)", data=DEFAULT_POLICY, is_active=True))
    db.flush()
    counts = seed_procurement(db)
    from app.core import audit

    if history:
        from app.seed_history import seed_history

        db.commit()
        counts.update(seed_history(db))
        counts["purchase_orders"] = db.scalar(select(func.count()).select_from(PurchaseOrder))
    audit.queue(db, "system.seeded", "database", None, actor=audit.SYSTEM, after={
        "synthetic": True, **counts,
        "note": ("history replayed through the real engine and workflow with the business clock set to past dates"
                 if history else "no invoice history")})
    db.commit()
    return {
        "organisations": 1,
        "suppliers": len(SUPPLIERS) + len(FOREIGN_SUPPLIERS),
        "users": len(SUPPLIERS) + len(FOREIGN_SUPPLIERS) + len(STAFF),
        "policies": 1,
        **counts,
    }


@dataclass(frozen=True)
class POSeed:
    """A purchase order for a demo scenario. receipts: per line, (qty or SES value, days ago) or None."""

    po_number: str
    supplier_code: str
    scenario: str
    lines: list[tuple[str, str, str, str, str, str, str]]  # item, desc, hsn, qty, uom, price, gst%
    receipts: list[tuple[str, int] | None]
    is_service: bool = False
    status: str = "open"
    created_by: str | None = None
    po_days_ago: int = 30
    ers: bool = False
    currency: str = "INR"


PURCHASE_ORDERS: list[POSeed] = [
    POSeed("4500001001", "V100101", "S1 clean catalyst, > Rs 10 lakh (L1 + L2 + MFA)",
           [("CAT-ZN-01", "Ziegler-Natta catalyst ZN-118", "3815", "1.5", "MT", "850000.00", "18")], [("1.5", 6)]),
    POSeed("4500001002", "V100101", "S2 additive billed 3.2% above PO price",
           [("ADD-AO-1010", "Antioxidant 1010 powder", "3812", "2000", "KG", "620.00", "18")], [("2000", 8)]),
    POSeed("4500001003", "V100103", "S3/S5 bearings: 100 ordered, 80 received; duplicate resubmission",
           [("BRG-6205", "Ball bearing 6205 2RS", "8482", "100", "NOS", "450.00", "18"),
            ("SEAL-M40", "Mechanical seal 40 mm", "8484", "4", "NOS", "7250.00", "18")], [("80", 5), ("4", 5)]),
    POSeed("4500001004", "V100102", "S4 packaging invoiced before goods arrive (no GR yet)",
           [("PKG-FFS-25", "FFS bag 25 kg PE", "3923", "20000", "NOS", "14.50", "18")], [None]),
    POSeed("4500001005", "V100102", "S10 MSME jumbo bags, GR 41 days ago",
           [("PKG-FIBC-1T", "Jumbo bag FIBC 1 tonne", "6305", "400", "NOS", "385.00", "5")], [("400", 41)],
           po_days_ago=55),
    POSeed("4500001006", "V100104", "S11 turnaround maintenance services with SES (TDS)",
           [("SRV-TA-01", "Turnaround mechanical maintenance", "998719", "1", "LS", "420000.00", "18")],
           [("420000.00", 3)], is_service=True),
    POSeed("4500001007", "V100105", "Freight; PO created by the L1 approver (SoD demo)",
           [("FRT-TNK-01", "Bulk tanker freight Dahej to Taloja", "996511", "10", "TRIP", "38000.00", "12")],
           [("152000.00", 4)], is_service=True, created_by="rohan.mehta@plantx.example"),
    POSeed("4500001008", "V100106", "Lab calibration services (MSME micro, no written agreement)",
           [("SRV-CAL-01", "Lab instrument calibration", "998346", "1", "LS", "36000.00", "18")],
           [("36000.00", 9)], is_service=True),
    POSeed("4500001009", "V100103", "S6 pump impellers: invoice carries a different bank account",
           [("PUMP-IMP-50", "Pump impeller 50 mm SS316", "8413", "10", "NOS", "6800.00", "18")], [("10", 4)]),
    POSeed("4500001010", "V100102", "S7 pallets: invoice with hidden prompt-injection text",
           [("PKG-PLT-1210", "Wooden pallet 1200 x 1000", "4415", "300", "NOS", "950.00", "12")], [("300", 6)]),
    POSeed("4500001011", "V100101", "S8 catalyst: PDF total edited, signed QR original",
           [("CAT-ZN-01", "Ziegler-Natta catalyst ZN-118", "3815", "0.5", "MT", "850000.00", "18")], [("0.5", 7)]),
    POSeed("4500001012", "V100103", "S9 seals: intra-state invoice charging IGST",
           [("SEAL-M60", "Mechanical seal 60 mm", "8484", "6", "NOS", "9400.00", "18")], [("6", 3)]),
    POSeed("4500001013", "V100102", "S12 FFS bags: blurry low-confidence photo",
           [("PKG-FFS-50", "FFS bag 50 kg PE", "3923", "5000", "NOS", "21.00", "18")], [("5000", 5)]),
    POSeed("4500001014", "V100103", "S5 bearings: INV/0042 (history) resubmitted as a photo 'INV-42'",
           [("BRG-6205", "Ball bearing 6205 2RS", "8482", "50", "NOS", "450.00", "18")], [("50", 12)],
           po_days_ago=25),
    POSeed("4500001015", "V100105", "Freight on evaluated receipt settlement (ERS): stores' SES settles it, no invoice",
           [("FRT-TRK-02", "Truck freight Dahej to Bhiwandi", "996511", "6", "TRIP", "22000.00", "12")],
           [None], is_service=True, ers=True, po_days_ago=10),
    POSeed("4500001016", "V100102", "Email-in: FIBC liners, invoice emailed from Navrang's registered domain",
           [("PKG-LNR-1T", "FIBC PE liner 1 tonne", "3923", "400", "NOS", "62.00", "18")], [("400", 2)],
           po_days_ago=14),
    POSeed("4500001017", "V100103", "Email-in: bearings 6310, invoice emailed from a lookalike domain",
           [("BRG-6310", "Ball bearing 6310 2RS", "8482", "30", "NOS", "980.00", "18")], [("30", 3)],
           po_days_ago=12),
    POSeed("4500000990", "V100105", "Closed PO (PO_CLOSED demo)",
           [("FRT-TNK-01", "Bulk tanker freight Dahej to Taloja", "996511", "4", "TRIP", "38000.00", "12")],
           [None], is_service=True, status="closed", po_days_ago=120),
    POSeed("4500001018", "V200101", "S13 import: nucleating agent from Germany, PO and invoice in EUR",
           [("NUC-AGT-77", "Nucleating agent NA-77 (clarifier)", "3812", "500", "KG", "38.50", "0")], [("500", 5)],
           po_days_ago=40, currency="EUR"),
    POSeed("4500001019", "V100103", "S14 units: bearings ordered in pieces, billed in boxes of 10",
           [("BRG-6205", "Ball bearing 6205 2RS", "8482", "200", "NOS", "450.00", "18")], [("150", 4)],
           po_days_ago=20),
]


def seed_procurement(db: Session) -> dict[str, int]:
    """POs with goods receipts / service entry sheets for the demo scenarios."""
    from datetime import timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from app.core import clock
    from app.models import GoodsReceipt, GRLine, POLine, PurchaseOrder, ServiceEntrySheet

    suppliers = {s.code: s for s in db.scalars(select(Supplier))}
    users = {u.email: u for u in db.scalars(select(User))}
    stores = users["imran.shaikh@plantx.example"]
    now, today = clock.now(), clock.today()
    gr_no, ses_no, grs, sess = 5000000101, 1000000201, 0, 0
    for spec in PURCHASE_ORDERS:
        s = suppliers[spec.supplier_code]
        po = PurchaseOrder(po_number=spec.po_number, supplier_id=s.id, po_date=today - timedelta(days=spec.po_days_ago),
                           status=spec.status, payment_terms_days=s.payment_terms_days, is_service=spec.is_service,
                           ers=spec.ers, currency=spec.currency,
                           created_by_user_id=users[spec.created_by].id if spec.created_by else None)
        db.add(po)
        db.flush()
        for n, (item, desc, hsn_code, qty, uom, price, gst) in enumerate(spec.lines, start=1):
            pl = POLine(po_id=po.id, line_no=n * 10, item_code=item, description=desc, hsn_sac=hsn_code,
                        qty=Decimal(qty), uom=uom, unit_price=Decimal(price), gst_rate=Decimal(gst))
            db.add(pl)
            db.flush()
            receipt = spec.receipts[n - 1]
            if receipt is None:
                continue
            amount, days_ago = receipt
            posted = now - timedelta(days=days_ago)
            if spec.is_service:
                db.add(ServiceEntrySheet(ses_number=str(ses_no), po_id=po.id, po_line_id=pl.id, description=desc,
                                         value=Decimal(amount), posted_by_user_id=stores.id, posted_at=posted))
                ses_no += 1
                sess += 1
            else:
                gr = GoodsReceipt(gr_number=str(gr_no), po_id=po.id, posted_by_user_id=stores.id, posted_at=posted)
                db.add(gr)
                db.flush()
                db.add(GRLine(gr_id=gr.id, po_line_id=pl.id, qty=Decimal(amount), uom=uom))
                gr_no += 1
                grs += 1
    return {"purchase_orders": len(PURCHASE_ORDERS), "goods_receipts": grs, "service_entry_sheets": sess}


def reset_and_seed(db: Session, history: bool = False) -> dict[str, int]:
    from app.core import clock

    db.close()
    drop_all()
    create_all()
    _clear_runtime_files()
    clock.load_offset(db)  # the demo clock starts again at real time (its setting was dropped)
    return seed(db, history=history)


def _clear_runtime_files() -> None:
    """Stored documents and rendered page images belong to the dropped database."""
    import shutil

    from app.core.config import DATA_DIR

    for sub in ("uploads", "pages"):
        shutil.rmtree(DATA_DIR / sub, ignore_errors=True)
