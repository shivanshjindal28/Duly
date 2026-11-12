"""Deterministic guardrails that run before any model sees the message.

- Cross-tenant: a supplier naming another supplier (by name or GSTIN) is refused and the
  attempt is logged as a security event. (The tools could not return that data anyway;
  this makes the refusal explicit and auditable.)
- Injection: instruction-like phrases are detected, stripped from what reaches the model,
  and flagged.
- Redaction: long digit runs (bank accounts) are masked before anything is logged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (your|the|all) (instructions|rules|system)",
    r"(system|developer) prompt", r"you are now", r"act as (an? )?(admin|administrator|developer|system)",
    r"pretend (to be|you are)", r"jailbreak", r"reveal (your|the) (instructions|prompt|rules)",
    r"supplier[_ ]?id\s*[=:]", r"(as|from) (the )?(system|admin|administrator)\s*:",
    r"पिछले निर्देश(ों)? को (अनदेखा|नज़रअंदाज़)",
]
_INJ = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)
_GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b")
_GENERIC = {"ltd", "pvt", "limited", "works", "services", "the", "and", "labs", "engineering", "packaging",
            "bulk", "carriers", "catalysts", "additives", "spares", "calibration", "turnaround"}


@dataclass
class Screen:
    text: str  # what may reach the model
    injection: bool
    other_supplier: str | None


def _distinctive(name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{4,}", name.lower()) if w not in _GENERIC]


def screen(message: str, own_supplier: str | None, own_gstin: str | None,
           other_suppliers: list[tuple[str, str]]) -> Screen:
    text = message.strip()[:1000]
    injection = bool(_INJ.search(text))
    if injection:
        text = _INJ.sub("[removed]", text)
    other = None
    low = text.lower()
    for name, gstin in other_suppliers:
        if name == own_supplier:
            continue
        if gstin and gstin in text.upper() and gstin != own_gstin:
            other = name
            break
        if any(fuzz.partial_ratio(w, low) >= 90 and len(w) >= 5 for w in _distinctive(name)):
            other = name
            break
    if other is None:
        for g in _GSTIN.findall(text.upper()):
            if g != own_gstin:
                other = "another supplier"
                break
    return Screen(text=text, injection=injection, other_supplier=other)


def redact(text: str) -> str:
    """Mask long digit runs (bank accounts etc.) before logging."""
    return re.sub(r"\d{9,18}", lambda m: "X" * (len(m.group()) - 4) + m.group()[-4:], text)
