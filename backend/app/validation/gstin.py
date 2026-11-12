"""GSTIN format and check-digit validation, plus a generator for synthetic GSTINs.

GSTIN layout (15 chars): 2-digit state code, 10-char PAN, entity number (1-9, A-Z),
'Z' (default), check character. The check character uses the GSTN mod-36 scheme:
alternate weights 1, 2 over the first 14 characters, each product folded as
(p // 36) + (p % 36), check = (36 - sum % 36) % 36.
"""
from __future__ import annotations

import re

CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

STATE_CODES = {
    "24": "Gujarat",
    "27": "Maharashtra",
    "29": "Karnataka",
}


def check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14.upper()):
        product = CHARSET.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return CHARSET[(36 - total % 36) % 36]


def is_valid_gstin(gstin: str) -> bool:
    g = (gstin or "").strip().upper()
    return bool(GSTIN_RE.match(g)) and check_char(g[:14]) == g[14]


def pan_from_gstin(gstin: str) -> str:
    return gstin[2:12]


def make_gstin(state_code: str, pan: str, entity: str = "1") -> str:
    """Build a GSTIN with a valid check digit (used for synthetic seed data only)."""
    if not PAN_RE.match(pan):
        raise ValueError(f"invalid PAN format: {pan}")
    first14 = f"{state_code}{pan}{entity}Z"
    return first14 + check_char(first14)
