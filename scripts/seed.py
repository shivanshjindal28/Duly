"""Create or reset the Duly database with synthetic seed data.

Usage (from the repo root):
    python scripts/seed.py --reset
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.db import SessionLocal, create_all  # noqa: E402
from app.seed import reset_and_seed, seed  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the Duly database with synthetic data.")
    parser.add_argument("--reset", action="store_true", help="drop all tables first")
    parser.add_argument("--no-history", action="store_true",
                        help="skip the ~250 historical invoices (faster; dashboards stay nearly empty)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.reset:
            counts = reset_and_seed(db, history=not args.no_history)
        else:
            create_all()
            counts = seed(db, history=not args.no_history)
    finally:
        db.close()
    print("Seeded:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    print("Demo password for every seeded user: Duly@2026 (synthetic data only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
