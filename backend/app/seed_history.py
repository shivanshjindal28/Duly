"""~250 historical invoices over the last 90 days, produced by the real system.

Nothing here writes an outcome directly. A seeded random plan (purchase orders, deliveries,
invoices, the occasional price increase, early invoice, over-billing, wrong tax head or
resubmitted duplicate) is replayed as a time-ordered stream of business events, each run with
the business clock set to the moment it "happened" (`clock.travel_to`):

    stores posts GR / SES  -> receipts.post_goods_receipt / post_service_entry (auto re-match)
    invoice arrives        -> pipeline.create_invoice (rendered PDF, text layer, offline parser) + engine
    clerk routes a FLAG    -> approvals.override_flag (written justification)
    approver acts          -> approvals.approve / reject (MFA codes for > Rs 10 lakh, SLA escalation)
    weekly payment run     -> payments.run.plan + release (MSME first, TDS, simulated UTR)
    supplier bank change   -> bank_changes request / propose (call-back) / cooling / approve

So decisions, approval routes, due dates, payments, KPIs and the audit chain are exactly what
Duly would have produced. Recent work is left open (pending approval, flagged, blocked) so the
dashboards and queues have something to show. All data is synthetic.
"""
from __future__ import annotations

import heapq
import itertools
import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal as D

import jwt
import pyotp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.offline_parser import parse
from app.core import audit, clock
from app.core.crypto import decrypt_str
from app.core.enums import InvoiceStatus, Severity, StepStatus
from app.ingestion.extract_text import text_layer_tokens
from app.ingestion.pipeline import Ingested, create_invoice
from app.ingestion.qr import QrResult
from app.ingestion.storage import sha256
from app.models import ApprovalStep, BankChangeRequest, Invoice, POLine, PurchaseOrder, Supplier, User
from app.payments import run as payrun
from app.samples import scenarios
from app.samples.invoice_pdf import Line, render_invoice_pdf, with_einvoice
from app.workflow import approvals, bank_changes, receipts
from app.workflow.matching import latest_match

DAYS = 90
SEED = 20261113

STORES = "imran.shaikh@plantx.example"
CLERKS = ["asha.kulkarni@plantx.example", "nikhil.verma@plantx.example"]
APPROVER = {1: "rohan.mehta@plantx.example", 2: "kavita.desai@plantx.example", 3: "vikram.rao@plantx.example"}


@dataclass(frozen=True)
class Item:
    code: str
    desc: str
    hsn: str
    uom: str
    price: str
    gst: str
    qtys: tuple  # quantities a delivery may have


def _r(lo, hi, step=1):
    return tuple(D(str(lo)) + D(str(step)) * i for i in range(int((D(str(hi)) - D(str(lo))) / D(str(step))) + 1))


@dataclass(frozen=True)
class Profile:
    """How a supplier's business looks: items, PO count, deliveries per PO, days between them."""

    code: str
    items: tuple[Item, ...]
    pos: int
    deliveries: tuple[int, int]
    gap_days: tuple[int, int]
    service: bool
    number: str  # invoice number format, {n}
    first_number: int
    lines_per_po: tuple[int, int] = (1, 2)


