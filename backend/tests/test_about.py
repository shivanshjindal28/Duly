"""About pages: architecture doc + system status, trust evidence, scenario assumptions."""
from __future__ import annotations

import pytest

from app.core.config import REPO_ROOT
from app.core.ratelimit import limiter


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def test_architecture_page_serves_the_docs_file_and_status(client):
    client.post("/api/auth/demo-login", json={"email": "sanjay.patil@plantx.example"})
    body = client.get("/api/architecture").json()
    assert body["markdown"] == (REPO_ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert body["markdown"].count("```mermaid") >= 2
    s = body["status"]
    assert s["db"] == "ok" and s["audit_chain_ok"] is True and s["policy_version"] == 1
    assert s["ai_mode"] in ("live", "cached", "offline") and s["ocr"] in ("loaded", "ready")


def test_trust_evidence_shows_ai_never_decides(client):
    client.post("/api/auth/demo-login", json={"email": "meera.iyer@plantx.example"})
    t = client.get("/api/trust").json()
    assert t["engine"]["ai_decided"] == 0
    assert t["data"]["synthetic"] is True and t["data"]["bank_accounts_encrypted"] == 7
    assert t["audit"]["ok"] is True and t["access"]["users_by_role"]["approver"] == 3


def test_assumptions_come_from_policy_and_master_data(client):
    client.post("/api/auth/demo-login", json={"email": "asha.kulkarni@plantx.example"})
    a = client.get("/api/assumptions").json()
    assert a["policy"]["data"]["doa"]["touchless_max_inr"] == 50_000
    assert len(a["suppliers"]) == 7 and any(s["e_invoice"] for s in a["suppliers"])
    assert any(h["code"] == "8482" for h in a["hsn"])


def test_about_pages_are_staff_only(client):
    for email in ("invoices@kesar-spares.example", "imran.shaikh@plantx.example"):
        client.post("/api/auth/demo-login", json={"email": email})
        for path in ("/api/architecture", "/api/trust", "/api/assumptions"):
            assert client.get(path).status_code == 403, (email, path)
