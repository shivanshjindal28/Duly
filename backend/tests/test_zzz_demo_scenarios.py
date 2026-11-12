"""The demo as it will be shown (same steps as `scripts/demo_check.py`, see app/demo_check.py).

Runs last: it reseeds the shared test database with the 90-day history, uploads the 12
git-tracked scenario files from demo/manifest.json, plays every follow-up and checks the chat
fallback and the audit chain.
"""
from __future__ import annotations

from app.demo_check import DemoCheck


def test_demo_check_is_all_green(client, db):
    checks = DemoCheck(client, db).run()  # resets with history via the admin endpoint
    failed = [c for c in checks if not c.ok]
    assert len(checks) >= 24
    assert not failed, "\n".join(f"{c.name}: {c.detail}" for c in failed)
