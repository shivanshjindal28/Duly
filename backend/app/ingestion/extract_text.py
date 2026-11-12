"""Text acquisition: PDF text layer first (pdfplumber), OCR fallback (RapidOCR) for scans and photos."""
from __future__ import annotations

import io
from functools import lru_cache

import numpy as np
import pdfplumber
import pypdfium2 as pdfium
from PIL import Image

from app.ingestion.tokens import Token

RENDER_DPI = 200
MIN_TEXT_CHARS = 40  # below this a PDF is treated as a scan


def text_layer_tokens(pdf_bytes: bytes) -> list[Token]:
    tokens: list[Token] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            w, h = float(page.width), float(page.height)
            for word in page.extract_words(keep_blank_chars=False, use_text_flow=False):
                box = (word["x0"] / w, word["top"] / h, word["x1"] / w, word["bottom"] / h)
                tokens.append(Token(word["text"], pno, box, 1.0, "text"))
    return tokens


def render_pages(data: bytes, kind: str, dpi: int = RENDER_DPI) -> list[Image.Image]:
    """Page images: rendered with pdfium for PDFs, the image itself otherwise."""
    if kind != "pdf":
        return [Image.open(io.BytesIO(data)).convert("RGB")]
    doc = pdfium.PdfDocument(data)
    try:
        return [doc[i].render(scale=dpi / 72).to_pil().convert("RGB") for i in range(len(doc))]
    finally:
        doc.close()


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr_onnxruntime import RapidOCR  # heavy import: load once, lazily

    return RapidOCR()


def ocr_tokens(images: list[Image.Image]) -> list[Token]:
    tokens: list[Token] = []
    for pno, img in enumerate(images, start=1):
        w, h = img.size
        result, _ = _ocr_engine()(np.array(img))
        for quad, text, score in result or []:
            xs = [p[0] for p in quad]
            ys = [p[1] for p in quad]
            box = (min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h)
            tokens.append(Token(str(text), pno, box, float(score), "ocr"))
    return tokens


def acquire_tokens(data: bytes, kind: str) -> tuple[list[Token], str]:
    """Return tokens and the method used: "text" (PDF text layer) or "ocr"."""
    if kind == "pdf":
        tokens = text_layer_tokens(data)
        if sum(len(t.text) for t in tokens) >= MIN_TEXT_CHARS:
            return tokens, "text"
    return ocr_tokens(render_pages(data, kind)), "ocr"
