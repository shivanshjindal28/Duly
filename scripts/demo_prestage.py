"""Get the stage database ready: optionally reset it (with history), then upload the scenarios
that are not shown live, so the dashboard, payment run and review queue already contain them.

Usage (from the repo root, with or without `python run.py` running):
    python scripts/demo_prestage.py --reset                   # reset + upload the default set
    python scripts/demo_prestage.py --ids S10,S11             # just these, no reset

Default set: S02 S03 S09A S09B S10 S11 S12. The live demo then uploads S01, S04, S05, S06, S07, S08
(see docs/DEMO_SCRIPT.md). Each upload is checked against demo/manifest.json, like demo_check.py.
Uses the configured AI mode (Demo controls / AI_MODE); offline is recommended on stage.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

DEFAULT = ["S02", "S03", "S09A", "S09B", "S10", "S11", "S12"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the stage database for the Duly demo.")
    parser.add_argument("--reset", action="store_true", help="reset with the 90-day history first (~25 s)")
    parser.add_argument("--ids", default=",".join(DEFAULT), help="comma-separated scenario ids from demo/manifest.json")
    parser.add_argument("--snapshot", action="store_true",
                        help="after staging, save a snapshot that 'Reset demo data' restores (used by the hosted demo)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from fastapi.testclient import TestClient

    from app.core.db import SessionLocal
    from app.demo_check import DemoCheck
    from app.main import app
    from app.seed import reset_and_seed

    db = SessionLocal()
    try:
        if args.reset:
            counts = reset_and_seed(db, history=True)
            print(f"Reset: {counts['history_invoices']} history invoices, {counts['purchase_orders']} POs")
        with TestClient(app) as client:
            check = DemoCheck(client, db)
            wanted = [i.strip().upper() for i in args.ids.split(",") if i.strip()]
            scenarios = {s["id"]: s for s in check.manifest["scenarios"]}
            unknown = [i for i in wanted if i not in scenarios]
            if unknown:
                print(f"Unknown scenario ids: {unknown}. Known: {', '.join(scenarios)}")
                return 2
            for sid in wanted:
                sc = scenarios[sid]
                check.step(sid, f"{sid} {sc['title']}", lambda sc=sc: check._scenario(sc))
    finally:
        db.close()
    for c in check.checks:
        print(f" {'OK  ' if c.ok else 'FAIL'} {c.name}: {c.detail}")
    if check.ok and args.snapshot:
        from app import demo_snapshot

        print(f"Snapshot saved: {demo_snapshot.save()}")
    print("Ready. Live: S01, S04, S05, S06, S07, S08 (docs/DEMO_SCRIPT.md)." if check.ok else "Something failed: see above.")
    return 0 if check.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
