import io

import pytest

from app.ai.offline_parser import parse
from app.ingestion.extract_text import acquire_tokens, render_pages
from app.samples.invoice_pdf import render_invoice_pdf
from tests.fixtures.invoices import KESAR_GSTIN, PLANT_X_GSTIN, bearings_invoice

EXPECTED_HEADER = {
    "invoice_number": "KES/26-27/0042", "invoice_date": "2026-11-05", "po_number": "4500001234",
    "place_of_supply": "24", "supplier_gstin": KESAR_GSTIN, "buyer_gstin": PLANT_X_GSTIN,
    "taxable_total": "74000.00", "cgst": "6660.00", "sgst": "6660.00", "igst": "0.00", "total": "87320.00",
    "bank_account": "50120034417921", "bank_ifsc": "SHYG0123456", "supplier_name": "Kesar Engineering Spares",
}
EXPECTED_LINE_1 = {"item_code": "BRG-6205", "hsn_sac": "8482", "qty": "100", "uom": "NOS",
                   "unit_price": "450.00", "taxable_value": "45000.00", "gst_rate": "18", "cgst": "4050.00"}


@pytest.fixture(scope="module")
def pdf() -> bytes:
    return render_invoice_pdf(bearings_invoice())


def _check(ex):
    for k, v in EXPECTED_HEADER.items():
        got = ex.header[k].value
        if k == "supplier_name":  # free text: OCR may drop spaces; suppliers are matched by GSTIN
            got, v = got.replace(" ", ""), v.replace(" ", "")
        assert got == v, k
    assert len(ex.lines) == 2
    for k, v in EXPECTED_LINE_1.items():
        assert ex.lines[0][k].value == v, k
    assert ex.lines[1]["qty"].value == "4"


def test_text_layer_extraction_with_locations(pdf):
    tokens, method = acquire_tokens(pdf, "pdf")
    assert method == "text"
    ex = parse(tokens, method)
    _check(ex)
    f = ex.header["invoice_number"]
    assert f.confidence >= 0.95 and f.page == 1 and f.source == "text"
    x0, y0, x1, y1 = f.bbox
    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


def test_tilted_blurry_phone_photo_keeps_rows_together(pdf):
    from PIL import ImageFilter

    page = render_pages(pdf, "pdf", dpi=130)[0]
    photo = page.rotate(1.2, expand=True, fillcolor="#d8d4cc").filter(ImageFilter.GaussianBlur(0.9))
    buf = io.BytesIO()
    photo.save(buf, format="JPEG", quality=40)
    tokens, method = acquire_tokens(buf.getvalue(), "jpg")
    ex = parse(tokens, method)
    assert len(ex.lines) == 2  # rows survive the tilt (deskewed line grouping)
    assert ex.lines[0]["item_code"].value == "BRG-6205" and ex.lines[0]["qty"].value == "100"
    assert ex.header["po_number"].value == "4500001234"


def _ocr_row(*cells: str):
    from app.ingestion.tokens import Token

    return [Token(text, 1, (0.05 + i * 0.07, 0.40, 0.11 + i * 0.07, 0.41), 0.95, "ocr") for i, text in enumerate(cells)]


def test_ocr_row_with_item_code_glued_to_description():
    """Seen on a scanned PDF: 'PKG-FIBC-1TJumbobagFIBC1tonn' (code and description in one token)."""
    ex = parse(_ocr_row("PKG-FIBC-1TJumbobagFIBC1tonn", "6305", "400", "NOS", "385.00", "1,54,000.00", "5",
                        "3,850.00", "3,850.00", "0.00"), "ocr")
    row = ex.lines[0]
    assert row["item_code"].value == "PKG-FIBC-1T" and row["description"].value == "JumbobagFIBC1tonn"
    assert row["hsn_sac"].value == "6305" and row["qty"].value == "400"


def test_ocr_row_without_hsn_is_kept_for_review():
    """Seen on a blurry photo: OCR lost the HSN cell. Keep the row; the HSN becomes a review item."""
    ex = parse(_ocr_row("PKG-FFS-50", "FFS", "bag50kgPE", "5000NOS", "21.00", "1,05,000.00", "18", "9,450.00",
                        "9,450.00", "0.00"), "ocr")
    row = ex.lines[0]
    assert row["item_code"].value == "PKG-FFS-50" and row["qty"].value == "5000" and row["uom"].value == "NOS"
    assert row["hsn_sac"].value is None


def test_text_layer_row_needs_hsn():
    """The PDF text layer never drops a cell, so a text row without an HSN is not an item line."""
    from app.ingestion.tokens import Token

    cells = ("PKG-FFS-50", "FFS", "bag", "5000", "NOS", "21.00", "1,05,000.00", "18", "9,450.00", "9,450.00", "0.00")
    tokens = [Token(t, 1, (0.05 + i * 0.07, 0.4, 0.11 + i * 0.07, 0.41), 1.0, "text") for i, t in enumerate(cells)]
    assert parse(tokens, "text").lines == []


def test_ocr_extraction_of_scanned_image(pdf):
    page = render_pages(pdf, "pdf", dpi=170)[0]
    buf = io.BytesIO()
    page.save(buf, format="PNG")
    tokens, method = acquire_tokens(buf.getvalue(), "png")
    assert method == "ocr"
    ex = parse(tokens, method)
    _check(ex)
    assert all(0 < f.confidence < 1 for _, f in ex.all_fields() if f.source == "ocr")
