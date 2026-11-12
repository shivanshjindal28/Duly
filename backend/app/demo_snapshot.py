"""Demo snapshot: a saved copy of the staged demo database and its documents.

`scripts/demo_prestage.py --snapshot` saves it after staging (the hosted demo does this during the
build). "Reset demo data" then restores it in a second instead of reseeding: on the hosted free plan
reseeding would take minutes on a small CPU and would drop the pre-staged scenarios.

The database is copied with SQLite's online backup API, so the running app keeps its connections.
SQLite only; on another database the reset reseeds as before.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from app.core.config import DATA_DIR, get_settings
from app.core.db import engine

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
