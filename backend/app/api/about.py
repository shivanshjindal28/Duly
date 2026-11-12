"""Data for the "About Duly" pages: Architecture (docs/ARCHITECTURE.md + live system status),
Trust & controls (live evidence for each control) and Scenario & assumptions (policy, suppliers,
HSN table). Staff roles only; nothing here is a secret, but suppliers do not need it.
"""
from __future__ import annotations

import importlib.util
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.ai.extract import ai_mode_setting
from app.core import audit
from app.core.config import REPO_ROOT, get_settings
from app.core.db import get_db
from app.core.enums import Role
from app.core.security import require_roles
from app.ingestion import extract_text
from app.models import (ApprovalStep, AuditEvent, ExtractionResult, Invoice, Organisation, Policy, Supplier, User)
from app.validation.hsn import HSN_RATES

router = APIRouter(tags=["about"],
                   dependencies=[Depends(require_roles(Role.CLERK, Role.APPROVER, Role.AUDITOR, Role.ADMIN))])


def _policy(db: Session) -> Policy | None:
    return db.scalar(select(Policy).where(Policy.is_active.is_(True)))


def _count(db: Session, action: str) -> int:
    return db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)) or 0


@router.get("/architecture")
def architecture(db: Session = Depends(get_db)) -> dict:
    """The same Markdown file the docs use, plus a live system-status panel."""
    doc = (REPO_ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    v = audit.verify(db)
    policy = _policy(db)
    ocr_installed = importlib.util.find_spec("rapidocr_onnxruntime") is not None
    settings = get_settings()
    return {
        "markdown": doc,
        "status": {
            "version": __version__,
            "db": "ok",
            "database": "postgres" if settings.resolved_database_url.startswith("postgres") else "sqlite",
            "ai_mode": ai_mode_setting(),
            "ai_model": settings.anthropic_model if ai_mode_setting() != "offline" else None,
            "ocr": "loaded" if extract_text._ocr_engine.cache_info().currsize else ("ready" if ocr_installed else "missing"),
            "audit_chain_ok": v.ok,
            "audit_events": v.events,
            "policy_version": policy.version if policy else None,
            "invoices": db.scalar(select(func.count()).select_from(Invoice)),
            "demo_mode": settings.demo_mode,
        },
    }


@router.get("/trust")
def trust(db: Session = Depends(get_db)) -> dict:
    """Live evidence behind each responsible-AI and security control (spec section 12)."""
    policy = _policy(db)
    threshold = float(policy.data.get("confidence_threshold", 0.85)) if policy else 0.85
    matches = db.scalars(select(AuditEvent.after).where(AuditEvent.action == "invoice.matched")).all()
    fields = db.execute(select(ExtractionResult.source, ExtractionResult.confidence, ExtractionResult.value,
                               ExtractionResult.model, ExtractionResult.prompt_version)).all()
    extracted = [f for f in fields if f.source != "manual"]
    reviews = [f for f in fields if f.source == "manual"]
    corrected = db.scalar(select(func.count()).select_from(ExtractionResult).where(
        ExtractionResult.source == "manual", ExtractionResult.value != ExtractionResult.previous_value)) or 0
    invoices = db.scalars(select(Invoice)).all()
    injected = [i for i in invoices if (i.injection or {}).get("found")]
    quarantined = [i for i in injected if (i.injection or {}).get("ai_quarantined")]
    sources = Counter(f.source for f in extracted)
    models = Counter(f"{f.model or 'offline-regex'} · {f.prompt_version or '-'}" for f in extracted)
    v = audit.verify(db)
    return {
        "threshold": threshold,
        "ai_mode": ai_mode_setting(),
        "ai_model": get_settings().anthropic_model,
        "engine": {
            "matches": len(matches),
            "ai_decided": sum(1 for a in matches if (a or {}).get("ai_decided")),
        },
        "extraction": {
            "fields": len(extracted),
            "below_threshold": sum(1 for f in extracted if f.value is not None and f.confidence < threshold),
            "reviews": len(reviews),
            "corrected": corrected,
            "sources": dict(sources),
            "models": dict(models.most_common(5)),
        },
        "injection": {"found": len(injected), "ai_quarantined": len(quarantined)},
        "access": {
            "users_by_role": dict(Counter(u.role for u in db.scalars(select(User)))),
            "sod_refusals": _count(db, "security.sod_refused"),
            "mfa_approvals": db.scalar(select(func.count()).select_from(ApprovalStep)
                                       .where(ApprovalStep.mfa_verified.is_(True))) or 0,
            "lockouts": _count(db, "auth.account_locked"),
            "failed_logins": _count(db, "auth.login_failed"),
            "chat_refusals": _count(db, "security.chat_cross_tenant_refused"),
            "chat_injection_flags": _count(db, "security.chat_injection_flagged"),
        },
        "data": {
            "bank_accounts_encrypted": db.scalar(select(func.count()).select_from(Supplier)
                                                 .where(Supplier.bank_account_enc.is_not(None))) or 0,
            "bank_alerts": _count(db, "security.bank_mismatch_alert"),
            "synthetic": all(s.is_synthetic for s in db.scalars(select(Supplier))),
        },
        "audit": {"ok": v.ok, "events": v.events, "signed_head": v.head_signature_ok},
    }


@router.get("/assumptions")
def assumptions(db: Session = Depends(get_db)) -> dict:
    """Scenario facts and every rule value Duly runs on (all assumptions, all editable as policy data)."""
    org = db.scalar(select(Organisation))
    policy = _policy(db)
    return {
        "organisation": {"name": org.name, "gstin": org.gstin, "state_code": org.state_code, "address": org.address}
        if org else None,
        "suppliers": [{
            "code": s.code, "name": s.name, "category": s.category, "state_code": s.state_code,
            "msme": s.msme_category, "udyam": s.udyam_no, "enterprise": s.enterprise_type,
            "e_invoice": s.e_invoice_applicable, "terms_days": s.payment_terms_days,
            "written_agreement": s.written_agreement, "tds_section": s.tds_section,
            "early_discount": f"{s.early_discount_pct}% in {s.early_discount_days} days" if s.early_discount_days else None,
        } for s in db.scalars(select(Supplier).order_by(Supplier.code))],
        "policy": {"version": policy.version, "name": policy.name, "data": policy.data} if policy else None,
        "hsn": [{"code": c, "description": d, "rates": sorted(float(r) for r in rates)}
                for c, (d, rates) in HSN_RATES.items()],
    }