PROFILES = [
    Profile("V100101", (
        Item("CAT-ZN-01", "Ziegler-Natta catalyst ZN-118", "3815", "MT", "850000.00", "18", _r("0.6", "1.2", "0.1")),
        Item("ADD-AO-1010", "Antioxidant 1010 powder", "3812", "KG", "620.00", "18", _r(600, 1800, 100)),
        Item("ADD-AO-168", "Antioxidant 168 phosphite", "3812", "KG", "410.00", "18", _r(800, 2400, 100)),
        Item("ADD-UV-770", "UV stabiliser HALS 770", "3812", "KG", "1150.00", "18", _r(150, 600, 50)),
        Item("ADD-SL-01", "Slip agent erucamide", "3812", "KG", "290.00", "18", _r(500, 1500, 100)),
    ), pos=7, deliveries=(3, 5), gap_days=(10, 18), service=False, number="SCA/26-27/{n:04d}", first_number=701),
    Profile("V100102", (
        Item("PKG-FFS-25", "FFS bag 25 kg PE", "3923", "NOS", "14.50", "18", _r(1500, 9000, 250)),
        Item("PKG-FFS-50", "FFS bag 50 kg PE", "3923", "NOS", "21.00", "18", _r(1000, 4500, 125)),
        Item("PKG-FIBC-1T", "Jumbo bag FIBC 1 tonne", "6305", "NOS", "385.00", "5", _r(50, 250, 10)),
        Item("PKG-PLT-1210", "Wooden pallet 1200 x 1000", "4415", "NOS", "950.00", "12", _r(25, 150, 5)),
    ), pos=12, deliveries=(5, 7), gap_days=(6, 11), service=False, number="NPW-{n}", first_number=201,
        lines_per_po=(1, 1)),
    Profile("V100103", (
        Item("BRG-6205", "Ball bearing 6205 2RS", "8482", "NOS", "450.00", "18", _r(20, 90, 5)),
        Item("BRG-6308", "Ball bearing 6308 ZZ", "8482", "NOS", "1250.00", "18", _r(6, 30, 2)),
        Item("SEAL-M40", "Mechanical seal 40 mm", "8484", "NOS", "7250.00", "18", _r(1, 12)),
        Item("GSK-SW-80", "Spiral wound gasket 80 NB", "8484", "NOS", "640.00", "18", _r(10, 60, 5)),
        Item("PUMP-IMP-50", "Pump impeller 50 mm SS316", "8413", "NOS", "6800.00", "18", _r(1, 12)),
    ), pos=11, deliveries=(3, 5), gap_days=(8, 14), service=False, number="INV/{n:04d}", first_number=0,
        lines_per_po=(1, 1)),
    Profile("V100104", (
        Item("SRV-MECH-01", "Mechanical maintenance manpower", "998719", "MDAY", "4500.00", "18", _r(18, 60)),
        Item("SRV-SCAF-01", "Scaffolding erection and removal", "998719", "SQM", "180.00", "18", _r(300, 1200, 50)),
    ), pos=5, deliveries=(2, 4), gap_days=(20, 30), service=True, number="TTS/MM/2026/{n:03d}", first_number=1,
        lines_per_po=(1, 1)),
    Profile("V100105", (
        Item("FRT-TNK-01", "Bulk tanker freight Dahej to Taloja", "996511", "TRIP", "38000.00", "12", _r(1, 16)),
        Item("FRT-TRK-02", "Truck freight Dahej to Bhiwandi", "996511", "TRIP", "22000.00", "12", _r(1, 18)),
        Item("FRT-TNK-03", "Tanker freight Dahej to Hazira", "996511", "TRIP", "16500.00", "12", _r(1, 18)),
        Item("FRT-TRK-04", "Truck freight Dahej to Silvassa", "996511", "TRIP", "14500.00", "12", _r(1, 20)),
    ), pos=10, deliveries=(6, 8), gap_days=(4, 8), service=True, number="KBC/FRT/{n}", first_number=3301,
        lines_per_po=(1, 1)),
    Profile("V100106", (
        Item("SRV-CAL-02", "Instrument calibration visit", "998346", "NOS", "6200.00", "18", _r(1, 16)),
        Item("SRV-CAL-03", "Balance and weights calibration", "998346", "NOS", "2400.00", "18", _r(2, 24)),
    ), pos=8, deliveries=(2, 4), gap_days=(12, 22), service=True, number="DCL-2026-{n:03d}", first_number=61,
        lines_per_po=(1, 1)),
]

# (supplier, item, qty) used by the live demo scenarios: never reused in the history, so the
# demo invoices are not near-duplicates of history (except S5's original, which is the point).
DEMO_ITEM_QTYS = {
    ("V100101", "CAT-ZN-01", D("1.5")), ("V100101", "CAT-ZN-01", D("0.5")), ("V100101", "ADD-AO-1010", D(2000)),
    ("V100102", "PKG-FFS-25", D(20000)), ("V100102", "PKG-FFS-50", D(5000)), ("V100102", "PKG-FIBC-1T", D(400)),
    ("V100102", "PKG-PLT-1210", D(300)), ("V100103", "BRG-6205", D(100)), ("V100103", "BRG-6205", D(50)),
    ("V100103", "SEAL-M40", D(4)), ("V100103", "PUMP-IMP-50", D(10)),
}

