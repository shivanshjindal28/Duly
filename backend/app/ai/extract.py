"""Extraction router: deterministic first, AI second, rules decide.

1. The offline parser always runs on the text layer / OCR tokens (cheap, deterministic).
2. If AI is enabled (AI_MODE live / cached / auto with a key), Claude reads the page images
   and numbered lines. Its fields are merged with the parser's:
     - both agree           -> confident (max of the two confidences)
     - they disagree        -> keep the PDF-text value if the text layer was used, otherwise
                               Claude's; confidence drops below the review threshold, so a
                               human confirms it
     - only one has a value -> that value, with its own confidence
   Bounding boxes come from our own positioned tokens on the line Claude cites, never from
   model-estimated coordinates.
3. Whatever happens with the AI, the result is an ordinary ExtractedInvoice for the rules.
"""
from __future__ import annotations

import logging
import re

from app.ai import offline_parser
from app.ai.claude_extractor import AIUnavailable, extract_with_claude
from app.ai.prompts.extraction import PROMPT_VERSION
from app.ai.schema import HEADER_FIELDS, LINE_FIELDS, ExtractedField, ExtractedInvoice
from app.core.config import get_settings
from app.ingestion.tokens import TextLine, Token, group_lines

log = logging.getLogger("duly.ai")
DISAGREE_FACTOR = 0.6  # confidence multiplier when AI and parser disagree (forces human review)
_NUMERIC = {"taxable_total", "cgst", "sgst", "igst", "total", "qty", "unit_price", "taxable_value", "gst_rate"}


def ai_mode_setting() -> str:
    """Effective AI mode: offline | cached | live. auto = live when an API key is configured."""
    s = get_settings()
    mode = (s.ai_mode or "auto").lower()
    if mode == "auto":
        return "live" if s.anthropic_api_key else "offline"
    return mode if mode in ("offline", "cached", "live") else "offline"


def _norm_value(name: str, value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    v = str(value).strip()
    if name in _NUMERIC:
        return offline_parser._num(re.sub(r"[₹,%\s]|Rs\.?|INR", "", v, flags=re.I)) or v
    if name == "invoice_date":
        return offline_parser._date(v) or (v if re.match(r"^\d{4}-\d{2}-\d{2}$", v) else v)
    if name in {"supplier_gstin", "buyer_gstin", "bank_ifsc", "po_number", "invoice_number", "item_code",
                "currency", "uom"}:
        return v.upper().replace(" ", "")
    if name == "bank_account":
        return re.sub(r"\D", "", v) or None
    return v


def _same(name: str, a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    if name in _NUMERIC:
        try:
            return abs(float(a) - float(b)) < 0.005
        except ValueError:
            return False
    squash = lambda s: re.sub(r"[\s\-/.]", "", s).upper()  # noqa: E731
    return squash(a) == squash(b)


def _locate(line: TextLine | None, value: str | None) -> tuple[int | None, tuple | None]:
    if line is None:
        return None, None
    if value:
        for candidate in {value, f"{float(value):,.2f}" if re.match(r"^\d+(\.\d+)?$", value) else value}:
            i = line.text.upper().find(candidate.upper())
            if i >= 0:
                box, _ = line.locate(i, i + len(candidate))
                return line.page, box
    box, _ = line.locate(0, len(line.text))
    return line.page, box


def _merge_field(name: str, ai: dict, det: ExtractedField, ids: dict[str, TextLine], text_layer: bool) -> ExtractedField:
    ai_value = _norm_value(name, ai.get("value"))
    ai_conf = max(0.0, min(1.0, float(ai.get("confidence") or 0)))
    page, bbox = _locate(ids.get(ai.get("line") or ""), ai_value)
    if ai_value is None and det.value is None:
        return ExtractedField()
    if ai_value is None:
        return det
    if det.value is None:
        return ExtractedField(value=ai_value, confidence=round(ai_conf, 3), page=page, bbox=bbox, source="ai")
    if _same(name, ai_value, det.value):
        return ExtractedField(value=det.value if text_layer else ai_value, confidence=round(max(ai_conf, det.confidence), 3),
                              page=det.page or page, bbox=det.bbox or bbox, source="ai")
    # Disagreement: a human must look. Prefer the exact PDF text over a model reading of it.
    keep_det = text_layer
    conf = min(ai_conf, det.confidence) * DISAGREE_FACTOR
    return ExtractedField(value=det.value if keep_det else ai_value, confidence=round(conf, 3),
                          page=(det.page if keep_det else page) or page, bbox=(det.bbox if keep_det else bbox) or det.bbox,
                          source="text" if keep_det else "ai")


def merge(ai: dict, det: ExtractedInvoice, ids: dict[str, TextLine], model: str) -> ExtractedInvoice:
    text_layer = det.method == "text"
    header = {n: _merge_field(n, ai["header"].get(n, {}), det.header.get(n, ExtractedField()), ids, text_layer)
              for n in HEADER_FIELDS}
    if header["currency"].value is None:
        header["currency"] = det.header["currency"]
    ai_lines = ai.get("lines") or []
    lines = []
    for i, al in enumerate(ai_lines):
        dl = det.lines[i] if i < len(det.lines) and len(det.lines) == len(ai_lines) else {}
        lines.append({n: _merge_field(n, al.get(n, {}), dl.get(n, ExtractedField()), ids, text_layer) for n in LINE_FIELDS})
    if not lines:
        lines = det.lines
    return ExtractedInvoice(header=header, lines=lines, method=det.method, extractor=model,
                            extractor_version=PROMPT_VERSION, suspicious_text=ai.get("suspicious_text"))


def extract(sha256: str, tokens: list[Token], method: str, images_fn, quarantine: bool = False
            ) -> tuple[ExtractedInvoice, str, str | None, dict | None]:
    """Return (extraction, ai_mode used, reason the AI was not used, quarantined AI output).

    quarantine=True (instruction-like text found in the document): the AI still reads the
    document so the clerk can see what it would have said, but its values are NOT used; the
    deterministic parser's are. The same happens if the AI itself reports suspicious text."""
    det = offline_parser.parse(tokens, method)
    mode = ai_mode_setting()
    if mode == "offline":
        return det, "offline", None, None
    try:
        data, used, ids = extract_with_claude(sha256, images_fn(), group_lines(tokens), mode)
    except AIUnavailable as e:
        log.warning("AI extraction unavailable, using offline parser: %s", e)
        return det, "offline", str(e), None
    if quarantine or data.get("suspicious_text"):
        det.suspicious_text = data.get("suspicious_text")
        return det, used, "AI output quarantined (possible prompt injection)", data
    model = data.get("_model_served") or get_settings().anthropic_model
    return merge(data, det, ids, model), used, None, None
