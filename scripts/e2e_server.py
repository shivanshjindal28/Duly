"""Backend for the Playwright smoke test: a fresh demo database (with history) in its own data
folder, AI offline, then uvicorn on DULY_API_PORT (default 8100). Started by
frontend/playwright.config.ts; never touches backend/data.
"""
from __future__ import annotations

import base64
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    data = Path(os.environ.get("DULY_DATA_DIR") or Path(tempfile.gettempdir()) / "duly-e2e")
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir(parents=True)
    os.environ.update(
        DULY_DATA_DIR=str(data),
        DATABASE_URL=f"sqlite:///{(data / 'e2e.db').as_posix()}",
        DATA_ENCRYPTION_KEY=base64.b64encode(os.urandom(32)).decode(),
        SECRET_KEY=base64.b64encode(os.urandom(32)).decode(),
        AI_MODE="offline",
        DEMO_MODE="true",
        LOGIN_RATE_LIMIT="1000/minute",  # the smoke test signs in several times from one address
    )
    sys.path.insert(0, str(ROOT / "backend"))
    os.chdir(ROOT / "backend")

    import uvicorn

    from app.core.db import SessionLocal
    from app.seed import reset_and_seed

    db = SessionLocal()
    try:
        counts = reset_and_seed(db, history=True)
    finally:
        db.close()
    print(f"[e2e] seeded {counts['history_invoices']} history invoices in {data}", flush=True)
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("DULY_API_PORT", "8100")), log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
