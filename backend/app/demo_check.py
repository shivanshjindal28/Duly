"""The full demo as a checklist: reset with history, run the 12 scenarios through the API,
play each follow-up, verify the audit chain, check the chatbot's offline fallback.

Used by `scripts/demo_check.py` (green/red table before going on stage) and by
`tests/test_zzz_demo_scenarios.py`. Every step records a Check instead of stopping, so one
failure does not hide the others; steps that depend on a failed one are marked skipped.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal as D
from pathlib import Path

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.core.crypto import decrypt_str
from app.core.guard import reset_budgets
from app.core.ratelimit import limiter
from app.models import ApprovalStep, AuditEvent, Invoice, Payment, PurchaseOrder, ReasonCode, User

DEMO = REPO_ROOT / "demo"
CLERK, STORES, AUDITOR, ADMIN = ("asha.kulkarni@plantx.example", "imran.shaikh@plantx.example",
                                 "meera.iyer@plantx.example", "sanjay.patil@plantx.example")
L1, L2 = "rohan.mehta@plantx.example", "kavita.desai@plantx.example"
KESAR = "invoices@kesar-spares.example"


@dataclass
class Check:
    id: str
    name: str
    ok: bool | None  # None = skipped
    detail: str = ""


class DemoCheck:
    def __init__(self, client: TestClient, db: Session, manifest_path: Path = DEMO / "manifest.json"):
        self.client, self.db = client, db
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.checks: list[Check] = []
        self.inv: dict[str, dict] = {}  # scenario id -> invoice detail after upload

    # ------------------------------------------------------------------ helpers
    def login(self, email: str) -> dict:
        limiter.reset()  # one in-process client logs in many times
        reset_budgets()
        r = self.client.post("/api/auth/demo-login", json={"email": email})
        assert r.status_code == 200, f"demo login {email}: {r.status_code}"
        return {"X-CSRF-Token": self.client.cookies.get("duly_csrf")}

    def totp(self, email: str) -> str:
        u = self.db.scalar(select(User).where(User.email == email))
        return pyotp.TOTP(decrypt_str(u.mfa_secret_enc)).now()

    def step(self, cid: str, name: str, fn: Callable[[], str], needs: tuple[str, ...] = ()) -> bool:
        failed = [n for n in needs if not self.passed(n)]
        if failed:
            self.checks.append(Check(cid, name, None, f"skipped: needs {', '.join(failed)}"))
            return False
        try:
            self.checks.append(Check(cid, name, True, fn() or ""))
            return True
        except AssertionError as e:
            self.checks.append(Check(cid, name, False, str(e) or "assertion failed"))
        except Exception as e:  # noqa: BLE001 - report, keep going
            self.checks.append(Check(cid, name, False, f"{type(e).__name__}: {e}"))
        return False

    def passed(self, cid: str) -> bool:
        return any(c.id == cid and c.ok for c in self.checks)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def detail(self, sid: str) -> dict:
        self.login(CLERK)
        return self.client.get(f"/api/invoices/{self.inv[sid]['id']}").json()

    # ------------------------------------------------------------------ the run
    def run(self, reset: bool = True) -> list[Check]:
        if reset:
            self.step("seed", "Reset demo data (admin button, 90-day history)", self._seed)
        self.step("history", "History: KPIs, payments, controls, chain", self._history)
        for sc in self.manifest["scenarios"]:
            self.step(sc["id"], f"{sc['id']} {sc['title']}", lambda sc=sc: self._scenario(sc))
        self.step("S04+", "S04 stores posts GR -> auto re-match releases it", self._s04_gr, ("S04",))
        self.step("S05+", "S05 side-by-side compare with INV/0042", self._s05_compare, ("S05",))
        self.step("S06+", "S06 security alert logged", self._s06_alert, ("S06",))
        self.step("S03+", "S03 supplier credit note -> quantity block released", self._s03_credit, ("S03",))
        self.step("S07+", "S07 hidden text shown to the clerk", self._s07_injection, ("S07",))
        self.step("S12+", "S12 clerk review logged -> matched", self._s12_review, ("S12",))
        self.step("S01+", "S01 L1 then L2 approve with MFA", self._s01_approvals, ("S01",))
        self.step("PAY", "S10/S11 approved -> payment run: MSME first, TDS", self._payment_run, ("S10", "S11"))
        self.step("ERS", "ERS freight: stores posts a trip -> self-billed, touchless", self._ers)
        self.step("MAIL", "Email-in: fetch AP mailbox -> clean, lookalike sender, non-invoice", self._mail)
        self.step("CHAT", "Chatbot offline: answer + cross-supplier refusal", self._chat)
        self.step("AI", "AI kill switch: offline and back", self._ai_switch)
        self.step("CHAIN", "Audit chain verifies; tamper demo detected and restored", self._chain)
        return self.checks

    def _seed(self) -> str:
        h = self.login(ADMIN)
        r = self.client.post("/api/admin/reset-demo", headers=h)
        assert r.status_code == 200, r.text[:200]
        counts = r.json()["counts"]
        assert counts.get("history_invoices", 0) >= 200, counts
        self.login(ADMIN)  # same user ids after the reset: the session survives
        clock = self.client.get("/api/admin/clock").json()
        assert clock["offset_hours"] == 0, clock
        return (f"{counts['history_invoices']} history invoices, {counts['purchase_orders']} POs "
                f"in {r.json()['seconds']:.0f} s")

    def _ai_switch(self) -> str:
        h = self.login(ADMIN)
        before = self.client.get("/api/admin/ai-mode").json()
        r = self.client.post("/api/admin/ai-mode", headers=h, json={"mode": "offline"}).json()
        assert r["effective"] == "offline" and r["overridden"], r
        assert self.client.get("/api/health").json()["ai_mode"] == "offline"
        restore = before["configured"] if before["overridden"] else "default"
        back = self.client.post("/api/admin/ai-mode", headers=h, json={"mode": restore}).json()
        assert back["effective"] == before["effective"], (before, back)
        logged = self.db.scalar(select(func.count()).select_from(AuditEvent)
                                .where(AuditEvent.action == "demo.ai_mode_changed"))
        assert logged >= 2, "AI mode changes not audited"
        return f"offline, then back to {back['effective']}; both changes audited"

    def _history(self) -> str:
        invoices = self.db.scalars(select(Invoice)).all()
        status = Counter(i.status for i in invoices)
        assert len(invoices) >= 200 and status["paid"] > 100, f"{len(invoices)} invoices, {dict(status)}"
        assert all(i.decision for i in invoices), "an invoice without an engine decision"
        assert self.db.scalar(select(func.count()).select_from(PurchaseOrder)) >= 55
        bank = self.db.scalar(select(func.count()).select_from(ReasonCode).where(ReasonCode.code == "BANK_MISMATCH"))
        assert bank == 0, "a history invoice is blocked for BANK_MISMATCH"
        s5 = self.db.scalar(select(Invoice).where(Invoice.invoice_number == "INV/0042"))
        assert s5 is not None and s5.status == "approved", "INV/0042 (S5 original) missing or not approved"
        steps = self.db.scalars(select(ApprovalStep).where(ApprovalStep.invoice_id == s5.id)).all()
        assert [s.by_policy for s in steps] == ["P-01"], "INV/0042 should be touchless (P-01)"
        assert all(p.utr.startswith("DULYN") for p in self.db.scalars(select(Payment)))
        self.login(CLERK)
        k = self.client.get("/api/dashboard/summary").json()["kpis"]
        assert 0.15 <= (k["touchless_rate"] or 0) <= 0.5, f"touchless {k['touchless_rate']}"
        assert k["in_queue"] >= 5 and k["duplicates_prevented"] >= 1, k
        self.login(AUDITOR)
        assert self.client.get("/api/audit/verify").json()["ok"], "audit chain broken after seeding"
        rep = self.client.get("/api/reports/controls?from=2026-01-01&to=2027-12-31").json()
        results = {c["id"]: c["result"] for c in rep["controls"]}
        assert "no_activity" not in results.values(), results
        return (f"{len(invoices)} invoices ({status['paid']} paid), touchless {k['touchless_rate']:.0%}, "
                f"cycle {k['avg_cycle_hours'] / 24:.1f} d, {k['duplicates_prevented']} duplicates caught")

    def _scenario(self, sc: dict) -> str:
        h = self.login(sc["upload_as"])
        path = DEMO / sc["file"]
        r = self.client.post("/api/invoices/upload", headers=h,
                             files={"file": (path.name, path.read_bytes(), sc["mime"])})
        assert r.status_code == 201, f"upload {r.status_code}: {r.text[:200]}"
        inv = r.json()
        self.inv[sc["id"]] = inv
        exp = sc["expected"]
        codes = [x["code"] for x in inv["match"]["reasons"] if x["severity"] != "info" or x["code"] in exp["reason_codes"]]
        got = f"{inv['decision']} / {inv['status']} {codes}"
        if exp["decision"]:
            assert inv["decision"] == exp["decision"], f"expected {exp['decision']}, got {got}"
        assert inv["status"] == exp["status"], f"expected status {exp['status']}, got {got}"
        missing = set(exp["reason_codes"]) - {x["code"] for x in inv["match"]["reasons"]}
        assert not missing, f"missing {sorted(missing)}; got {got}"
        assert "POSSIBLE_DUPLICATE" not in codes, f"unexpected POSSIBLE_DUPLICATE: {got}"
        reasons = {x["code"]: x for x in inv["match"]["reasons"]}
        if "total" in exp:
            assert D(inv["total"]) == D(exp["total"]), f"total {inv['total']}"
        if "approval_levels" in exp and inv["status"] == "pending_approval":
            assert [s["level"] for s in inv["workflow"]["steps"]] == exp["approval_levels"], inv["workflow"]["steps"]
        if exp.get("mfa_required"):
            assert inv["workflow"]["mfa_required"], "MFA should be required"
        if "variance_amount" in exp:
            got_v = reasons["PRICE_VARIANCE"]["evidence"]["variance_amount"]
            assert D(got_v) == D(exp["variance_amount"]), f"variance {got_v}"
        if "duplicate_of" in exp:
            assert reasons["DUPLICATE"]["evidence"]["duplicate_of"] == exp["duplicate_of"]
        if "currency" in exp:
            assert inv["currency"] == exp["currency"], f"currency {inv['currency']}"
        if "total_inr" in exp:
            assert D(inv["total_inr"]) == D(exp["total_inr"]), f"INR equivalent {inv['total_inr']}"
        if "converted_qty" in exp:
            row = inv["match"]["matrix"][0]
            assert D(str(row["invoice_qty"])) == D(exp["converted_qty"]) and row["invoice_uom"] != row["uom"], row
        if "printed_total" in exp:
            assert D(inv["total"]) == D(exp["printed_total"])
            signed = reasons["QR_MISMATCH"]["evidence"]["signed"]["TotInvVal"]
            assert D(str(signed)) == D(exp["signed_total"]), f"signed total {signed}"
        extra = " (review pending)" if inv["status"] == "needs_review" else ""
        return f"{inv['decision']} {', '.join(codes) or 'clean'}{extra}"

    def _s04_gr(self) -> str:
        h = self.login(STORES)
        po = next(p for p in self.client.get("/api/stores/open-pos").json() if p["po_number"] == "4500001004")
        r = self.client.post("/api/stores/goods-receipts", headers=h, json={
            "po_number": "4500001004", "lines": [{"po_line_id": po["lines"][0]["id"], "qty": str(po["lines"][0]["open"])}]})
        assert r.status_code == 201, r.text[:200]
        d = self.detail("S04")
        assert d["decision"] == "APPROVE" and d["status"] == "pending_approval", (d["decision"], d["status"])
        return f"GR {r.json().get('number', '')} -> APPROVE, routed to approval"

    def _s03_credit(self) -> str:
        iid = self.inv["S03"]["id"]
        h = self.login(KESAR)
        d = self.client.get(f"/api/invoices/{iid}").json()
        s = d["credit_suggestion"]
        assert d["can_issue_credit"] and len(s) == 1 and D(s[0]["qty"]) == 20, s
        r = self.client.post(f"/api/invoices/{iid}/credit-notes", headers=h, json={
            "number": "CN/0071", "note_date": d["invoice_date"], "reason": "20 bearings not delivered",
            "lines": [{"line_no": s[0]["line_no"], "qty": s[0]["qty"]}]})
        assert r.status_code == 201, r.text[:200]
        d = r.json()
        assert d["decision"] == "APPROVE" and d["status"] == "pending_approval", (d["decision"], d["status"])
        assert D(d["total"]) - D(d["net_total"]) == D(s[0]["total"]), (d["total"], d["net_total"])
        return (f"CN/0071 credits 20 bearings Rs {s[0]['total']}: APPROVE, routed on the net "
                f"Rs {d['net_total']} (invoice Rs {d['total']})")

    def _mail(self) -> str:
        h = self.login(CLERK)
        r = self.client.post("/api/inbox/fetch", headers=h)
        assert r.status_code == 200 and r.json()["fetched"] == 3, r.text[:200]
        emails = {e["sender_status"]: e for e in self.client.get("/api/inbox").json()["emails"]
                  if e["status"] != "rejected"}
        clean = self.client.get(f"/api/invoices/{emails['verified']['attachments'][0]['invoice_id']}").json()
        fake = self.client.get(f"/api/invoices/{emails['lookalike']['attachments'][0]['invoice_id']}").json()
        assert clean["decision"] == "APPROVE" and clean["status"] == "approved", (clean["decision"], clean["status"])
        assert fake["decision"] == "FLAG" and any(x["code"] == "EMAIL_SENDER_UNVERIFIED"
                                                   for x in fake["match"]["reasons"]), fake["decision"]
        return (f"{clean['invoice_number']} APPROVE touchless; {fake['invoice_number']} from "
                f"{emails['lookalike']['from_addr']} FLAG; statement .xlsx rejected")

    def _ers(self) -> str:
        h = self.login(STORES)
        po = next(p for p in self.client.get("/api/stores/open-pos").json() if p["po_number"] == "4500001015")
        assert po["ers"], po
        r = self.client.post("/api/stores/service-entries", headers=h, json={
            "po_number": "4500001015", "po_line_id": po["lines"][0]["id"], "value": "22000.00"})
        assert r.status_code == 201 and r.json()["ers_settled"], r.text[:200]
        inv = self.db.scalar(select(Invoice).where(Invoice.invoice_number == f"ERS-{r.json()['number']}"))
        assert inv is not None and inv.origin == "ers", "no ERS settlement created"
        assert inv.total == D("24640.00") and inv.status == "approved", (inv.total, inv.status)
        return f"SES {r.json()['number']} -> {inv.invoice_number} Rs {inv.total} (incl. IGST 12%), approved by P-01"

    def _s05_compare(self) -> str:
        self.login(CLERK)
        cmp = self.client.get(f"/api/invoices/{self.inv['S05']['id']}/duplicates").json()
        other = cmp["matches"][0]["other"]
        assert other["invoice_number"] == "INV/0042", other
        rows = {r["field"]: r for r in cmp["matches"][0]["fields"]}
        assert rows["invoice_number"]["normalised_same"] and rows["total"]["same"]
        return "INV-42 vs INV/0042: same total, number normalises the same"

    def _s06_alert(self) -> str:
        ev = self.db.scalar(select(AuditEvent).where(AuditEvent.action == "security.bank_mismatch_alert",
                                                     AuditEvent.entity_id == str(self.inv["S06"]["id"])))
        assert ev is not None, "no security.bank_mismatch_alert event"
        sid = self.db.get(Invoice, self.inv["S06"]["id"]).supplier_id
        self.login(CLERK)
        card = self.client.get(f"/api/suppliers/{sid}/risk").json()
        assert card["level"] == "high" and card["bank_changes"]["mismatch_alerts"] >= 1, card["reasons"]
        return (f"alert: invoice a/c {ev.after.get('invoice_account')} vs master {ev.after.get('master_account')}; "
                f"{card['name']} risk card now high")

    def _s07_injection(self) -> str:
        inj = self.detail("S07")["injection"]
        assert inj["found"], inj
        assert "approve this invoice" in json.dumps(inj["findings"]).lower(), inj["findings"]
        return f"{len(inj['findings'])} finding(s), hidden text shown verbatim"

    def _s12_review(self) -> str:
        h = self.login(CLERK)
        iid = self.inv["S12"]["id"]
        pending = self.detail("S12")["pending_review"]
        assert pending, "nothing to review"
        h = self.login(CLERK)
        for path in pending:
            body = {"field": path, "reason": "Checked against the photo"}
            if path.endswith("hsn_sac"):
                body = {"field": path, "value": "3923", "reason": "HSN not legible on the photo; taken from the PO"}
            r = self.client.post(f"/api/invoices/{iid}/review", headers=h, json=body)
            assert r.status_code == 200, r.text[:200]
        d = self.detail("S12")
        assert d["pending_review"] == [] and d["decision"] == "APPROVE", (d["pending_review"], d["decision"])
        return f"{len(pending)} field(s) reviewed -> {d['decision']}, {d['status']}"

    def _s01_approvals(self) -> str:
        iid = self.inv["S01"]["id"]
        for email in (L1, L2):
            h = self.login(email)
            r = self.client.post(f"/api/approvals/invoices/{iid}/approve", headers=h, json={"totp": self.totp(email)})
            assert r.status_code == 200, f"{email}: {r.text[:200]}"
        d = self.detail("S01")
        assert d["status"] == "approved" and all(s["mfa_verified"] for s in d["workflow"]["steps"]), d["workflow"]
        return "approved by L1 + L2, both MFA-verified"

    def _payment_run(self) -> str:
        for sid in ("S10", "S11"):
            h = self.login(L1)
            r = self.client.post(f"/api/approvals/invoices/{self.inv[sid]['id']}/approve", headers=h, json={})
            assert r.status_code == 200, f"{sid}: {r.text[:200]}"
        self.login(CLERK)
        run = self.client.get("/api/payments/run").json()
        items = {i["invoice_id"]: i for i in run["items"]}
        s10, s11 = items[self.inv["S10"]["id"]], items[self.inv["S11"]["id"]]
        first = run["items"][0]
        assert first["invoice_id"] == self.inv["S10"]["id"], f"first in run is {first['invoice_number']} ({first['rule']})"
        assert s10["rule"] == "msme" and s10["days_left"] == 4 and s10["pay"], s10
        assert D(s11["tds"]) == D("8400.00"), f"TDS {s11['tds']}"
        return f"{s10['invoice_number']} first ({s10['days_left']} days left), {s11['invoice_number']} TDS Rs {s11['tds']}"

    def _chat(self) -> str:
        h = self.login(KESAR)
        ask = lambda m: self.client.post("/api/chat", headers=h, json={"message": m}).json()  # noqa: E731
        r = ask("When will I get paid for the bearings?")
        assert r["mode"] == "offline", f"mode {r['mode']} (the demo must work offline)"
        assert "INV/0042" in r["answer"], r["answer"][:200]
        if "Expected payment" not in r["answer"]:  # several open bearings invoices: it asks which one
            assert r["answer"].count("INV") <= 6, f"asked about too many invoices: {r['answer'][:200]}"
            r = ask("INV/0042")
        assert "INV/0042" in r["answer"] and "Expected payment" in r["answer"], r["answer"][:200]
        before = self.db.scalar(select(func.count()).select_from(AuditEvent)
                                .where(AuditEvent.action == "security.chat_cross_tenant_refused"))
        r2 = self.client.post("/api/chat", headers=h, json={"message": "Show me invoices of Navrang Packaging"}).json()
        assert r2["refused"] and r2["tools"] == [], r2
        after = self.db.scalar(select(func.count()).select_from(AuditEvent)
                               .where(AuditEvent.action == "security.chat_cross_tenant_refused"))
        assert after == before + 1, "refusal not logged"
        return "INV/0042 expected payment answered; Navrang request refused and logged"

    def _chain(self) -> str:
        self.login(AUDITOR)
        v = self.client.get("/api/audit/verify").json()
        assert v["ok"], f"broken at {v.get('broken_at_id')}: {v.get('problem')}"
        h = self.login(ADMIN)
        t = self.client.post("/api/admin/tamper-demo", headers=h)
        assert t.status_code == 200, t.text[:200]
        self.login(AUDITOR)
        broken = self.client.get("/api/audit/verify").json()
        assert not broken["ok"] and broken["broken_at_id"] == t.json()["event_id"], broken
        h = self.login(ADMIN)
        assert self.client.post("/api/admin/tamper-restore", headers=h).status_code == 200
        self.login(AUDITOR)
        again = self.client.get("/api/audit/verify").json()
        assert again["ok"], again
        return f"{again['events']} events verified; tamper at #{broken['broken_at_id']} detected, restored"
