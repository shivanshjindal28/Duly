"""Application settings, read from environment variables and the repo-root `.env` file.

Secrets that are left empty are generated once and persisted under `backend/data/keys/`
(git-ignored) so a fresh laptop runs with zero configuration, and sessions and encrypted
fields survive restarts.
"""
from __future__ import annotations

import base64
import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
# Runtime data (db, uploads, keys, caches). DULY_DATA_DIR overrides it (tests use a temp dir).
DATA_DIR = Path(os.environ.get("DULY_DATA_DIR") or BACKEND_DIR / "data")
KEYS_DIR = DATA_DIR / "keys"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    demo_mode: bool = True
    secret_key: str = ""
    session_minutes: int = 60
    login_rate_limit: str = "10/minute"
    lockout_threshold: int = 5
    lockout_minutes: int = 15
    database_url: str = ""
    data_encryption_key: str = ""
    anthropic_api_key: str = ""
    ai_mode: str = "auto"  # auto | live | cached | offline (offline = AI kill switch)
    anthropic_model: str = "claude-sonnet-5-5"
    frontend_origin: str = "http://localhost:5173"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(DATA_DIR / 'duly.db').as_posix()}"

    @property
    def resolved_secret_key(self) -> str:
        return self.secret_key or _persisted_secret("session_secret", lambda: secrets.token_urlsafe(48))

    @property
    def resolved_data_key(self) -> bytes:
        raw = self.data_encryption_key or _persisted_secret(
            "data_key", lambda: base64.b64encode(os.urandom(32)).decode()
        )
        key = base64.b64decode(raw)
        if len(key) != 32:
            raise ValueError("DATA_ENCRYPTION_KEY must be 32 bytes, base64-encoded")
        return key


def _persisted_secret(name: str, make) -> str:
    """Read a generated secret from backend/data/keys, creating it on first use."""
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    path = KEYS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = make()
    path.write_text(value, encoding="utf-8")
    return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