JUSTIFICATIONS = {
    "PRICE_VARIANCE": ["Price increase agreed by the buyer on {d}; PO amendment raised, approve at invoice price.",
                       "Buyer confirmed the revised rate for this lot (raw material surcharge); PO to be amended."],
    "TAX_MISMATCH": ["Supplier confirmed the tax head is wrong but the amount is right; corrected invoice to follow."],
    "EINVOICE_QR_MISSING": ["Original e-invoice PDF requested; IRN checked manually on the supplier's copy."],
    "SES_VALUE_EXCEEDED": ["Balance work confirmed by the plant engineer; extra SES being posted, approve as billed."],
    "QTY_EXCEEDS_GR": ["Balance quantity received at the gate, GR posting delayed; checked with stores."],
    "POSSIBLE_DUPLICATE": ["Checked with the supplier: a separate delivery (different LR / challan), not a copy."],
}
REJECTIONS = ["Rate not agreed: supplier to issue a credit note for the difference and re-bill at the PO price.",
              "Price increase not approved by purchasing; send back to the supplier for a corrected invoice."]


@dataclass
class Delivery:
    po: str
    supplier: str
    service: bool
    lines: list[tuple[int, Item, D]]  # (po line index, item, qty)
    at: datetime


@dataclass
class Planned:
    delivery: Delivery
    at: datetime
    variant: str  # clean | price | tax | qty_over | early | no_qr
    price_pct: D = D(0)
    number: str = ""
    uploader: str = ""
    dup_after_days: int | None = None


@dataclass(order=True)
class Event:
    at: datetime
    seq: int
    kind: str = field(compare=False)
    data: object = field(compare=False, default=None)


