"""Database engine, session factory and declarative base.

SQLite (WAL mode) by default; any SQLAlchemy URL (e.g. Postgres) via DATABASE_URL.
"""
from __future__ import annotations

import warnings
from collections.abc import Iterator

from sqlalchemy import create_engine, event, exc
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

# SQLite stores Numeric as REAL-compatible text; SQLAlchemy warns once about Decimal. We
# round explicitly in the domain code, so the warning is noise.
warnings.filterwarnings("ignore", category=exc.SAWarning, message=".*Decimal objects natively.*")


class Base(DeclarativeBase):
    pass


_url = get_settings().resolved_database_url
_is_sqlite = _url.startswith("sqlite")

engine = create_engine(
    _url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    future=True,
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        # WAL + NORMAL: never corrupts; only the last commits can be lost on power failure (the
        # SQLite-recommended pairing). FULL made every commit an fsync and the seed 3x slower.
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    import app.models  # noqa: F401  (register models)

    Base.metadata.create_all(engine)


def drop_all() -> None:
    import app.models  # noqa: F401

    Base.metadata.drop_all(engine)
