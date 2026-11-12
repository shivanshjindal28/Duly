"""Policy changes: admin only, validated, versioned, audited; old versions kept."""
from __future__ import annotations

from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.core.ratelimit import limiter
from app.models import AuditEvent, Policy
from app.workflow.approvals import required_levels
from app.workflow.matching import active_policy

ADMIN = "sanjay.patil@plantx.example"
CLERK = "asha.kulkarni@plantx.example"
AUDITOR = "meera.iyer@plantx.example"


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def login(client, email):
    assert client.post("/api/auth/demo-login", json={"email": email}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("duly_csrf")}


def post(client, h, changes, reason="Quarterly tolerance review by finance"):
    return client.post("/api/policy", headers=h, json={"changes": changes, "reason": reason})


def test_read_access_and_refusals(client):
    login(client, AUDITOR)
    r = client.get("/api/policy")
    assert r.status_code == 200
    j = r.json()
    assert j["can_edit"] is False and j["values"]["tolerances.PP.flag_pct"] is not None
    assert any(s["value"] == 45 for s in j["statutory"])  # MSME cap is shown, not editable
    h = login(client, CLERK)
    assert post(client, h, {"tolerances.PP.flag_pct": 2}).status_code == 403
    login(client, "invoices@kesar-spares.example")
    assert client.get("/api/policy").status_code == 403

    h = login(client, ADMIN)
    assert post(client, h, {"tolerances.PP.flag_pct": 2}, reason="short").status_code == 422
    assert post(client, h, {"tolerances.PP.flag_pct": 99}).status_code == 422  # out of range
    r = post(client, h, {"tolerances.PP.flag_pct": 6})  # above the block level
    assert r.status_code == 422 and "block level" in r.json()["detail"]
    assert post(client, h, {"doa.touchless_max_inr": 2_000_000}).status_code == 422  # above L1-only band
    assert post(client, h, {"sla_hours": 12.5}).status_code == 422  # whole hours
    assert post(client, h, {"msme.max_term_days": 60}).status_code == 422  # statutory, not editable
    cur = j["values"]
    assert post(client, h, {"tolerances.PP.flag_pct": cur["tolerances.PP.flag_pct"]}).status_code == 422  # nothing changed


def test_change_creates_new_version_used_by_workflow_and_audited(client, db):
    h = login(client, ADMIN)
    before = client.get("/api/policy").json()
    v0, old = before["version"], before["values"]
    r = post(client, h, {"tolerances.PP.flag_pct": 2, "doa.touchless_max_inr": 40000, "mfa_threshold_inr": 500000})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["version"] == v0 + 1 and j["values"]["tolerances.PP.flag_pct"] == 2.0
    assert j["values"]["doa.touchless_max_inr"] == 40000
    newest = j["history"][0]
    assert newest["active"] and newest["reason"].startswith("Quarterly") and newest["created_by"]
    assert set(newest["changed"]) == {"tolerances.PP.flag_pct", "doa.touchless_max_inr", "mfa_threshold_inr"}

    db.expire_all()
    assert db.scalar(select(Policy).where(Policy.version == v0)).is_active is False
    assert active_policy(db).version == v0 + 1
    # The approval workflow reads the new version: Rs 45,000 is no longer touchless.
    data = active_policy(db).data
    assert D(45000) > D(str(data["doa"]["touchless_max_inr"]))
    assert required_levels(D(45000), data, override=False) == [1]
    ev = db.scalar(select(AuditEvent).where(AuditEvent.action == "policy.changed").order_by(AuditEvent.id.desc()))
    assert ev.after["reason"].startswith("Quarterly") and ev.before["tolerances.PP.flag_pct"] == old["tolerances.PP.flag_pct"]

    # Put the original values back (as another version) so later tests see the defaults.
    r = post(client, h, {k: old[k] for k in ("tolerances.PP.flag_pct", "doa.touchless_max_inr", "mfa_threshold_inr")},
             reason="Restore defaults after the test")
    assert r.status_code == 200 and r.json()["version"] == v0 + 2
    assert r.json()["values"] == old
