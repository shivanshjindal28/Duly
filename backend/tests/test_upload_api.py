import pytest

from app.core.ratelimit import limiter
from app.samples.invoice_pdf import render_invoice_pdf
from tests.fixtures.invoices import seeded_invoice

KESAR = "invoices@kesar-spares.example"
NAVRANG = "accounts@navrang-pack.example"
CLERK = "asha.kulkarni@plantx.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


@pytest.fixture(scope="module")
def pdf():
    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        return render_invoice_pdf(seeded_invoice(db))
    finally:
        db.close()


def upload(client, headers, pdf, name="invoice.pdf", **form):
    return client.post("/api/invoices/upload", headers=headers,
                       files={"file": (name, pdf, "application/pdf")}, data=form)


def test_supplier_upload_extracts_fields_with_locations(client, pdf):
    r = upload(client, login(client, KESAR), pdf)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["invoice_number"] == "KES/26-27/0042"
    assert body["supplier_name"] == "Kesar Engineering Spares"
    assert len(body["lines"]) == 2
    # Seeded PO 4500001003: 100 bearings billed, only 80 received -> blocked by the rules.
    assert body["status"] == "blocked" and body["decision"] == "BLOCK"
    reasons = {(r["code"], r["severity"]) for r in body["match"]["reasons"]}
    assert reasons == {("QTY_EXCEEDS_GR", "block")}
    q = next(r for r in body["match"]["reasons"] if r["code"] == "QTY_EXCEEDS_GR")
    assert q["evidence"]["received"] == "80.000" and q["sap_equivalent"].startswith("Payment block R")
    assert len(body["match"]["matrix"]) == 2
    assert body["bank_account_masked"].startswith("XXXXXX")
    fields = {f["field"]: f for f in body["fields"]}
    assert fields["total"]["value"] == "87320.00" and fields["total"]["bbox"]
    assert fields["bank_account"]["value"].startswith("XXXX")  # the extraction log is masked
    assert body["document"]["sha256"] and body["document"]["pages"] == 1

    page = client.get(f"/api/invoices/{body['id']}/pages/1.png")
    assert page.status_code == 200 and page.content[:4] == b"\x89PNG"


def test_other_supplier_cannot_see_document(client, pdf):
    inv = upload(client, login(client, KESAR), pdf).json()
    login(client, NAVRANG)
    assert client.get(f"/api/invoices/{inv['id']}/document").status_code == 404
    assert client.get(f"/api/invoices/{inv['id']}/pages/1.png").status_code == 404


def test_clerk_uploads_on_behalf_supplier_resolved_by_gstin(client, pdf):
    r = upload(client, login(client, CLERK), pdf)
    assert r.status_code == 201
    assert r.json()["supplier_name"] == "Kesar Engineering Spares"


def test_rejected_upload_returns_reason(client, pdf):
    r = upload(client, login(client, KESAR), pdf, name="invoice.png")
    assert r.status_code == 422 and "does not match" in r.json()["detail"]


@pytest.mark.parametrize("email", ["imran.shaikh@plantx.example", "meera.iyer@plantx.example",
                                   "rohan.mehta@plantx.example"])
def test_only_suppliers_and_clerks_upload(client, pdf, email):
    assert upload(client, login(client, email), pdf).status_code == 403
