"""Human review of low-confidence fields: confirm, correct (logged before/after), re-match, release."""
from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.core.ratelimit import limiter
from app.models import ExtractionResult, Policy
from app.samples.invoice_pdf import render_invoice_pdf
from tests.fixtures.invoices import seeded_invoice

CLERK = "asha.kulkarni@plantx.example"
KESAR = "invoices@kesar-spares.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


@pytest.fixture
def strict_threshold(db):
    """Raise the confidence threshold above 0.98 so every text-layer field needs review."""
    policy = db.scalar(select(Policy).where(Policy.is_active.is_(True)))
    original = copy.deepcopy(policy.data)
    policy.data = {**policy.data, "confidence_threshold": 0.99}
    db.commit()
    yield
    policy.data = original
    db.commit()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def upload(client, headers, db, **overrides):
    pdf = render_invoice_pdf(seeded_invoice(db, **overrides))
    r = client.post("/api/invoices/upload", headers=headers, files={"file": ("inv.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()


def test_low_confidence_goes_to_review_and_is_released_after_review(client, db, strict_threshold):
    h = login(client, KESAR)
    inv = upload(client, h, db)
    assert inv["status"] == "needs_review"
    assert inv["match"]["decision"] == "BLOCK"  # decision computed, but not applied until review is done
    assert len(inv["pending_review"]) > 10

    h = login(client, CLERK)
    # Correct the bearings quantity to what was actually received: the block should go away.
    r = client.post(f"/api/invoices/{inv['id']}/review", headers=h,
                    json={"field": "lines[0].qty", "value": "80", "reason": "Supplier confirmed 80 by phone"})
    assert r.status_code == 200, r.text
    body = r.json()
    field = next(f for f in body["fields"] if f["field"] == "lines[0].qty")
    assert (field["value"], field["previous_value"], field["source"]) == ("80", "100", "manual")
    assert field["reviewed_by"] == "Asha Kulkarni" and field["review_reason"] == "Supplier confirmed 80 by phone"
    assert body["status"] == "needs_review"  # other fields still pending

    for path in body["pending_review"]:
        if path == "lines[0].taxable_value":
            payload = {"field": path, "value": "36000.00", "reason": "80 x 450"}
        else:
            payload = {"field": path, "reason": "Checked against the document"}
        assert client.post(f"/api/invoices/{inv['id']}/review", headers=h, json=payload).status_code == 200

    final = client.get(f"/api/invoices/{inv['id']}").json()
    assert final["pending_review"] == []
    assert final["match"]["trigger"] == "review_completed"
    # Taxable total and tax on the document still say 100 bearings: arithmetic no longer adds up.
    codes = {r["code"] for r in final["match"]["reasons"]}
    assert "QTY_EXCEEDS_GR" not in codes and "MATH_ERROR" in codes
    assert final["status"] == "flagged"

    history = db.scalars(select(ExtractionResult).where(ExtractionResult.invoice_id == inv["id"],
                                                        ExtractionResult.field == "lines[0].qty")
                         .order_by(ExtractionResult.id)).all()
    assert [h.source for h in history] == ["text", "manual"] and history[0].corrected


def test_review_requires_reason_and_clerk(client, db):
    h = login(client, KESAR)
    inv = upload(client, h, db)
    r = client.post(f"/api/invoices/{inv['id']}/review", headers=h, json={"field": "total", "reason": "ok fine"})
    assert r.status_code == 403  # suppliers cannot review

    h = login(client, CLERK)
    r = client.post(f"/api/invoices/{inv['id']}/review", headers=h, json={"field": "total", "reason": ""})
    assert r.status_code == 422 and "reason" in r.json()["detail"]
    r = client.post(f"/api/invoices/{inv['id']}/review", headers=h,
                    json={"field": "total", "value": "abc", "reason": "typo"})
    assert r.status_code == 422 and "not a number" in r.json()["detail"]


def test_bank_account_correction_is_masked_in_log(client, db):
    h = login(client, CLERK)
    inv = upload(client, h, db)
    r = client.post(f"/api/invoices/{inv['id']}/review", headers=h,
                    json={"field": "bank_account", "value": "11112222333344", "reason": "Rescanned page"})
    assert r.status_code == 200
    body = r.json()
    f = next(x for x in body["fields"] if x["field"] == "bank_account")
    assert f["value"] == "XXXXXXXXXX3344" and "11112222333344" not in str(body)
    assert body["bank_account_masked"] == "XXXXXX3344"
    assert "BANK_MISMATCH" in {x["code"] for x in body["match"]["reasons"]}
