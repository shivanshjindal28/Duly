"""Demo snapshot: a saved copy of the staged demo database and its documents.

`scripts/demo_prestage.py --snapshot` saves it after staging (the hosted demo does this during the
build). "Reset demo data" then restores it in a second instead of reseeding: on the hosted free plan
reseeding would take minutes on a small CPU and would drop the pre-staged scenarios.

The database is copied with SQLite's online backup API, so the running app keeps its connections.
SQLite only; on another database the reset reseeds as before.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from app.core.config import DATA_DIR, get_settings
from app.core.db import engine

log = logging.getLogger("duly.demo")
SNAP_DIR = DATA_DIR / "snapshot"
SNAP_DB = SNAP_DIR / "duly.db"
_FILES = ("uploads", "pages")


def _sqlite() -> bool:
    return get_settings().resolved_database_url.startswith("sqlite")


def available() -> bool:
    return _sqlite() and SNAP_DB.exists()


def save() -> Path:
    if not _sqlite():
        raise RuntimeError("Snapshots are for the SQLite demo database only.")
    shutil.rmtree(SNAP_DIR, ignore_errors=True)
    SNAP_DIR.mkdir(parents=True)
    raw = engine.raw_connection()
    try:
        dst = sqlite3.connect(SNAP_DB)
        try:
            raw.driver_connection.backup(dst)
        finally:
            dst.close()
    finally:
        raw.close()
    for sub in _FILES:
        if (DATA_DIR / sub).exists():
            shutil.copytree(DATA_DIR / sub, SNAP_DIR / sub)
    return SNAP_DB


def restore() -> None:
    """Replace the live demo database and files with the snapshot (callers close their sessions first)."""
    if not available():
        raise RuntimeError("No demo snapshot saved.")
    src = sqlite3.connect(SNAP_DB)
    raw = engine.raw_connection()
    try:
        src.backup(raw.driver_connection)
    finally:
        raw.close()
        src.close()
    for sub in _FILES:
        shutil.rmtree(DATA_DIR / sub, ignore_errors=True)
        if (SNAP_DIR / sub).exists():
            shutil.copytree(SNAP_DIR / sub, DATA_DIR / sub)


_reset_lock = threading.Lock()


def reset_live() -> None:
    """Restore the snapshot and reload what the running app caches from the database (demo clock, AI mode).
    Used by the scheduled reset; the admin button does the same inside its request."""
    from app.core import audit, clock, runtime
    from app.core.db import SessionLocal

    with _reset_lock:
        restore()
        db = SessionLocal()
        try:
            clock.load_offset(db)
            runtime.load_ai_mode(db)
            audit.queue(db, "demo.auto_reset", "database", None, after={"restored_snapshot": 1})
            db.commit()
        finally:
            db.close()


def start_auto_reset(minutes: int) -> None:
    """Public demo: everyone shares one database, so put it back to the staged state every `minutes`
    (clears vandalism, odd uploads and a left-over tamper demo). Daemon thread; no-op without a snapshot."""
    if minutes <= 0 or not available():
        return

    def loop() -> None:
        while True:
            time.sleep(minutes * 60)
            try:
                reset_live()
                log.info("demo auto-reset: snapshot restored")
            except Exception:  # noqa: BLE001 - never kill the thread; try again next time
                log.exception("demo auto-reset failed")

    threading.Thread(target=loop, name="demo-auto-reset", daemon=True).start()
