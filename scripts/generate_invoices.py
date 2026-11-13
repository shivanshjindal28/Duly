"""Generate the demo scenario invoices into demo/invoices/ with demo/manifest.json.

Usage (from the repo root):
    python scripts/generate_invoices.py            # dates relative to today
    python scripts/generate_invoices.py --date 2026-11-12
    python scripts/generate_invoices.py --only S13,S14   # add / redo these only; other files and the
                                                         # signing key stay as committed

Builds against a throwaway seeded database (the seed is deterministic, so GSTINs, PANs and
bank accounts match every laptop's `seed.py --reset`). E-invoice scenarios are signed by a
fresh Sandbox IRP key; its PUBLIC half is written to demo/keys/ so the committed PDFs verify
anywhere in demo mode. No private key leaves the temp folder. All data is fictional.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"

# Isolated runtime data (DB, keys) before the app is imported.
_tmp = Path(tempfile.mkdtemp(prefix="duly-gen-"))
os.environ["DULY_DATA_DIR"] = str(_tmp)
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'gen.db').as_posix()}"
os.environ["DATA_ENCRYPTION_KEY"] = base64.b64encode(os.urandom(32)).decode()
os.environ["SECRET_KEY"] = "generator-only"
sys.path.insert(0, str(ROOT / "backend"))

from app.core import clock  # noqa: E402
from app.core.config import KEYS_DIR  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.samples import sandbox_irp, scenarios  # noqa: E402
from app.seed import reset_and_seed  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the demo scenario invoices.")
    parser.add_argument("--date", help="treat this day as today (YYYY-MM-DD); default: today")
    parser.add_argument("--only", help="comma-separated scenario ids: regenerate just these (no e-invoice ones), "
                                       "keep the other files, the manifest entries and the signing key")
    args = parser.parse_args()
    only = [i.strip().upper() for i in (args.only or "").split(",") if i.strip()]
    existing = json.loads((DEMO / "manifest.json").read_text(encoding="utf-8")) if only else None
    if only and not args.date:
        args.date = existing["generated_on"]  # same "today" as the committed files
    today = date.fromisoformat(args.date) if args.date else clock.today()

    out_dir = DEMO / "invoices"
    if not only:
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
    with clock.travel_to(datetime.combine(today, time(10, 0), tzinfo=clock.IST)):
        db = SessionLocal()
        try:
            reset_and_seed(db)
            items = [sc for sc in scenarios.build(db, today) if not only or sc.id in only]
            if only:
                assert not any(sc.spec.signed_qr for sc in items), "--only cannot redo e-invoice files (key rotation)"
            entries = []
            for sc in items:
                data = sc.render()
                (out_dir / sc.file).write_bytes(data)
                entries.append({**sc.manifest(), "bytes": len(data)})
                print(f"{sc.id:5} {sc.file:44} {len(data) / 1024:7.1f} KB  expect {sc.expect_decision or '(review)'}")
        finally:
            db.close()

    if only:
        kept = [e for e in existing["scenarios"] if e["id"] not in only]
        existing["scenarios"] = kept + entries
        (DEMO / "manifest.json").write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        shutil.rmtree(_tmp, ignore_errors=True)
        print(f"Updated {len(entries)} file(s) in {out_dir.relative_to(ROOT)} and demo/manifest.json")
        return 0
    (DEMO / "keys").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KEYS_DIR / sandbox_irp.PUBLIC, DEMO / "keys" / sandbox_irp.PUBLIC)
    manifest = {
        "generated_on": today.isoformat(),
        "generator": "scripts/generate_invoices.py",
        "note": ("Synthetic documents for the Duly demo; Plant X and every party are fictional. Upload each file "
                 "as the listed supplier (or as an AP clerk on their behalf). Expected results assume a fresh "
                 "`python scripts/seed.py --reset` (history included) and the scenarios uploaded in this order."),
        "sandbox_irp_public_key": "keys/sandbox_irp_public.pem",
        "scenarios": entries,
    }
    (DEMO / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    shutil.rmtree(_tmp, ignore_errors=True)
    print(f"Wrote {len(entries)} files to {out_dir.relative_to(ROOT)} and demo/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
