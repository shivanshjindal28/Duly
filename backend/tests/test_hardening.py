import io

import pytest
from PIL import Image

from app.ingestion.hardening import MAX_BYTES, UploadRejected, harden
from app.samples.invoice_pdf import render_invoice_pdf
from tests.fixtures.invoices import bearings_invoice


@pytest.fixture(scope="module")
def pdf() -> bytes:
    return render_invoice_pdf(bearings_invoice())


def _image(exif: bool = False) -> bytes:
    img = Image.new("RGB", (40, 30), "white")
    buf = io.BytesIO()
    if exif:
        e = Image.Exif()
        e[0x010F] = "SecretPhoneMaker"  # EXIF Make tag
        img.save(buf, format="JPEG", exif=e.tobytes())
    else:
        img.save(buf, format="PNG")
    return buf.getvalue()


def test_clean_pdf_accepted(pdf):
    out = harden("invoice.pdf", pdf)
    assert out.kind == "pdf" and out.pages == 1 and out.data == pdf


@pytest.mark.parametrize("name", ["invoice.exe", "invoice", "invoice.docx", "invoice.pdf.js"])
def test_bad_extension_rejected(pdf, name):
    with pytest.raises(UploadRejected):
        harden(name, pdf)


def test_magic_bytes_must_match_extension(pdf):
    with pytest.raises(UploadRejected, match="does not match"):
        harden("invoice.png", pdf)
    with pytest.raises(UploadRejected, match="does not match"):
        harden("invoice.pdf", _image())


def test_size_limit(pdf):
    with pytest.raises(UploadRejected, match="10 MB"):
        harden("big.pdf", pdf + b"0" * MAX_BYTES)


@pytest.mark.parametrize("payload", [
    b"/OpenAction << /S /JavaScript /JS (app.alert(1)) >>",
    b"/AA << /O << /S /Launch /F (cmd.exe) >> >>",
    b"/Names << /EmbeddedFiles 3 0 R >>",
    b"/S /J#61vaScript",  # hex-obfuscated name
])
def test_active_pdf_content_rejected(pdf, payload):
    evil = pdf.replace(b"%%EOF", payload + b"\n%%EOF")
    with pytest.raises(UploadRejected, match="active or embedded content"):
        harden("invoice.pdf", evil)


def test_garbage_pdf_rejected():
    with pytest.raises(UploadRejected, match="could not be opened"):
        harden("invoice.pdf", b"%PDF-1.7\nnot really a pdf")


def test_image_metadata_stripped():
    raw = _image(exif=True)
    assert b"SecretPhoneMaker" in raw
    out = harden("photo.jpg", raw)
    assert b"SecretPhoneMaker" not in out.data
    assert out.kind == "jpg" and out.pages == 1
