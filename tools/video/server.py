"""Backend for the product video: a fresh demo database (90-day history + the background scenarios
pre-staged, exactly like the hosted demo) in its own temp folder, AI offline, then uvicorn.
Never touches backend/data. Started by tools/video/record.mjs; port from DULY_API_PORT (default 8200).
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRESTAGE = "S02,S03,S05,S09A,S09B,S10,S11,S12"


def main() -> int:
    data = Path(tempfile.gettempdir()) / "duly-video"
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir(parents=True)
    os.environ.update(
        DULY_DATA_DIR=str(data),
        DATABASE_URL=f"sqlite:///{(data / 'video.db').as_posix()}",
        DATA_ENCRYPTION_KEY=base64.b64encode(os.urandom(32)).decode(),
        SECRET_KEY=base64.b64encode(os.urandom(32)).decode(),
        AI_MODE="offline",
        DEMO_MODE="true",
        LOGIN_RATE_LIMIT="1000/minute",
        DEMO_LOGIN_RATE_LIMIT="1000/minute",
    )
    # Same staging as the hosted demo: history + the scenarios that are not uploaded on camera.
    subprocess.run([sys.executable, str(ROOT / "scripts" / "demo_prestage.py"), "--reset", "--ids", PRESTAGE],
                   check=True, cwd=ROOT / "backend")
    sys.path.insert(0, str(ROOT / "backend"))
    os.chdir(ROOT / "backend")
    import uvicorn

    print("[video] backend ready", flush=True)
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("DULY_API_PORT", "8200")), log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