class History:
    def __init__(self, db: Session, now: datetime):
        self.db, self.now = db, now
        self.rng = random.Random(SEED)
        self.start = now - timedelta(days=DAYS)
        self.events: list[Event] = []
        self.seq = itertools.count()
        self.users = {u.email: u for u in db.scalars(select(User))}
        self.suppliers = {s.code: s for s in db.scalars(select(Supplier))}
        self.planned: dict[int, Planned] = {}  # invoice id -> plan
        self.scheduled_steps: set[int] = set()
        self.handled_flags: set[int] = set()
        self.counts = {"history_invoices": 0, "history_duplicates": 0, "history_payment_runs": 0}

    # ---------------------------------------------------------------- time helpers
    def push(self, at: datetime, kind: str, data=None) -> None:
        if at < self.now - timedelta(minutes=30):  # the future has not happened yet
            heapq.heappush(self.events, Event(at, next(self.seq), kind, data))

    def office(self, at: datetime) -> datetime:
        """The next moment in office hours (Mon-Fri 09:30-19:00 IST) at or after `at`."""
        t = at.astimezone(clock.IST)
        for _ in range(8):
            open_, close = t.replace(hour=9, minute=30, second=0, microsecond=0), t.replace(hour=19, minute=0)
            if t.weekday() < 5 and open_ <= t <= close:
                return t
            if t.weekday() < 5 and t < open_:
                return open_ + timedelta(minutes=self.rng.randint(0, 90))
            t = (t + timedelta(days=1)).replace(hour=9, minute=30) + timedelta(minutes=self.rng.randint(0, 90))
            if t.weekday() < 5:
                return t
        return t

    def anytime(self, day: date, lo: int = 8, hi: int = 21) -> datetime:
        return datetime.combine(day, time(self.rng.randint(lo, hi - 1), self.rng.randint(0, 59)), tzinfo=clock.IST)

    def act_as(self, email: str) -> User:
        user = self.users[email]
        audit.set_actor(self.db, user.id, user.role, None)
        return user

    # ---------------------------------------------------------------- the plan
    def plan(self) -> None:
        recent: dict[tuple[str, str], list[tuple[date, D]]] = {}
        po_no = itertools.count(4500000801)
        deliveries: list[Delivery] = []
        first_day = (self.start + timedelta(days=2)).astimezone(clock.IST).date()
        last_day = (self.now - timedelta(days=1)).astimezone(clock.IST).date()
        for prof in PROFILES:
            catalogue = list(prof.items)
            self.rng.shuffle(catalogue)
            for po_index in range(prof.pos):
                n_lines = self.rng.randint(*prof.lines_per_po)
                # Spread the supplier's items evenly over its POs (a lane or item is not over-used).
                items = [catalogue[(po_index + k) % len(catalogue)] for k in range(n_lines)]
                n_del = self.rng.randint(*prof.deliveries)
                span = n_del * sum(prof.gap_days) // 2
                day = first_day + timedelta(days=self.rng.randint(0, max(1, (last_day - first_day).days - span // 2)))
                po_lines_qty: dict[int, D] = {i: D(0) for i in range(n_lines)}
                po_number = str(next(po_no))
                po_deliveries = []
                for _ in range(n_del):
                    if day > last_day:
                        break
                    lines = []
                    for i, item in enumerate(items):
                        qty = self._pick_qty(prof.code, item, day, recent)
                        lines.append((i, item, qty))
                        po_lines_qty[i] += qty
                    at = self.office(self.anytime(day, 9, 18)) if not prof.service else self.anytime(day, 10, 18)
                    po_deliveries.append(Delivery(po_number, prof.code, prof.service, lines, at))
                    day += timedelta(days=self.rng.randint(*prof.gap_days))
                if not po_deliveries:
                    continue
                self._create_po(po_number, prof, items, po_lines_qty, po_deliveries[0].at)
                deliveries += po_deliveries

        invoices: list[Planned] = []
        for dlv in deliveries:
            inv_at = dlv.at + timedelta(hours=self.rng.randint(10, 90))
            roll = self.rng.random()
            variant, pct = "clean", D(0)
            if roll < 0.07:
                variant = "early"
                inv_at = dlv.at - timedelta(hours=self.rng.randint(20, 70))
            elif roll < 0.15:
                variant, pct = "price", self.rng.choice([D("1.6"), D("2.1"), D("2.8"), D("3.4"), D("4.2")])
            elif roll < 0.20:
                variant = "qty_over"
            elif roll < 0.23 and self.suppliers[dlv.supplier].state_code == "24":
                variant = "tax"
            elif roll < 0.29 and dlv.supplier == "V100101":
                variant = "no_qr"
            p = Planned(dlv, inv_at, variant, pct)
            if self.rng.random() < 0.035:
                p.dup_after_days = self.rng.randint(4, 20)
            invoices.append(p)
            self.push(dlv.at, "receipt", (dlv, D(1)))  # an "early" invoice arrives before this receipt
        self._number(invoices)
        for p in invoices:
            self.push(p.at, "invoice", p)
            if p.variant == "qty_over":  # the rest of the delivery (or the missing services) arrives later
                self.push(self.office(p.at + timedelta(days=self.rng.randint(2, 7))), "receipt",
                          (p.delivery, D("0.15")))
        # Monday-to-Friday weekly payment runs, the latest yesterday.
        run_day = (self.now - timedelta(days=1)).astimezone(clock.IST).date()
        while datetime.combine(run_day, time(11), tzinfo=clock.IST) > self.start + timedelta(days=7):
            self.push(datetime.combine(run_day, time(11), tzinfo=clock.IST), "payment_run")
            run_day -= timedelta(days=7)
        self._special_events()

    def _pick_qty(self, code: str, item: Item, day: date, recent: dict) -> D:
        """A delivery quantity not used for this item in the last 35 days (so genuine repeat orders
        are not near-duplicates of each other) and never a demo scenario's quantity."""
        used = recent.setdefault((code, item.code), [])
        allowed = [q for q in item.qtys if (code, item.code, q) not in DEMO_ITEM_QTYS]

        def gap(q: D) -> int:  # days to the nearest delivery of the same quantity
            return min((abs((day - ud).days) for ud, uq in used if uq == q), default=10_000)

        options = [q for q in allowed if gap(q) > 34]  # duplicate check window: 30 days + date jitter
        qty = self.rng.choice(options) if options else max(allowed, key=gap)
        used.append((day, qty))
        return qty

    def _create_po(self, po_number: str, prof: Profile, items: list[Item], qty: dict[int, D], first: datetime) -> None:
        s = self.suppliers[prof.code]
        po = PurchaseOrder(po_number=po_number, supplier_id=s.id, status="open", is_service=prof.service,
                           po_date=(first - timedelta(days=self.rng.randint(4, 15))).astimezone(clock.IST).date(),
                           payment_terms_days=s.payment_terms_days)
        self.db.add(po)
        self.db.flush()
        for i, item in enumerate(items):
            ordered = (qty[i] * D("1.3")).quantize(D("0.1") if item.uom == "MT" else D(1))
            self.db.add(POLine(po_id=po.id, line_no=(i + 1) * 10, item_code=item.code, description=item.desc,
                               hsn_sac=item.hsn, qty=ordered, uom=item.uom, unit_price=D(item.price),
                               gst_rate=D(item.gst)))
        self.db.flush()

    def _number(self, invoices: list[Planned]) -> None:
        """Invoice numbers per supplier in date order. Kesar's genuine bearings invoice must be INV/0042
        (scenario 5), so Kesar's numbering is anchored on it."""
        invoices.sort(key=lambda p: p.at)
        s5_at = self.now - timedelta(days=9)
        for prof in PROFILES:
            mine = [p for p in invoices if p.delivery.supplier == prof.code]
            n = prof.first_number
            if prof.code == "V100103":
                # The plan is laid out relative to today, so on some dates more than 41 Kesar invoices fall
                # before the scenario-5 original. Drop the oldest extras (their deliveries simply stay
                # uninvoiced) so the numbering still lands on INV/0042 whatever the date.
                before = [p for p in mine if p.at < s5_at]
                for extra in before[: max(0, len(before) - 41)]:
                    invoices.remove(extra)
                    mine.remove(extra)
                n = 42 - sum(1 for p in mine if p.at < s5_at)
            for p in mine:
                if prof.code == "V100103" and n == 42:
                    n += 1  # reserved for the scenario 5 original
                p.number = prof.number.format(n=n)
                p.uploader = (self.rng.choice(CLERKS) if self.rng.random() < 0.3
                              else scenarios.SUPPLIER_EMAIL[prof.code])
                n += 1

    def _special_events(self) -> None:
        # Scenario 5's original: Kesar's bearings invoice INV/0042 (touchless, awaiting payment).
        self.push(self.office(self.now - timedelta(days=9, hours=2)), "s5_original")
        # A supplier changes its bank account the proper way (maker-checker, call-back, cooling period),
        # before the first history invoice: invoices printed with the old account stay consistent.
        t = self.office(self.now - timedelta(days=DAYS + 6))
        self.push(t, "bank_request")
        self.push(self.office(t + timedelta(hours=20)), "bank_propose")
        self.push(self.office(t + timedelta(days=5)), "bank_approve")

    # ---------------------------------------------------------------- replay
    def run(self) -> dict[str, int]:
        self.plan()
        self.db.commit()
        while self.events:
            ev = heapq.heappop(self.events)
            with clock.travel_to(ev.at):
                getattr(self, f"on_{ev.kind}")(ev)
                self.db.commit()
                self._follow_up(ev.at)
                self.db.commit()
        audit.set_actor(self.db, None, "system", None)
        return self.counts

    def on_receipt(self, ev: Event) -> None:
        dlv, share = ev.data
        user = self.act_as(STORES)
        po = self.db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == dlv.po))
        lines = {pl.line_no: pl for pl in po.lines}
        try:
            if dlv.service:
                for i, item, qty in dlv.lines:
                    units = qty if share == 1 else max(D(1), (qty * share).quantize(D(1)))
                    receipts.post_service_entry(self.db, user, dlv.po, lines[(i + 1) * 10].id, units * D(item.price),
                                                f"{item.desc}: {units} {item.uom}")
            else:
                rows = []
                for i, item, qty in dlv.lines:
                    q = qty if share == 1 else _round(qty * share, item.uom)
                    rows.append((lines[(i + 1) * 10].id, q))
                receipts.post_goods_receipt(self.db, user, dlv.po, rows)
        except receipts.ReceiptError:
            self.db.rollback()

    def on_invoice(self, ev: Event) -> None:
        p: Planned = ev.data
        dlv = p.delivery
        lines = []
        for _i, item, qty in dlv.lines:
            price = D(item.price)
            if p.variant == "price":
                price = (price * (1 + p.price_pct / 100)).quantize(D("0.01"))
            billed = _round(qty * D("1.15"), item.uom) if p.variant == "qty_over" else qty
            lines.append(Line(item.code, item.desc, item.hsn, billed, item.uom, price, D(item.gst)))
        inv = self._upload(p.uploader, dlv.supplier, p.number, p.at, dlv.po, lines, p.variant)
        self.planned[inv.id] = p
        if p.dup_after_days:
            again = Planned(dlv, p.at + timedelta(days=p.dup_after_days), "duplicate", number=_reformat(p.number),
                            uploader=scenarios.SUPPLIER_EMAIL[dlv.supplier])
            again.lines_override = lines  # type: ignore[attr-defined]
            self.push(again.at, "duplicate", (again, p))

    def on_duplicate(self, ev: Event) -> None:
        again, original = ev.data
        inv = self._upload(again.uploader, again.delivery.supplier, again.number, original.at, again.delivery.po,
                           again.lines_override, original.variant if original.variant in ("tax", "no_qr") else "clean")
        self.planned[inv.id] = again
        self.counts["history_duplicates"] += 1

    def on_s5_original(self, ev: Event) -> None:
        spec = scenarios.s5_original(self.db, clock.today())
        inv = self._upload_spec(scenarios.SUPPLIER_EMAIL["V100103"], "V100103", spec, "INV-0042.pdf")
        self.planned[inv.id] = Planned(Delivery(spec.po_number, "V100103", False, [], ev.at), ev.at, "clean")

    def _upload(self, email: str, code: str, number: str, at: datetime, po: str, lines: list[Line],
                variant: str) -> Invoice:
        buyer, sup = scenarios.parties(self.db)
        inv_date = (at - timedelta(days=self.rng.randint(0, 2))).astimezone(clock.IST).date()
        spec = scenarios.spec_for(buyer, sup[code], number, inv_date, po, lines, force_igst=True if variant == "tax" else None)
        if self.suppliers[code].e_invoice_applicable and variant != "no_qr":
            spec = with_einvoice(spec)
        return self._upload_spec(email, code, spec, f"{number.replace('/', '-')}.pdf")

    def _upload_spec(self, email: str, code: str, spec, filename: str) -> Invoice:
        user = self.act_as(email)
        pdf = render_invoice_pdf(spec)
        extracted = parse(text_layer_tokens(pdf), "text")
        qr = QrResult("none")
        if spec.signed_qr:
            qr = QrResult("valid", json.loads(jwt.decode(spec.signed_qr, options={"verify_signature": False})["data"]))
        inv = create_invoice(self.db, user, self.suppliers[code], Ingested(
            filename=filename, data=pdf, kind="pdf", mime="application/pdf", pages=1, sha256=sha256(pdf), phash=None,
            extracted=extracted, ai_mode="offline", ai_fallback=None, quarantined=None, qr=qr))
        self.counts["history_invoices"] += 1
        return inv

    def on_override(self, ev: Event) -> None:
        inv_id, code = ev.data
        inv = self.db.get(Invoice, inv_id)
        if inv.status != InvoiceStatus.FLAGGED:
            return
        clerk = self.act_as(self.rng.choice(CLERKS))
        text = self.rng.choice(JUSTIFICATIONS.get(code, JUSTIFICATIONS["PRICE_VARIANCE"]))
        try:
            approvals.override_flag(self.db, inv, clerk, text.format(d=f"{clock.today() - timedelta(days=3):%d %b}"))
        except approvals.ApprovalError:
            self.db.rollback()

    def on_approve(self, ev: Event) -> None:
        inv_id, step_id = ev.data
        inv = self.db.get(Invoice, inv_id)
        step = approvals.current_step(self.db, inv_id)
        if step is None or step.id != step_id or inv.status != InvoiceStatus.PENDING_APPROVAL:
            return
        user = self.act_as(APPROVER[step.level])
        try:
            if inv.override_justification and step.level == 1 and self.rng.random() < 0.2:
                approvals.reject(self.db, inv, user, self.rng.choice(REJECTIONS))
                return
            code = pyotp.TOTP(decrypt_str(user.mfa_secret_enc)).now() if approvals.mfa_required(self.db, inv) else None
            comment = self.rng.choice(["", "", "OK as per PO and GR.", "Checked against the contract rate."])
            approvals.approve(self.db, inv, user, comment, code)
        except approvals.ApprovalError:
            self.db.rollback()

    def on_payment_run(self, ev: Event) -> None:
        user = self.act_as(APPROVER[1])
        pl = payrun.plan(self.db)
        ids = [i.invoice_id for i in pl.items if i.pay]
        if not ids:
            return
        try:
            payrun.release(self.db, user, ids)
            self.counts["history_payment_runs"] += 1
        except payrun.PaymentError:
            self.db.rollback()

    def on_bank_request(self, ev: Event) -> None:
        user = self.act_as(scenarios.SUPPLIER_EMAIL["V100105"])
        bank_changes.request_change(self.db, user, "60218844310957", "SHYG0742210", "Sahyog Bank (fictional), Panvel",
                                    "Our account moved to the Panvel branch after the office relocation.")

    def on_bank_propose(self, ev: Event) -> None:
        r = self.db.scalar(select(BankChangeRequest).order_by(BankChangeRequest.id.desc()))
        clerk = self.act_as(CLERKS[1])
        bank_changes.propose(self.db, r, clerk, {k: True for k in bank_changes.CHECKLIST},
                             "Swati Kamat (accounts), on the number in the vendor master",
                             "Cancelled cheque of the new account received by courier.")

    def on_bank_approve(self, ev: Event) -> None:
        r = self.db.scalar(select(BankChangeRequest).order_by(BankChangeRequest.id.desc()))
        user = self.act_as(APPROVER[1])
        bank_changes.approve(self.db, r, user, "Call-back and bank letter verified.")

    # ---------------------------------------------------------------- reactions
    def _follow_up(self, at: datetime) -> None:
        """After every event: approvers pick up newly opened steps; clerks look at new flags."""
        for step in self.db.scalars(select(ApprovalStep).where(ApprovalStep.status == StepStatus.PENDING)):
            if step.id in self.scheduled_steps or approvals.current_step(self.db, step.invoice_id).id != step.id:
                continue
            self.scheduled_steps.add(step.id)
            # Approvers batch their queue: same day to a few days; ~8% miss the 48 h SLA (escalation).
            hours = self.rng.choice([3, 6, 20, 26, 30, 44, 50, 70]) if self.rng.random() > 0.08 \
                else self.rng.randint(60, 100)
            self.push(self.office(at + timedelta(hours=hours)), "approve", (step.invoice_id, step.id))
        recent = at > self.now - timedelta(days=12)
        for inv in self.db.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.FLAGGED)):
            if inv.id in self.handled_flags:
                continue
            self.handled_flags.add(inv.id)
            flags = [r.code for r in latest_match(self.db, inv.id).reasons if r.severity == Severity.FLAG]
            code = next((c for c in flags if c in JUSTIFICATIONS), "PRICE_VARIANCE")
            # Most flags are cleared within a few working days; recent ones are still on the clerk's desk.
            if self.rng.random() < (0.45 if recent else 0.9):
                self.push(self.office(at + timedelta(hours=self.rng.randint(20, 100))), "override", (inv.id, code))


def _round(q: D, uom: str) -> D:
    return q.quantize(D("0.1")) if uom == "MT" else q.quantize(D(1))


def _reformat(number: str) -> str:
    """How a resubmitted copy's number tends to differ: separators changed, leading zeros dropped."""
    if number.startswith("INV/"):
        return "INV-" + str(int(number[4:]))
    return number.replace("/", "-") if "/" in number else number.replace("-", "/")


def seed_history(db: Session) -> dict[str, int]:
    return History(db, clock.now()).run()
