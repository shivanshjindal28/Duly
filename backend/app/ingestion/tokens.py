"""Positioned text tokens (from the PDF text layer or OCR) and grouping into lines.

Coordinates are page fractions (0..1) with a top-left origin, so the same bounding box
works for highlighting on any rendering of the page.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BBox = tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass(frozen=True)
class Token:
    text: str
    page: int  # 1-based
    bbox: BBox
    conf: float  # 1.0 for the text layer, OCR score otherwise
    source: str  # "text" | "ocr"
    line_y: float | None = None  # deskewed vertical centre used for line grouping (photos)

    @property
    def cy(self) -> float:
        return self.line_y if self.line_y is not None else (self.bbox[1] + self.bbox[3]) / 2


@dataclass
class TextLine:
    page: int
    tokens: list[Token] = field(default_factory=list)
    text: str = ""
    spans: list[tuple[int, int]] = field(default_factory=list)  # char span of each token in text

    def finalise(self) -> TextLine:
        self.tokens.sort(key=lambda t: t.bbox[0])
        parts, spans, pos = [], [], 0
        for t in self.tokens:
            spans.append((pos, pos + len(t.text)))
            parts.append(t.text)
            pos += len(t.text) + 1
        self.text, self.spans = " ".join(parts), spans
        return self

    def locate(self, start: int, end: int) -> tuple[BBox, float]:
        """Union bbox and minimum confidence of the tokens covering text[start:end]."""
        hit = [t for t, (s, e) in zip(self.tokens, self.spans, strict=True) if s < end and e > start]
        if not hit:
            hit = self.tokens
        box = (min(t.bbox[0] for t in hit), min(t.bbox[1] for t in hit),
               max(t.bbox[2] for t in hit), max(t.bbox[3] for t in hit))
        return box, min(t.conf for t in hit)


def group_lines(tokens: list[Token]) -> list[TextLine]:
    """Group tokens whose vertical centres are close into reading-order lines."""
    lines: list[TextLine] = []
    for t in sorted(tokens, key=lambda t: (t.page, t.cy, t.bbox[0])):
        h = max(t.bbox[3] - t.bbox[1], 0.004)
        cur = lines[-1] if lines else None
        if cur and cur.page == t.page:
            if abs(t.cy - cur.tokens[0].cy) <= h * 0.6:
                cur.tokens.append(t)
                continue
        lines.append(TextLine(page=t.page, tokens=[t]))
    return [ln.finalise() for ln in lines]
