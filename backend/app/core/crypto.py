"""Field-level encryption (AES-256-GCM) for sensitive values such as bank account numbers."""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_AAD = b"duly:field:v1"


def encrypt_str(plaintext: str) -> str:
    """Encrypt to base64(nonce || ciphertext+tag)."""
    nonce = os.urandom(12)
    ct = AESGCM(get_settings().resolved_data_key).encrypt(nonce, plaintext.encode("utf-8"), _AAD)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_str(token: str) -> str:
    raw = base64.b64decode(token)
    return AESGCM(get_settings().resolved_data_key).decrypt(raw[:12], raw[12:], _AAD).decode("utf-8")


def mask_account(account: str) -> str:
    """Show only the last 4 digits, e.g. XXXXXX4417."""
    digits = account.strip()
    return "X" * max(len(digits) - 4, 2) + digits[-4:]
