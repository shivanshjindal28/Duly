"""Duplicate detection (B1): unit tests per signal + scenario 5 end to end."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.core.ratelimit import limiter
from app.duplicates.detector import DupView, assess, jaccard, phash_distance
from app.ingestion.pipeline import normalise_invoice_number
from app.samples.invoice_pdf import Line, render_invoice_pdf
from tests.fixtures.invoices import seeded_invoice

G = "24ABCDE1234F1Z5"


def view(i, number="INV-42", **kw) -> DupView:
    base = dict(invoice_id=i, invoice_number=number, number_norm=normalise_invoice_number(number), supplier_id=1,
                supplier_gstin=G, fiscal_year="2026-27", irn=None, sha256=f"sha{i}", phash=None, total=D("53100.00"),
                invoice_date=date(2026, 11, 5), lines=(("BRG-6205", D(100)),), bank_account="1111222233334444")
    base.update(kw)
    return DupView(**base)


def codes(new, earlier):
    return {r.code: r.severity.value for r in assess(new, earlier)[1]}


def test_normalised_number_same_fy_blocks():
    assert codes(view(2, "INV/0042"), [view(1, "INV-42")]) == {"DUPLICATE": "block"}


def test_same_number_other_fy_or_other_supplier_is_not_exact():
    assert "DUPLICATE" not in codes(view(2, fiscal_year="2027-28", invoice_date=date(2027, 5, 1)), [view(1)])
    assert codes(view(2, supplier_id=2, supplier_gstin="27ZZZZZ9999Z1Z9", bank_account=None), [view(1)]) == {}


def test_same_irn_and_same_file_block():
    assert codes(view(2, "X-9", irn="ab" * 32), [view(1, "Y-1", irn="ab" * 32)])["DUPLICATE"] == "block"
    assert codes(view(2, "X-9", sha256="same"), [view(1, "Y-1", sha256="same")])["DUPLICATE"] == "block"


def test_near_duplicate_flags_but_different_items_do_not():
    new = view(2, "KES-99", total=D("53150.00"), invoice_date=date(2026, 11, 20))
    assert codes(new, [view(1)]) == {"POSSIBLE_DUPLICATE": "flag"}
    other_items = view(2, "KES-99", lines=(("SEAL-M40", D(4)),))
    assert codes(other_items, [view(1)]) == {}


def test_visual_alone_never_flags_but_corroborates():
    alike = dict(phash="ffffffffffffffff")
    assert codes(view(2, "Z-1", total=D("99.00"), lines=(), **alike), [view(1, lines=(), **alike)]) == {}
    matches, _ = assess(view(2, "Z-2", total=D("53150.00"), **alike), [view(1, **alike)])
    assert {s.name for s in matches[0].signals} == {"near_match", "visual"} and matches[0].probability > 0.8


def test_bank_account_shared_with_another_supplier():
    other = view(1, "A-1", supplier_id=7, supplier_gstin="27ZZZZZ9999Z1Z9")
    assert codes(view(2, "B-1"), [other]) == {"BANK_ACCOUNT_SHARED": "flag"}


def test_helpers():
    assert phash_distance("ff", "fe") == 1 and phash_distance(None, "ff") is None
    assert jaccard((("A", D(1)),), (("a", D("1.000")),)) == 1.0


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def test_s5_bearings_resubmitted_as_photo_with_reformatted_number(client, db):
    """Scenario 5: 'INV/0042' resubmitted as 'INV-42' (as a photo) is blocked with side-by-side evidence."""
    import io

    from app.ingestion.extract_text import render_pages

    # PO 4500001013 (FFS bags, 5000 received) is not used by any other test, so quantities stay open.
    lines = [Line("PKG-FFS-50", "FFS bag 50 kg PE", "3923", D(1000), "NOS", D("21.00"), D(18))]
    nav = "Navrang Packaging Works"
    assert client.post("/api/auth/demo-login", json={"email": "accounts@navrang-pack.example"}).status_code == 200
    h = {"X-CSRF-Token": client.cookies.get("duly_csrf")}
    first_pdf = render_invoice_pdf(seeded_invoice(db, nav, invoice_number="INV/0042", invoice_date=date(2026, 11, 3),
                                                  po_number="4500001013", lines=lines))
    first = client.post("/api/invoices/upload", headers=h, files={"file": ("a.pdf", first_pdf, "application/pdf")}).json()
    assert "DUPLICATE" not in {r["code"] for r in first["match"]["reasons"]}

    second_pdf = render_invoice_pdf(seeded_invoice(db, nav, invoice_number="INV-42", invoice_date=date(2026, 11, 3),
                                                   po_number="4500001013", lines=lines))
    photo = io.BytesIO()
    render_pages(second_pdf, "pdf", dpi=170)[0].save(photo, format="JPEG", quality=85)
    second = client.post("/api/invoices/upload", headers=h,
                         files={"file": ("whatsapp.jpg", photo.getvalue(), "image/jpeg")}).json()
    dup = next(r for r in second["match"]["reasons"] if r["code"] == "DUPLICATE")
    assert second["decision"] == "BLOCK" and dup["evidence"]["duplicate_of_invoice_id"] == first["id"]
    assert "exact_number" in dup["evidence"]["signals"]

    cmp = client.get(f"/api/invoices/{second['id']}/duplicates").json()
    assert cmp["matches"][0]["other"]["id"] == first["id"]
    rows = {r["field"]: r for r in cmp["matches"][0]["fields"]}
    assert rows["total"]["same"] is True and rows["invoice_number"]["same"] is False
    assert rows["invoice_number"]["normalised_same"] is True

    # The dashboard counts it as a duplicate prevented.
    client.post("/api/auth/demo-login", json={"email": "asha.kulkarni@plantx.example"})
    k = client.get("/api/dashboard/summary").json()["kpis"]
    assert k["duplicates_prevented"] >= 1
