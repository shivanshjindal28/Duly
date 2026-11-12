"""Signed e-invoice QR: decode (zxing-cpp, OpenCV fallback) and verify the IRP signature (RS256).

"Trust the signed QR, not the pixels": a PDF's printed total can be edited, but the QR's
signed payload cannot be changed without the IRP's private key. The decision comes from
comparing the two in `einvoice_reasons` (rules, not AI).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import cv2
import jwt
import numpy as np
import zxingcpp

from app.core.config import get_settings
from app.core.enums import Severity
from app.engine.types import InvoiceDoc, Reason


@dataclass
class QrResult:
    status: str  # none | valid | invalid
    payload: dict | None = None
    error: str | None = None


def trusted_public_key() -> bytes:
    path = get_settings().irp_public_key_path
    if path:
        with open(path, "rb") as f:
            return f.read()
    from app.samples.sandbox_irp import public_key_pem

    return public_key_pem()


def _variants(img):
    """Grey page, then Otsu-binarised (rendering and photos leave anti-aliased grey edges that
    stop dense QR codes decoding), then a sharpened binarised copy for soft photos."""
    grey = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    yield grey
    _, bw = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield bw
    sharp = cv2.addWeighted(grey, 1.8, cv2.GaussianBlur(grey, (0, 0), 2), -0.8, 0)
    _, sbw = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield sbw


def _decode(arr, detectors) -> list[str]:
    for det in detectors:
        try:
            text, _, _ = det.detectAndDecode(arr)
            if text:
                return [text]
            ok, texts, _, _ = det.detectAndDecodeMulti(arr)
        except cv2.error:
            continue
        found = [t for t in texts if t] if ok else []
        if found:
            return found
    return []


def decode_qr(images) -> list[str]:
    """zxing-cpp first (measured: decodes dense IRP-size QRs reliably, including tilted, blurred
    photos, where OpenCV's decoder fails on some payloads even from a perfect image); then OpenCV:
    locate with the ArUco finder, decode a cropped, binarised window; whole page last."""
    for img in images:
        found = [b.text for b in zxingcpp.read_barcodes(img.convert("RGB"), formats=zxingcpp.BarcodeFormat.QRCode)
                 if b.text]
        if found:
            return found
    std, aruco = cv2.QRCodeDetector(), cv2.QRCodeDetectorAruco()
    for img in images:
        for arr in _variants(img):
            try:
                ok, pts = aruco.detect(arr)
            except cv2.error:
                ok, pts = False, None
            if ok and pts is not None:
                p = pts.reshape(-1, 2)
                x0, y0 = p.min(axis=0)
                x1, y1 = p.max(axis=0)
                m = int(max(x1 - x0, y1 - y0) * 0.3) + 8
                h, w = arr.shape[:2]
                crop = arr[max(0, int(y0) - m):min(h, int(y1) + m), max(0, int(x0) - m):min(w, int(x1) + m)]
                # Dense IRP codes need ~6+ px per module: upscale the crop, then re-binarise.
                for scale in (1, 2, 3):
                    c = crop if scale == 1 else cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                    c = cv2.threshold(c, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
                    found = _decode(c, (aruco, std))
                    if found:
                        return found
            found = _decode(arr, (std, aruco))
            if found:
                return found
    return []


def verify(images) -> QrResult:
    """Find an e-invoice QR (a JWT) on the pages and verify its signature."""
    candidates = [t for t in decode_qr(images) if t.count(".") == 2]
    if not candidates:
        return QrResult("none")
    token = candidates[0]
    try:
        claims = jwt.decode(token, trusted_public_key(), algorithms=["RS256"], options={"verify_aud": False})
        return QrResult("valid", json.loads(claims["data"]))
    except jwt.InvalidSignatureError:
        error = "signature does not match the trusted IRP key"
    except (jwt.InvalidTokenError, KeyError, ValueError) as e:
        error = f"not a valid signed e-invoice QR ({type(e).__name__})"
    try:  # show what the forged QR claims, clearly marked as unverified
        unverified = json.loads(jwt.decode(token, options={"verify_signature": False})["data"])
    except Exception:  # noqa: BLE001
        unverified = None
    return QrResult("invalid", unverified, error)


def _inr(v) -> str:
    from app.samples.invoice_pdf import inr

    return "₹" + inr(Decimal(str(v)))


def einvoice_reasons(doc: InvoiceDoc, qr_status: str | None, payload: dict | None, e_invoice_applicable: bool) -> list[Reason]:
    """Compare the signed QR with the printed/extracted invoice. Pure function."""
    if qr_status == "invalid":
        return [Reason("QR_SIGNATURE_INVALID", Severity.BLOCK,
                       "The QR code on this invoice is not signed by the trusted IRP key, so the invoice cannot be "
                       "trusted as a registered e-invoice.", {"claimed": payload or {}})]
    if qr_status != "valid" or not payload:
        if e_invoice_applicable:
            return [Reason("EINVOICE_QR_MISSING", Severity.FLAG,
                           "This supplier is above the e-invoicing threshold, but no readable signed IRP QR code was "
                           "found (ask for the original PDF if this is a photo or scan).", {})]
        return [Reason("EINVOICE_NOT_APPLICABLE", Severity.INFO,
                       "e-invoice not applicable (supplier below the turnover threshold).", {})]
    diffs: list[tuple[str, str, str]] = []
    if payload.get("SellerGstin") != doc.supplier_gstin:
        diffs.append(("supplier GSTIN", str(doc.supplier_gstin), str(payload.get("SellerGstin"))))
    if payload.get("BuyerGstin") != doc.buyer_gstin:
        diffs.append(("buyer GSTIN", str(doc.buyer_gstin), str(payload.get("BuyerGstin"))))
    if str(payload.get("DocNo", "")).upper() != (doc.invoice_number or "").upper():
        diffs.append(("invoice number", doc.invoice_number, str(payload.get("DocNo"))))
    try:
        signed_date = datetime.strptime(payload.get("DocDt", ""), "%d/%m/%Y").date()
    except ValueError:
        signed_date = None
    if signed_date != doc.invoice_date:
        diffs.append(("invoice date", str(doc.invoice_date), str(signed_date)))
    signed_total = Decimal(str(payload.get("TotInvVal", "0")))
    if abs(signed_total - doc.total) > Decimal("1.00"):
        diffs.append(("total", _inr(doc.total), _inr(signed_total)))
    evidence = {"signed": payload, "differences": [{"field": f, "printed": p, "signed": s} for f, p, s in diffs]}
    if diffs:
        first = diffs[0]
        msg = (f"The printed {first[0]} {first[1]} does not match the signed e-invoice {first[0]} {first[2]}"
               + (f" (and {len(diffs) - 1} more field(s))" if len(diffs) > 1 else "")
               + ". The document was changed after the IRP signed it.")
        return [Reason("QR_MISMATCH", Severity.BLOCK, msg, evidence)]
    return [Reason("EINVOICE_VERIFIED", Severity.INFO,
                   f"Signed e-invoice verified: IRN {str(payload.get('Irn', ''))[:12]}..., total {_inr(signed_total)} "
                   "matches the printed invoice.", evidence)]
