"""Tamper demo: edit one audit_events row directly in SQLite, bypassing Duly, then show that
chain verification pinpoints the broken event.

Usage (from the repo root):
    python scripts/tamper_demo.py            # tamper + verify
    python scripts/tamper_demo.py --restore  # put the original row back + verify
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core import audit, tamper  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--restore", action="store_true", help="undo the tamper")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = tamper.restore(db) if args.restore else tamper.tamper(db)
        print("Done:", result)
        v = audit.verify(db)
        if v.ok:
            print(f"Audit chain VERIFIED: {v.events} events, head #{v.head_id} signature OK.")
        else:
            print(f"Audit chain BROKEN at event #{v.broken_at_id}: {v.problem}")
            print(f"  expected hash {v.expected_hash}\n  stored hash   {v.stored_hash}")
    except ValueError as e:
        print("Nothing done:", e)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
