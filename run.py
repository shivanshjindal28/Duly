"""Start Duly locally: FastAPI backend on :8000 and Vite frontend on :5173.

Usage:
    python run.py              # both
    python run.py --backend    # backend only
    python run.py --frontend   # frontend only

Works on Windows and macOS. Ctrl+C stops both.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def start_backend() -> subprocess.Popen:
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"]
    print("[run] backend  -> http://127.0.0.1:8000  (docs at /api/docs)")
    return subprocess.Popen(cmd, cwd=BACKEND)


def start_frontend() -> subprocess.Popen | None:
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        print("[run] npm not found. Install Node.js 20+ to run the frontend.")
        return None
    if not (FRONTEND / "node_modules").exists():
        print("[run] frontend/node_modules missing, running npm install first...")
        subprocess.run([npm, "install"], cwd=FRONTEND, check=True)
    print("[run] frontend -> http://localhost:5173")
    return subprocess.Popen([npm, "run", "dev"], cwd=FRONTEND)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", action="store_true", help="start backend only")
    parser.add_argument("--frontend", action="store_true", help="start frontend only")
    args = parser.parse_args()
    both = not args.backend and not args.frontend

    procs: list[subprocess.Popen] = []
    if both or args.backend:
        procs.append(start_backend())
    if both or args.frontend:
        p = start_frontend()
        if p:
            procs.append(p)
    if not procs:
        return 1

    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                if os.name == "nt":
                    # Kill the whole tree (npm.cmd spawns node; uvicorn --reload spawns a worker).
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
                else:
                    p.send_signal(signal.SIGINT)
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
