"""Render synthetic GST tax-invoice PDFs with reportlab.

Used by tests now and by `scripts/generate_invoices.py` (demo scenarios) later. Tax is
computed from the lines unless a scenario overrides it (for example to charge IGST on an
intra-state supply). All parties and numbers are fictional.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.pdfgen import canvas

from app.validation.gstin import STATE_CODES

TWO = Decimal("0.01")


def money(v: Decimal) -> Decimal:
    return v.quantize(TWO, rounding=ROUND_HALF_UP)


def inr(v: Decimal) -> str:
    """Indian digit grouping: 1234567.5 -> 12,34,567.50."""
    v = money(v)
    sign = "-" if v < 0 else ""
    whole, frac = f"{abs(v):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{whole}.{frac}"


@dataclass
class Party:
    name: str
    gstin: str
    address: str
    pan: str | None = None


@dataclass
class Line:
    item_code: str
    description: str
    hsn_sac: str
    qty: Decimal
    uom: str
    unit_price: Decimal
    gst_rate: Decimal


@dataclass
class InvoiceSpec:
    supplier: Party
    buyer: Party
    invoice_number: str
    invoice_date: date
    po_number: str | None
    lines: list[Line]
    place_of_supply: str | None = None  # state code; defaults to buyer's state
    bank_name: str | None = None
    bank_account: str | None = None
    bank_ifsc: str | None = None
    irn: str | None = None
    force_igst: bool | None = None  # scenario override: True = IGST, False = CGST+SGST
    total_override: Decimal | None = None  # scenario override: printed total differs
    hidden_text: str | None = None  # scenario: white text (prompt injection demo)
    signed_qr: str | None = None  # IRP-signed e-invoice QR payload (JWT), printed bottom-left
    metadata_subject: str | None = None  # scenario: instructions hidden in the PDF metadata
    extra_notes: list[str] = field(default_factory=list)

    @property
    def pos(self) -> str:
        return self.place_of_supply or self.buyer.gstin[:2]

    @property
    def inter_state(self) -> bool:
        if self.force_igst is not None:
            return self.force_igst
        return self.supplier.gstin[:2] != self.pos


@dataclass
class Computed:
    rows: list[dict]
    taxable: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    total: Decimal


def compute(spec: InvoiceSpec) -> Computed:
    rows, taxable, cgst, sgst, igst = [], Decimal(0), Decimal(0), Decimal(0), Decimal(0)
    for i, ln in enumerate(spec.lines, start=1):
        value = money(ln.qty * ln.unit_price)
        tax = money(value * ln.gst_rate / 100)
        if spec.inter_state:
            c = s = Decimal(0)
            g = tax
        else:
            c = money(tax / 2)
            s = tax - c
            g = Decimal(0)
        rows.append({"no": i, "line": ln, "value": value, "cgst": c, "sgst": s, "igst": g})
        taxable += value
        cgst += c
        sgst += s
        igst += g
    total = spec.total_override if spec.total_override is not None else taxable + cgst + sgst + igst
    return Computed(rows, taxable, cgst, sgst, igst, money(total))


def _qty(v: Decimal) -> str:
    return f"{v.normalize():f}" if v == v.to_integral() else f"{v:.3f}".rstrip("0")


def render_invoice_pdf(spec: InvoiceSpec) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, pageCompression=0)
    c.setTitle(f"Tax invoice {spec.invoice_number}")
    c.setAuthor(spec.supplier.name)
    if spec.metadata_subject:
        c.setSubject(spec.metadata_subject)
    width, height = A4
    left, right = 15 * mm, width - 15 * mm
    y = height - 18 * mm
    navy = colors.HexColor("#1F2A44")

    # Letterhead
    c.setFillColor(navy)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(left, y, spec.supplier.name)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 8.5)
    y -= 5 * mm
    c.drawString(left, y, spec.supplier.address)
    y -= 4.2 * mm
    state = STATE_CODES.get(spec.supplier.gstin[:2], "")
    c.drawString(left, y, f"GSTIN: {spec.supplier.gstin}")
    c.drawString(left + 62 * mm, y, f"State: {state} ({spec.supplier.gstin[:2]})")
    if spec.supplier.pan:
        c.drawString(left + 112 * mm, y, f"PAN: {spec.supplier.pan}")

    y -= 9 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, y, "TAX INVOICE")
    c.setLineWidth(0.6)
    c.line(left, y - 2.5 * mm, right, y - 2.5 * mm)

    if spec.signed_qr:
        # Vector QR (crisp modules at any render resolution), bottom-left block clear of all text.
        widget = QrCodeWidget(spec.signed_qr, barLevel="L", barBorder=4)
        x0, y0, x1, y1 = widget.getBounds()
        size = 55 * mm
        drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
        drawing.add(widget)
        renderPDF.draw(drawing, c, left, 36 * mm)
        c.setFont("Helvetica", 6)
        c.drawString(left + 4 * mm, 34 * mm, "Signed e-invoice QR (IRP)")

    # Invoice meta (right) and bill-to (left)
    y -= 9 * mm
    meta_x = left + 105 * mm
    c.setFont("Helvetica", 9)
    pos_name = STATE_CODES.get(spec.pos, "")
    meta = [
        f"Invoice No: {spec.invoice_number}",
        f"Invoice Date: {spec.invoice_date:%d-%m-%Y}",
        f"PO Number: {spec.po_number or ''}",
        f"Place of Supply: {pos_name} ({spec.pos})",
    ]
    for i, text in enumerate(meta):
        c.drawString(meta_x, y - i * 4.6 * mm, text)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left, y, "Bill To:")
    c.setFont("Helvetica", 9)
    c.drawString(left, y - 4.6 * mm, spec.buyer.name)
    c.drawString(left, y - 9.2 * mm, spec.buyer.address)
    c.drawString(left, y - 13.8 * mm, f"Buyer GSTIN: {spec.buyer.gstin}")

    # Line table
    y -= 24 * mm
    cols = [  # (header, x, align)
        # Amount columns are 18-20 mm apart so even ₹99,99,999.00 never touches its neighbour.
        ("#", left, "l"), ("Item Code", left + 5 * mm, "l"), ("Description", left + 25 * mm, "l"),
        ("HSN/SAC", left + 56 * mm, "l"), ("Qty", left + 76 * mm, "r"), ("UoM", left + 78 * mm, "l"),
        ("Rate", left + 98 * mm, "r"), ("Taxable", left + 118 * mm, "r"), ("GST%", left + 126 * mm, "r"),
        ("CGST", left + 144 * mm, "r"), ("SGST", left + 162 * mm, "r"), ("IGST", right, "r"),
    ]
    c.setFillColor(colors.HexColor("#EEF1F6"))
    c.rect(left - 1 * mm, y - 1.8 * mm, right - left + 2 * mm, 6 * mm, stroke=0, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 7.5)
    for head, x, align in cols:
        (c.drawRightString if align == "r" else c.drawString)(x, y, head)
    c.setFont("Helvetica", 7.5)
    comp = compute(spec)
    for row in comp.rows:
        y -= 6 * mm
        ln: Line = row["line"]
        cells = [
            str(row["no"]), ln.item_code, ln.description[:21], ln.hsn_sac, _qty(ln.qty), ln.uom,
            inr(ln.unit_price), inr(row["value"]), f"{ln.gst_rate.normalize():f}",
            inr(row["cgst"]), inr(row["sgst"]), inr(row["igst"]),
        ]
        for (_, x, align), text in zip(cols, cells, strict=True):
            (c.drawRightString if align == "r" else c.drawString)(x, y, text)
    y -= 3 * mm
    c.line(left, y, right, y)

    # Totals
    y -= 7 * mm
    c.setFont("Helvetica", 9)
    totals = [("Taxable Value", comp.taxable), ("CGST", comp.cgst), ("SGST", comp.sgst), ("IGST", comp.igst)]
    for label, value in totals:
        c.drawString(left + 120 * mm, y, label)
        c.drawRightString(right, y, inr(value))
        y -= 5 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(left + 120 * mm, y, "Total Invoice Value")
    c.drawRightString(right, y, inr(comp.total))

    # Bank and IRN
    y -= 12 * mm
    c.setFont("Helvetica", 8.5)
    if spec.bank_account:
        c.drawString(left, y, f"Bank: {spec.bank_name or ''}")
        c.drawString(left, y - 4.4 * mm, f"A/c No: {spec.bank_account}")
        c.drawString(left + 62 * mm, y - 4.4 * mm, f"IFSC: {spec.bank_ifsc or ''}")
        y -= 9 * mm
    if spec.irn:
        c.setFont("Helvetica", 7)
        c.drawString(left, y, f"IRN: {spec.irn}")
        y -= 4.4 * mm
    else:
        c.setFont("Helvetica-Oblique", 7.5)
        c.drawString(left, y, "e-invoice: not applicable (turnover below threshold)")
        y -= 4.4 * mm
    c.setFont("Helvetica", 7.5)
    for note in spec.extra_notes:
        c.drawString(left, y, note)
        y -= 4 * mm

    if spec.hidden_text:
        c.setFillColor(colors.white)
        c.setFont("Helvetica", 4)
        c.drawString(left, 20 * mm, spec.hidden_text)
        c.setFillColor(colors.black)

    c.setFont("Helvetica", 8)
    c.drawRightString(right, 32 * mm, f"For {spec.supplier.name}")
    c.drawRightString(right, 22 * mm, "Authorised Signatory")
    c.setFont("Helvetica-Oblique", 6.5)
    c.drawString(left, 12 * mm, "Synthetic document generated for the Duly demo. Plant X and all parties are fictional.")
    c.showPage()
    c.save()
    return buf.getvalue()


def with_einvoice(spec: InvoiceSpec) -> InvoiceSpec:
    """Register the invoice with the Sandbox IRP: set the IRN and the signed QR from the real totals.
    (A scenario can then change `total_override` to simulate an edited PDF.)"""
    from app.samples import sandbox_irp

    comp = compute(InvoiceSpec(**{**spec.__dict__, "total_override": None}))
    spec.irn = sandbox_irp.irn(spec.supplier.gstin, spec.invoice_number, spec.invoice_date)
    spec.signed_qr = sandbox_irp.sign(
        spec.supplier.gstin, spec.buyer.gstin, spec.invoice_number, spec.invoice_date, str(comp.total),
        len(spec.lines), spec.lines[0].hsn_sac if spec.lines else "", spec.irn)
    return spec
