"""Run the whole demo through the API and print a green/red table. Run it before every push in
Phase 4 and before going on stage.

Usage (from the repo root):
    python scripts/demo_check.py              # isolated temp database, AI offline (default)
    python scripts/demo_check.py --live-db    # use backend/data/duly.db: reset, check, reset again
    python scripts/demo_check.py --ai         # use the configured AI_MODE instead of offline

Steps: reset with the 90-day history, upload the 12 scenario files from demo/manifest.json and
check each expected decision, play the follow-ups (stores GR, clerk review, approvals with MFA,
payment run with MSME first and TDS), the chatbot's offline answer and refusal, and the audit
chain including the tamper demo. Exit code 0 only if every step passes.
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Duly demo check (green/red table).")
    parser.add_argument("--live-db", action="store_true",
                        help="run against the real database (it is reset before and after)")
    parser.add_argument("--keep", action="store_true",
                        help="with --live-db: leave the checked data in place instead of resetting again")
    parser.add_argument("--ai", action="store_true", help="use the configured AI_MODE (default: offline)")
    args = parser.parse_args()

    if not args.live_db:
        tmp = Path(tempfile.mkdtemp(prefix="duly-demo-check-"))
        os.environ["DULY_DATA_DIR"] = str(tmp)
        os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'demo_check.db').as_posix()}"
        os.environ["DATA_ENCRYPTION_KEY"] = base64.b64encode(os.urandom(32)).decode()
        os.environ["SECRET_KEY"] = base64.b64encode(os.urandom(32)).decode()
    if not args.ai:
        os.environ["AI_MODE"] = "offline"  # the demo must work with no internet
    os.environ["DEMO_MODE"] = "true"
    sys.path.insert(0, str(ROOT / "backend"))

    from fastapi.testclient import TestClient

    from app.core.db import SessionLocal
    from app.demo_check import DemoCheck
    from app.main import app
    from app.seed import reset_and_seed

    if os.name == "nt":
        os.system("")  # enable ANSI colours in the Windows console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # "₹" on a cp1252 console
    green, red, grey, bold, end = "\033[32m", "\033[31m", "\033[90m", "\033[1m", "\033[0m"

    started = time.time()
    db = SessionLocal()
    print(f"{bold}Duly demo check{end}  ({'live database' if args.live_db else 'isolated temp database'}, "
          f"AI {'as configured' if args.ai else 'offline'}) ... about a minute")
    try:
        if not args.live_db:
            reset_and_seed(db)  # a bare seed so the admin who presses "Reset demo data" exists
        with TestClient(app) as client:
            check = DemoCheck(client, db)
            checks = check.run()  # resets through the admin "Reset demo data" endpoint
        if args.live_db and not args.keep:
            reset_and_seed(db, history=True)  # leave a fresh demo database for the stage
    finally:
        db.close()

    width = max(len(c.name) for c in checks)
    for c in checks:
        mark = f"{green}PASS{end}" if c.ok else (f"{grey}SKIP{end}" if c.ok is None else f"{red}FAIL{end}")
        print(f" {mark}  {c.name:<{width}}  {grey if c.ok else ''}{c.detail}{end}")
    passed = sum(1 for c in checks if c.ok)
    colour = green if check.ok else red
    print(f"{colour}{bold}{passed}/{len(checks)} passed{end} in {time.time() - started:.0f} s")
    return 0 if check.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
