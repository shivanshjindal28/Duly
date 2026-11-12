"""Test setup: an isolated SQLite DB and fixed keys, set before the app is imported."""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="duly-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production-0123456789"
os.environ["DATA_ENCRYPTION_KEY"] = base64.b64encode(b"\x01" * 32).decode()
os.environ["DEMO_MODE"] = "true"
os.environ["ANTHROPIC_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import reset_and_seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    db = SessionLocal()
    try:
        reset_and_seed(db)
    finally:
        db.close()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
