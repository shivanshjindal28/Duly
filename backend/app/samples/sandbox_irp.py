"""Sandbox IRP: a local stand-in for the GST Invoice Registration Portal (demo only).

Real e-invoices above the turnover threshold carry a QR code holding a JWT signed (RS256) by
the IRP. Its `data` claim is a JSON string with the seller and buyer GSTINs, document number,
type and date, total invoice value, item count, main HSN, the IRN and the IRN date. This
module signs the same structure with a locally generated RSA key so the demo can show
signature verification end to end. Production must trust the real NIC IRP public key instead;
the trusted key is configured, not hard-coded (`IRP_PUBLIC_KEY_PATH`).

IRN = SHA-256 of seller GSTIN + financial year + document type + document number (the IRP rule).
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import KEYS_DIR

PRIVATE = "sandbox_irp_private.pem"
PUBLIC = "sandbox_irp_public.pem"
ISSUER = "Sandbox IRP (Duly demo)"


def _keypair():
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    priv_path = KEYS_DIR / PRIVATE
    if not priv_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()))
        (KEYS_DIR / PUBLIC).write_bytes(key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return serialization.load_pem_private_key(priv_path.read_bytes(), password=None)


def public_key_pem() -> bytes:
    _keypair()
    return (KEYS_DIR / PUBLIC).read_bytes()


def fiscal_year(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def irn(seller_gstin: str, doc_no: str, doc_date: date, doc_type: str = "INV") -> str:
    return hashlib.sha256(f"{seller_gstin}{fiscal_year(doc_date)}{doc_type}{doc_no}".encode()).hexdigest()


def sign(seller_gstin: str, buyer_gstin: str, doc_no: str, doc_date: date, total: str, item_count: int,
         main_hsn: str, irn_value: str) -> str:
    """Return the signed QR string (a JWT), as an IRP would print it on the invoice."""
    data = {
        "SellerGstin": seller_gstin, "BuyerGstin": buyer_gstin, "DocNo": doc_no, "DocTyp": "INV",
        "DocDt": doc_date.strftime("%d/%m/%Y"), "TotInvVal": float(total), "ItemCnt": item_count,
        "MainHsnCode": main_hsn, "Irn": irn_value, "IrnDt": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
    }
    return jwt.encode({"data": json.dumps(data, separators=(",", ":")), "iss": ISSUER}, _keypair(), algorithm="RS256")
