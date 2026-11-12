"""Tamper-evident audit trail (spec C4).

Append-only `audit_events`. Each event stores
    hash = SHA256(prev_hash + canonical_json(event))
so changing, deleting or reordering any row breaks every hash after it. The chain head
(last id + hash) is signed with a server Ed25519 key and the signature stored, so cutting
rows off the end is detected too.

Writing: code anywhere calls `audit.queue(db, action, ...)`. Events are held on the
session and written only after that session's transaction commits (SQLAlchemy
after_commit hook), so a rolled-back action never leaves an audit entry, and an audit
entry never describes something that did not happen. A process lock keeps the chain
linear when requests run in parallel threads.
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import KEYS_DIR

GENESIS = "0" * 64
_HEAD_KEY = "audit_head"
_lock = threading.Lock()
_PENDING = "audit_pending"
_ACTOR = "audit_actor"
SYSTEM = (None, "system", None)  # rules engine / policy / scheduler, not a person


# --- Keys ----------------------------------------------------------------------------------

def _signing_key() -> Ed25519PrivateKey:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    path = KEYS_DIR / "audit_ed25519.pem"
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    key = Ed25519PrivateKey.generate()
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return key


def public_key_b64() -> str:
    raw = _signing_key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


# --- Hashing -------------------------------------------------------------------------------

def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def event_payload(e) -> dict:
    """The fields covered by the hash (everything except id, prev_hash and hash)."""
    ts = e.ts if isinstance(e.ts, str) else e.ts.replace(tzinfo=None).isoformat(timespec="microseconds")
    return {"ts": ts, "actor_user_id": e.actor_user_id, "actor_role": e.actor_role, "action": e.action,
            "entity_type": e.entity_type, "entity_id": e.entity_id, "before": e.before, "after": e.after, "ip": e.ip}


def compute_hash(prev_hash: str, payload: dict) -> str:
    return hashlib.sha256((prev_hash + canonical_json(payload)).encode("utf-8")).hexdigest()


# --- Queueing and writing ------------------------------------------------------------------

def set_actor(db: Session, user_id: int | None, role: str | None, ip: str | None) -> None:
    """Remember who is acting on this request's session (set by the auth dependency)."""
    db.info[_ACTOR] = (user_id, role, ip)


def queue(db: Session, action: str, entity_type: str | None = None, entity_id: Any = None,
          before: dict | None = None, after: dict | None = None, *, actor: tuple | None = None) -> None:
    """Queue an audit event; it is written when `db` commits (and dropped if it rolls back)."""
    user_id, role, ip = actor or db.info.get(_ACTOR, (None, "system", None))
    db.info.setdefault(_PENDING, []).append({
        "ts": clock.now(), "actor_user_id": user_id, "actor_role": role, "action": action,
        "entity_type": entity_type, "entity_id": None if entity_id is None else str(entity_id),
        "before": _jsonable(before), "after": _jsonable(after), "ip": ip,
    })


def _jsonable(obj: Any) -> Any:
    """Decimals, dates and enums become strings so the stored JSON hashes the same on re-read."""
    return None if obj is None else json.loads(canonical_json(obj))


@event.listens_for(Session, "after_rollback")
def _drop_pending(session: Session) -> None:
    session.info.pop(_PENDING, None)


@event.listens_for(Session, "after_commit")
def _write_pending(session: Session) -> None:
    pending = session.info.pop(_PENDING, None)
    if pending:
        append(pending)


def append(events: list[dict]) -> None:
    """Append events to the chain in their own transaction and re-sign the head."""
    from app.core.db import SessionLocal
    from app.models import AppSetting, AuditEvent

    with _lock:
        db = SessionLocal()
        try:
            last = db.scalar(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1))
            prev = last.hash if last else GENESIS
            row = None
            for ev in events:
                row = AuditEvent(**ev, prev_hash=prev)
                row.ts = ev["ts"].replace(tzinfo=None)  # stored naive UTC (SQLite); hashed the same way
                row.hash = compute_hash(prev, event_payload(row))
                db.add(row)
                db.flush()
                prev = row.hash
            head = f"{row.id}:{row.hash}"
            sig = base64.b64encode(_signing_key().sign(head.encode())).decode()
            setting = db.get(AppSetting, _HEAD_KEY)
            if setting is None:
                db.add(AppSetting(key=_HEAD_KEY, value=f"{head}:{sig}"))
            else:
                setting.value = f"{head}:{sig}"
            db.commit()
        finally:
            db.close()


# --- Verification --------------------------------------------------------------------------

@dataclass
class VerifyResult:
    ok: bool
    events: int
    head_id: int | None
    head_hash: str | None
    head_signature_ok: bool
    broken_at_id: int | None = None
    problem: str | None = None
    expected_hash: str | None = None
    stored_hash: str | None = None
    verified_at: datetime | None = None


def verify(db: Session) -> VerifyResult:
    from app.models import AppSetting, AuditEvent

    prev = GENESIS
    n = 0
    last = None
    for e in db.scalars(select(AuditEvent).order_by(AuditEvent.id)):
        n += 1
        if e.prev_hash != prev:
            return VerifyResult(False, n, None, None, False, e.id,
                                "This event does not point to the previous event's hash (a row was deleted or "
                                "reordered before it).", prev, e.prev_hash, clock.now())
        expected = compute_hash(prev, event_payload(e))
        if expected != e.hash:
            return VerifyResult(False, n, None, None, False, e.id,
                                "This event's content no longer matches its hash (the row was edited).",
                                expected, e.hash, clock.now())
        prev, last = e.hash, e

    sig_ok = False
    setting = db.get(AppSetting, _HEAD_KEY)
    if setting and last is not None:
        head_id, head_hash, sig = setting.value.split(":", 2)
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64())).verify(
                base64.b64decode(sig), f"{head_id}:{head_hash}".encode())
            sig_ok = int(head_id) == last.id and head_hash == last.hash
        except Exception:  # noqa: BLE001 - any signature problem is a failed check
            sig_ok = False
        if not sig_ok:
            return VerifyResult(False, n, last.id, last.hash, False, last.id,
                                f"The signed head says event {head_id} is the last one; the table ends at {last.id} "
                                "(events were removed or added outside Duly).", head_hash, last.hash, clock.now())
    return VerifyResult(True, n, last.id if last else None, last.hash if last else None,
                        sig_ok or last is None, verified_at=clock.now())
