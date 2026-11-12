"""Document storage: random file names under backend/data/uploads (outside any web root)."""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

from app.core.config import DATA_DIR

UPLOAD_DIR = DATA_DIR / "uploads"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def store(data: bytes, kind: str) -> str:
    """Write bytes under a random name; return the stored name (never the user's file name)."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(16)}.{kind}"
    (UPLOAD_DIR / name).write_bytes(data)
    return name


def path_of(stored_name: str) -> Path:
    """Resolve a stored name to its path, refusing anything that escapes the upload dir."""
    p = (UPLOAD_DIR / stored_name).resolve()
    if p.parent != UPLOAD_DIR.resolve():
        raise ValueError("invalid stored name")
    return p
