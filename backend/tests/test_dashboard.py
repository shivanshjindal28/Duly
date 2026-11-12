"""Exceptions dashboard and work queue: numbers computed from data, filters drill down."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.core.ratelimit import limiter
from app.payments.msme import msme_eligible, statutory_due_date

CLERK = "asha.kulkarni@plantx.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email=CLERK):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200


def test_msme_due_date_rules():
    accepted = date(2026, 10, 1)
    assert statutory_due_date(accepted, 60, True) == accepted + timedelta(days=45)  # capped at 45
    assert statutory_due_date(accepted, 30, True) == accepted + timedelta(days=30)
    assert statutory_due_date(accepted, 30, False) == accepted + timedelta(days=15)  # no written agreement
    assert msme_eligible("micro", "manufacturer") and msme_eligible("small", "services")
    assert not msme_eligible("micro", "trader") and not msme_eligible("none", "manufacturer")


def test_summary_is_consistent_with_queue(client):
    login(client)
    s = client.get("/api/dashboard/summary").json()
    open_rows = client.get("/api/dashboard/queue?status=open").json()
    assert s["kpis"]["in_queue"] >= len(open_rows)
    assert D(s["kpis"]["value_on_hold"]) == sum(D(r["total"]) for r in open_rows)
    assert sum(a["count"] for a in s["by_age"]) == len(open_rows)
    assert sum(r["open_exceptions"] for r in s["by_supplier"]) == len(open_rows)
    # Drill-down: each exception type count equals the filtered queue length.
    for t in s["by_type"]:
        rows = client.get(f"/api/dashboard/queue?status=open&reason={t['code']}").json()
        assert len(rows) == t["count"], t["code"]
    if s["kpis"]["touchless_rate"] is not None:
        assert 0 <= s["kpis"]["touchless_rate"] <= 1


def test_queue_filters_and_roles(client):
    login(client)
    all_rows = client.get("/api/dashboard/queue?status=all").json()
    assert all_rows
    sid = all_rows[0]["supplier_id"]
    assert all(r["supplier_id"] == sid for r in client.get(f"/api/dashboard/queue?status=all&supplier_id={sid}").json())
    assert all(r["age_days"] <= 7 for r in client.get("/api/dashboard/queue?status=all&age=0-7").json())
    login(client, "invoices@kesar-spares.example")
    assert client.get("/api/dashboard/summary").status_code == 403
    login(client, "imran.shaikh@plantx.example")
    assert client.get("/api/dashboard/queue").status_code == 403
