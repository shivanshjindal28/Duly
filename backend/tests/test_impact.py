"""Impact page data: measured live, assumptions with reasons, staff only."""
from __future__ import annotations

import pytest

from app.core.ratelimit import limiter
from app.reports.impact import ASSUMPTIONS


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def test_impact_measured_and_assumptions(client):
    client.post("/api/auth/demo-login", json={"email": "meera.iyer@plantx.example"})
    r = client.get("/api/impact")
    assert r.status_code == 200
    body = r.json()
    m = body["measured"]
    assert m["invoices"] >= 0 and m["approved"] >= m["touchless"]
    assert m["msme_interest_pct"] == 17.25  # 3 x the policy's RBI bank rate
    keys = [a["key"] for a in body["assumptions"]]
    assert keys == [a["key"] for a in ASSUMPTIONS]
    assert all(a["reason"] and a["value"] is not None for a in body["assumptions"])
    assert "touchless_rate" in body["formulas"]["hours_saved_month"]


def test_impact_is_staff_only(client):
    client.post("/api/auth/demo-login", json={"email": "invoices@kesar-spares.example"})
    assert client.get("/api/impact").status_code == 403
    client.post("/api/auth/demo-login", json={"email": "imran.shaikh@plantx.example"})
    assert client.get("/api/impact").status_code == 403
