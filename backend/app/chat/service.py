"""Payment assistant orchestration: guardrails -> (Claude with tools | offline matcher) -> log.

Every turn is stored (redacted) on a ChatSession and recorded in the audit trail; refusals of
cross-supplier requests and injection attempts are recorded as security events.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.extract import ai_mode_setting
from app.chat import llm, offline
from app.chat.guardrails import redact, screen
from app.chat.i18n import t
from app.chat.tools import ToolCall
from app.core import audit, clock
from app.core.enums import Role
from app.models import ChatSession, Supplier, User

log = logging.getLogger("duly.chat")


@dataclass
class ChatResult:
    session_id: int
    answer: str
    tools: list[dict] = field(default_factory=list)
    mode: str = "offline"  # live | offline
    refused: bool = False
    flagged: bool = False


def _tool_chips(lang: str, calls: list[ToolCall]) -> list[dict]:
    return [{"name": c.name, "ref": c.ref, "label": t(lang, f"chat.tool.{c.name}", ref=c.ref or "")} for c in calls]


def _session(db: Session, user: User, supplier_id: int, session_id: int | None) -> ChatSession:
    if session_id:
        s = db.get(ChatSession, session_id)
        if s and s.user_id == user.id and s.supplier_id == supplier_id:
            return s
    s = ChatSession(user_id=user.id, supplier_id=supplier_id, messages=[])
    db.add(s)
    db.flush()
    return s


def chat(db: Session, user: User, supplier_id: int, message: str, lang: str, session_id: int | None) -> ChatResult:
    lang = "hi" if lang == "hi" else "en"
    supplier = db.get(Supplier, supplier_id)
    others = [(s.name, s.gstin) for s in db.scalars(select(Supplier))]
    scr = screen(message, supplier.name, supplier.gstin, others)
    session = _session(db, user, supplier_id, session_id)
    result = ChatResult(session_id=session.id, answer="")

    if user.role == Role.SUPPLIER and scr.other_supplier:
        result.answer, result.refused = t(lang, "chat.refused_other_supplier"), True
        audit.queue(db, "security.chat_cross_tenant_refused", "supplier", supplier_id,
                    after={"asked_about": scr.other_supplier, "message": redact(message)[:300]})
    elif scr.injection and not scr.text.replace("[removed]", "").strip(" .,!?"):
        result.answer, result.flagged = t(lang, "chat.injection_flagged"), True
    else:
        history = [{"role": m["role"], "content": m["content"]} for m in session.messages if m["role"] in ("user", "assistant")]
        calls: list[ToolCall] = []
        if ai_mode_setting() == "live":
            try:
                result.answer, calls = llm.answer(db, supplier_id, supplier.name, history, scr.text, lang)
                result.mode = "live"
            except llm.ChatUnavailable as e:
                log.warning("Chat AI unavailable, using offline assistant: %s", e)
        if not result.answer:
            result.answer, calls = offline.answer(db, supplier_id, scr.text, lang)
        result.tools = _tool_chips(lang, calls)
        if scr.injection:
            result.flagged = True
            result.answer = t(lang, "chat.injection_flagged") + "\n\n" + result.answer
    if scr.injection:
        audit.queue(db, "security.chat_injection_flagged", "supplier", supplier_id,
                    after={"message": redact(message)[:300]})

    now = clock.now().isoformat()
    session.messages = [*session.messages,
                        {"role": "user", "content": redact(message)[:1000], "at": now},
                        {"role": "assistant", "content": redact(result.answer)[:2000], "at": now,
                         "tools": [c["name"] for c in result.tools], "mode": result.mode}]
    audit.queue(db, "chat.message", "chat_session", session.id, after={
        "supplier_id": supplier_id, "question": redact(message)[:300], "mode": result.mode, "lang": lang,
        "tools": [f"{c['name']}:{c['ref'] or ''}" for c in result.tools], "refused": result.refused,
        "flagged": result.flagged,
    })
    db.commit()
    return result
