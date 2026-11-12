"""Upload hardening. Every uploaded file is untrusted until it passes these checks.

- Extension must be pdf/png/jpg/jpeg and must agree with the file's magic bytes.
- Size limit 10 MB; PDF page limit; image pixel limit (decompression bombs).
- PDFs with active content are rejected: JavaScript, Launch actions, embedded files,
  or other auto-run actions (names are de-obfuscated first, e.g. /J#61vaScript).
- Images are decoded and re-encoded, which drops EXIF/GPS and any trailing payload.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
MAX_PIXELS = 40_000_000

_MAGIC = {
    "pdf": (b"%PDF-",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
}
_EXT = {"pdf": "pdf", "png": "png", "jpg": "jpg", "jpeg": "jpg"}
_MIME = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg"}

# PDF name tokens that indicate active or embedded content.
_DANGEROUS_PDF_NAMES = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/EmbeddedFiles",
                        b"/RichMedia", b"/SubmitForm", b"/ImportData", b"/GoToR", b"/XFA")
_NAME_HEX = re.compile(rb"#([0-9A-Fa-f]{2})")


class UploadRejected(ValueError):
    """Raised with a user-facing reason when an upload fails a hardening check."""


@dataclass(frozen=True)
class CleanFile:
    kind: str  # pdf | png | jpg
    mime: str
    data: bytes  # sanitised bytes to store (re-encoded for images)
    pages: int


def _kind(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _EXT:
        raise UploadRejected("Only PDF, PNG or JPG files are accepted.")
    return _EXT[ext]


def _check_pdf(data: bytes) -> int:
    normalised = _NAME_HEX.sub(lambda m: bytes([int(m.group(1), 16)]), data)
    for name in _DANGEROUS_PDF_NAMES:
        # Match the whole name: /JS must not match /JSomething-else.
        if re.search(re.escape(name) + rb"(?![A-Za-z0-9])", normalised):
            raise UploadRejected(
                f"PDF contains active or embedded content ({name.decode()[1:]}); please upload a plain invoice PDF."
            )
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        raise UploadRejected("The PDF could not be opened (damaged or password-protected).") from e
    try:
        pages = len(doc)
    finally:
        doc.close()
    if pages == 0:
        raise UploadRejected("The PDF has no pages.")
    if pages > MAX_PAGES:
        raise UploadRejected(f"The PDF has {pages} pages; the limit is {MAX_PAGES}.")
    return pages


def _clean_image(data: bytes, kind: str) -> bytes:
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            if img.width * img.height > MAX_PIXELS:
                raise UploadRejected("The image is too large.")
            img = img.convert("RGB")
            out = io.BytesIO()
            # Re-encode without passing any metadata (EXIF, GPS, ICC, comments are dropped).
            if kind == "png":
                img.save(out, format="PNG", optimize=True)
            else:
                img.save(out, format="JPEG", quality=92)
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as e:
        raise UploadRejected("The image could not be read.") from e


def harden(filename: str, data: bytes) -> CleanFile:
    """Validate and sanitise an upload, or raise UploadRejected."""
    if not data:
        raise UploadRejected("The file is empty.")
    if len(data) > MAX_BYTES:
        raise UploadRejected("The file is larger than 10 MB.")
    kind = _kind(filename)
    if not data.startswith(_MAGIC[kind]):
        raise UploadRejected("The file content does not match its extension.")
    if kind == "pdf":
        return CleanFile(kind, _MIME[kind], data, _check_pdf(data))
    return CleanFile(kind, _MIME[kind], _clean_image(data, kind), 1)
