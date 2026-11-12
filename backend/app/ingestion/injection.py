"""Prompt-injection shield for documents (D2).

Invoices are untrusted input that may reach an LLM. Before anything reads a PDF we look for:
  - hidden text: white (or near-white) fill, tiny fonts (< 3.5 pt), text placed outside the page
  - PDF metadata (title, subject, keywords, author, creator) that contains instructions
  - instruction-like phrasing anywhere in the document (visible or hidden)
plus the AI's own report of suspicious text. Hidden words are also REMOVED from the tokens the
deterministic parser reads, so hidden text cannot change extracted values. The decision is
still the rules engine's; this module only produces findings.
"""
from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field

import pdfplumber

from app.core.enums import Severity
from app.engine.types import Reason

TINY_PT = 3.5
PATTERNS = [
    (r"ignore (all |any |the )?(previous|prior|above|earlier|other) (instructions|rules|prompts?)", "override instructions"),
    (r"disregard (your|the|all|any) (instructions|rules|system|checks)", "override instructions"),
    (r"(system|developer) prompt|you are now|new instructions", "re-role the model"),
    (r"\b(ai|assistant|llm|chatgpt|claude)\s*:", "addressed to an AI"),  # not "model:" (product models)
    (r"(mark|set|treat)( this| the)? (invoice )?as (approved|paid|verified)|approve (this|the) invoice|auto[- ]?approve",
     "approve the invoice"),
    (r"(change|update|use|replace) (the )?(bank|account|beneficiary|ifsc)", "change payment details"),
    (r"(skip|bypass|disable) (the )?(checks?|validation|matching|approval|review)", "bypass controls"),
    (r"pay (immediately|now|urgently|without)", "rush payment"),
    (r"do not (flag|block|report|review)", "suppress controls"),
]
_RX = [(re.compile(p, re.IGNORECASE), label) for p, label in PATTERNS]


@dataclass
class Finding:
    where: str  # white text | tiny text | outside page | metadata:<key> | visible text | ai noticed
    text: str
    page: int | None = None
    patterns: list[str] = field(default_factory=list)


def _is_white(color) -> bool:
    if color is None:
        return False
    if isinstance(color, (int, float)):
        color = (color,)
    vals = [float(v) for v in color if isinstance(v, (int, float))]
    if not vals:
        return False
    if len(vals) == 4:  # CMYK: white is no ink
        return all(v <= 0.05 for v in vals)
    return all(v >= 0.95 for v in vals)


def hidden_reason(ch: dict, width: float, height: float) -> str | None:
    if _is_white(ch.get("non_stroking_color")):
        return "white text"
    if float(ch.get("size") or 99) < TINY_PT:
        return "tiny text"
    if ch["x1"] < 0 or ch["x0"] > width or ch["bottom"] < 0 or ch["top"] > height:
        return "outside page"
    return None


def matches(text: str) -> list[str]:
    return sorted({label for rx, label in _RX if rx.search(text)})


def scan_pdf(data: bytes) -> list[Finding]:
    """Hidden text runs, metadata and instruction-like visible text in a PDF."""
    findings: list[Finding] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for key, value in (pdf.metadata or {}).items():
            if isinstance(value, str) and matches(value):
                findings.append(Finding(f"metadata:{key}", value[:500], None, matches(value)))
        for pno, page in enumerate(pdf.pages, start=1):
            w, h = float(page.width), float(page.height)
            runs: dict[str, list[str]] = {}
            for ch in page.chars:
                why = hidden_reason(ch, w, h)
                if why:
                    runs.setdefault(why, []).append(ch["text"])
            for why, chars in runs.items():
                text = re.sub(r"\s+", " ", "".join(chars)).strip()
                if len(text) >= 3:
                    findings.append(Finding(why, text[:1000], pno, matches(text)))
            # Visible text only (hidden characters were reported above, not twice).
            shown = page.filter(lambda o, w=w, h=h: o.get("object_type") != "char" or not hidden_reason(o, w, h))
            visible = shown.extract_text() or ""
            for line in visible.splitlines():
                m = matches(line)
                if m:
                    findings.append(Finding("visible text", line[:300], pno, m))
    return findings


def scan_text(lines: list[str]) -> list[Finding]:
    """For images (OCR): only visible text can be checked."""
    return [Finding("visible text", ln[:300], None, matches(ln)) for ln in lines if matches(ln)]


def is_injection(findings: list[Finding]) -> bool:
    """Hidden content is suspicious only if it carries instructions; visible instructions count too."""
    return any(f.patterns for f in findings)


def to_json(findings: list[Finding]) -> list[dict]:
    return [asdict(f) for f in findings]


def injection_reasons(stored: dict | None) -> list[Reason]:
    """Engine input from the stored scan result. Pure."""
    if not stored or not stored.get("found"):
        return []
    items = stored.get("findings", [])
    first = next((f for f in items if f.get("patterns")), items[0] if items else {})
    where = sorted({f["where"] for f in items if f.get("patterns")})
    quarantined = stored.get("ai_quarantined") is not None
    return [Reason(
        "INJECTION_ATTEMPT", Severity.FLAG,
        f"The document contains instructions aimed at an AI or at the approval process ({', '.join(where)}): "
        f"\"{first.get('text', '')[:120]}\". "
        + ("The AI's reading of this document was quarantined; values come from the deterministic parser. "
           if quarantined else "")
        + "Duly's decision comes from the rules engine, not from AI, so the text has no effect on approval.",
        {"findings": items[:10], "ai_quarantined": quarantined})]
