"""Controls report (B3): runs late in the suite so every earlier test's data is in the period."""
from __future__ import annotations

import pytest

from app.core.ratelimit import limiter


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email="meera.iyer@plantx.example"):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200


def test_controls_report_tests_every_control_on_live_data(client):
    login(client)
    r = client.get("/api/reports/controls?from=2026-01-01&to=2027-12-31")
    assert r.status_code == 200
    rep = r.json()
    ids = [c["id"] for c in rep["controls"]]
    assert ids == [f"C-{n:02d}" for n in range(1, 11)]
    by = {c["id"]: c for c in rep["controls"]}
    # The suite approved invoices, caught duplicates, refused SoD attempts and kept the chain intact.
    assert by["C-01"]["result"] == "effective" and by["C-01"]["population"] > 0
    assert by["C-02"]["result"] == "effective"
    assert by["C-03"]["metrics"]["caught"] >= 1 and by["C-03"]["result"] == "effective"
    assert by["C-04"]["result"] == "effective" and by["C-04"]["metrics"]["touchless"] >= 1
    assert by["C-05"]["result"] == "effective" and by["C-05"]["metrics"]["sod_refusals_logged"] >= 1
    assert by["C-06"]["result"] == "effective"  # bank changes went through maker-checker (test_bank_changes)
    assert by["C-07"]["result"] == "effective"
    assert by["C-09"]["metrics"]["ai_approvals"] == 0
    assert by["C-10"]["result"] == "effective" and len(by["C-10"]["metrics"]["users"]) == 14
    assert rep["opinion"].startswith("10 controls tested")
    assert any(o["justification"] for o in rep["overrides"])


def test_controls_pdf_and_access(client):
    login(client)
    r = client.get("/api/reports/controls.pdf")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-" and r.headers["content-type"] == "application/pdf"
    assert client.get("/api/reports/controls?from=2026-12-31&to=2026-01-01").status_code == 422
    login(client, "asha.kulkarni@plantx.example")
    assert client.get("/api/reports/controls").status_code == 403
