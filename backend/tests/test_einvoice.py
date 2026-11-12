"""D1 signed e-invoice QR: decode, verify the IRP signature, compare with the printed invoice."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.ratelimit import limiter
from app.engine.types import InvoiceDoc
from app.ingestion.extract_text import render_pages
from app.ingestion.qr import einvoice_reasons, verify
from app.samples.invoice_pdf import Line, render_invoice_pdf, with_einvoice
from tests.fixtures.invoices import KESAR_GSTIN, PLANT_X_GSTIN, bearings_invoice, seeded_invoice

CATALYST = [Line("CAT-ZN-01", "Ziegler-Natta catalyst ZN-118", "3815", D("0.5"), "MT", D("850000.00"), D(18))]


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def doc(**kw) -> InvoiceDoc:
    base = InvoiceDoc("KES/26-27/0042", date(2026, 11, 5), KESAR_GSTIN, PLANT_X_GSTIN, "24", "4500001234", "INR",
                      D("74000.00"), D("6660.00"), D("6660.00"), D(0), D("87320.00"))
    return replace(base, **kw)


PAYLOAD = {"SellerGstin": KESAR_GSTIN, "BuyerGstin": PLANT_X_GSTIN, "DocNo": "KES/26-27/0042", "DocDt": "05/11/2026",
           "TotInvVal": 87320.0, "Irn": "ab" * 32}


def codes(reasons):
    return [(r.code, r.severity.value) for r in reasons]


def test_rules_compare_signed_values_with_printed_ones():
    assert codes(einvoice_reasons(doc(), "valid", PAYLOAD, True)) == [("EINVOICE_VERIFIED", "info")]
    r = einvoice_reasons(doc(total=D("86000.00")), "valid", PAYLOAD, True)
    assert codes(r) == [("QR_MISMATCH", "block")]
    assert "₹86,000.00" in r[0].message and "₹87,320.00" in r[0].message
    assert codes(einvoice_reasons(doc(), "invalid", PAYLOAD, True)) == [("QR_SIGNATURE_INVALID", "block")]
    assert codes(einvoice_reasons(doc(), "none", None, True)) == [("EINVOICE_QR_MISSING", "flag")]
    assert codes(einvoice_reasons(doc(), "none", None, False)) == [("EINVOICE_NOT_APPLICABLE", "info")]


def test_qr_decoded_and_signature_verified_from_pdf():
    spec = with_einvoice(bearings_invoice())
    r = verify(render_pages(render_invoice_pdf(spec), "pdf", dpi=200))
    assert r.status == "valid" and r.payload["DocNo"] == "KES/26-27/0042" and r.payload["TotInvVal"] == 87320.0
    assert r.payload["Irn"] == spec.irn and len(spec.irn) == 64


def test_forged_qr_signed_with_another_key_is_invalid():
    spec = with_einvoice(bearings_invoice())
    claims = jwt.decode(spec.signed_qr, options={"verify_signature": False})
    data = json.loads(claims["data"])
    data["TotInvVal"] = 8732.0
    rogue = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    spec.signed_qr = jwt.encode({"data": json.dumps(data), "iss": "IRP"}, rogue, algorithm="RS256")
    r = verify(render_pages(render_invoice_pdf(spec), "pdf", dpi=200))
    assert r.status == "invalid" and "signature" in r.error and r.payload["TotInvVal"] == 8732.0


def test_s8_edited_pdf_total_with_original_signed_qr_is_blocked(client, db):
    """Scenario 8: someone edits the total on a catalyst e-invoice PDF; the signed QR still has the real one."""
    spec = with_einvoice(seeded_invoice(db, "Sahyadri Catalysts & Additives Ltd", invoice_number="SCA/26-27/0950",
                                        invoice_date=date(2026, 11, 8), po_number="4500001011", lines=CATALYST))
    real_total = D("501500.00")  # 0.5 MT x 8,50,000 + 18% IGST
    spec.total_override = D("519500.00")
    client.post("/api/auth/demo-login", json={"email": "billing@sahyadri-catalysts.example"})
    inv = client.post("/api/invoices/upload", headers={"X-CSRF-Token": client.cookies.get("duly_csrf")},
                      files={"file": ("sca.pdf", render_invoice_pdf(spec), "application/pdf")}).json()
    reasons = {r["code"]: r for r in inv["match"]["reasons"]}
    assert inv["decision"] == "BLOCK" and "QR_MISMATCH" in reasons
    msg = reasons["QR_MISMATCH"]["message"]
    assert "₹5,19,500.00" in msg and "₹5,01,500.00" in msg
    assert D(str(reasons["QR_MISMATCH"]["evidence"]["signed"]["TotInvVal"])) == real_total
    assert inv["einvoice"]["status"] == "valid" and inv["einvoice"]["sandbox"] is True


def test_einvoice_supplier_without_qr_is_flagged(client, db):
    spec = seeded_invoice(db, "Sahyadri Catalysts & Additives Ltd", invoice_number="SCA/26-27/0951",
                          invoice_date=date(2026, 11, 8), po_number="4500001011", lines=CATALYST)
    client.post("/api/auth/demo-login", json={"email": "billing@sahyadri-catalysts.example"})
    inv = client.post("/api/invoices/upload", headers={"X-CSRF-Token": client.cookies.get("duly_csrf")},
                      files={"file": ("sca.pdf", render_invoice_pdf(spec), "application/pdf")}).json()
    assert "EINVOICE_QR_MISSING" in {r["code"] for r in inv["match"]["reasons"]}
    assert inv["einvoice"]["status"] == "none"
