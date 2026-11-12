"""Tamper demo (DEMO_MODE only): edit one audit row directly in the database, bypassing Duly,
the way an insider with database access might. Verification then shows exactly which event
broke. `restore` puts the original bytes back so the demo can be repeated.
"""
from __future__ import annotations

import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AppSetting, AuditEvent

_BACKUP = "tamper_backup"


def tamper(db: Session) -> dict:
    """Change the amount (or comment) on the latest approval event with a raw SQL UPDATE."""
    if db.get(AppSetting, _BACKUP):
        raise ValueError("A tamper demo is already active; restore it first.")
    target = (db.scalar(select(AuditEvent).where(AuditEvent.action == "approval.approved")
                        .order_by(AuditEvent.id.desc()).limit(1))
              or db.scalar(select(AuditEvent).where(AuditEvent.action == "invoice.matched")
                           .order_by(AuditEvent.id.desc()).limit(1)))
    if target is None:
        raise ValueError("No approval or match event to tamper with yet.")
    original = db.execute(text("SELECT after FROM audit_events WHERE id = :id"), {"id": target.id}).scalar_one()
    data = json.loads(original) if isinstance(original, str) else dict(original or {})
    if "total" in data:
        data["total"] = str(round(float(data["total"]) / 10, 2))  # an insider "reduces" the approved amount
        what = "approved amount divided by 10"
    else:
        data["decision"] = "APPROVE"
        what = "decision changed to APPROVE"
    db.add(AppSetting(key=_BACKUP, value=json.dumps({"id": target.id})))
    db.commit()
    db.execute(text("UPDATE audit_events SET after = :after WHERE id = :id"),
               {"after": json.dumps(data), "id": target.id})
    # Keep the original separately (long JSON does not fit in app_settings.value).
    db.execute(text("CREATE TABLE IF NOT EXISTS tamper_backup (id INTEGER PRIMARY KEY, after TEXT)"))
    db.execute(text("INSERT OR REPLACE INTO tamper_backup (id, after) VALUES (:id, :after)"),
               {"id": target.id, "after": original if isinstance(original, str) else json.dumps(original)})
    db.commit()
    return {"event_id": target.id, "action": target.action, "change": what}


def restore(db: Session) -> dict:
    backup = db.get(AppSetting, _BACKUP)
    if backup is None:
        raise ValueError("No tamper demo is active.")
    event_id = json.loads(backup.value)["id"]
    original = db.execute(text("SELECT after FROM tamper_backup WHERE id = :id"), {"id": event_id}).scalar_one()
    db.execute(text("UPDATE audit_events SET after = :after WHERE id = :id"), {"after": original, "id": event_id})
    db.execute(text("DELETE FROM tamper_backup WHERE id = :id"), {"id": event_id})
    db.delete(backup)
    db.commit()
    return {"event_id": event_id, "restored": True}
