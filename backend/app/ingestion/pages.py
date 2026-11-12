"""Page images for the document viewer, rendered once and cached on disk.

The viewer shows server-rendered PNGs for both PDFs and images, so extraction bounding
boxes (page fractions) line up exactly with what the user sees.
"""
from __future__ import annotations

import io

from app.core.config import DATA_DIR
from app.ingestion.extract_text import render_pages
from app.ingestion.storage import path_of

PAGE_DIR = DATA_DIR / "pages"
VIEW_DPI = 110


def page_png(stored_name: str, page: int) -> bytes:
    cached = PAGE_DIR / f"{stored_name.rsplit('.', 1)[0]}-{page}.png"
    if cached.exists():
        return cached.read_bytes()
    src = path_of(stored_name)
    kind = stored_name.rsplit(".", 1)[-1]
    images = render_pages(src.read_bytes(), kind, dpi=VIEW_DPI)
    PAGE_DIR.mkdir(parents=True, exist_ok=True)
    out = b""
    for i, img in enumerate(images, start=1):
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        (PAGE_DIR / f"{stored_name.rsplit('.', 1)[0]}-{i}.png").write_bytes(buf.getvalue())
        if i == page:
            out = buf.getvalue()
    return out
