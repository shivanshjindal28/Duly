"""Controls report as a PDF (reportlab platypus). Same data as the on-screen report."""
from __future__ import annotations

import io
import json

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core import clock
from app.reports.controls import ControlsReport

NAVY = colors.HexColor("#0B1F44")
RESULT = {"effective": ("Effective", colors.HexColor("#157A42")),
          "exceptions": ("Exceptions", colors.HexColor("#B0005B")),
          "no_activity": ("No activity", colors.HexColor("#5B6B82"))}


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(report: ControlsReport) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title="Duly controls report", author="Duly")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], textColor=NAVY, fontSize=17, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY, fontSize=12, spaceBefore=10, spaceAfter=3)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.8, leading=11.5)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#5B6B82"))
    story = [
        Paragraph("Duly: controls report for auditors", h1),
        Paragraph(f"Plant X Polymers Pvt Ltd (fictional) · Period {report.period_from:%d %b %Y} to "
                  f"{report.period_to:%d %b %Y} · Generated {report.generated_at.astimezone(clock.IST):%d %b %Y %H:%M} IST",
                  small),
        Spacer(1, 6),
        Paragraph(f"<b>Overall opinion:</b> {_esc(report.opinion)}", body),
        Spacer(1, 8),
    ]
    rows = [["ID", "Control", "Result", "Tested", "Exceptions"]]
    for c in report.controls:
        rows.append([c.id, Paragraph(_esc(c.title), body), RESULT[c.result][0], str(c.population), str(len(c.exceptions))])
    t = Table(rows, colWidths=[14 * mm, 92 * mm, 26 * mm, 18 * mm, 22 * mm])
    style = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DCE3EC")),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    for r, c in enumerate(report.controls, start=1):
        style.append(("TEXTCOLOR", (2, r), (2, r), RESULT[c.result][1]))
    t.setStyle(TableStyle(style))
    story += [t]

    for c in report.controls:
        label, color = RESULT[c.result]
        block = [
            Paragraph(f"{c.id} · {_esc(c.title)} · <font color='{color.hexval()}'>{label}</font>", h2),
            Paragraph(f"<b>Objective.</b> {_esc(c.objective)}", body),
            Paragraph(f"<b>How Duly enforces it.</b> {_esc(c.how)}", body),
            Paragraph(f"<b>Test performed.</b> {_esc(c.test)}", body),
        ]
        metrics = {k: v for k, v in c.metrics.items() if k != "users"}
        if metrics:
            block.append(Paragraph(f"<b>Figures.</b> {_esc(json.dumps(metrics, ensure_ascii=False))}", small))
        for e in c.exceptions[:15]:
            ref = f"{e.get('invoice_number')}: " if e.get("invoice_number") else ""
            block.append(Paragraph(f"• Exception: {_esc(ref + e['detail'])}", body))
        for e in c.evidence[:6]:
            block.append(Paragraph(f"• Evidence: {_esc(e.get('detail') or e.get('label', ''))}"
                                   + (f" ({_esc(e['invoice_number'])})" if e.get("invoice_number") else ""), small))
        if c.id == "C-10":
            urows = [["User", "Role", "MFA", "Last login", "Locked"]] + [
                [u["name"], u["role"] + (f" L{u['level']}" if u["level"] else ""), "yes" if u["mfa"] else "no",
                 (u["last_login"] or "never")[:16].replace("T", " "), "yes" if u["locked"] else "no"]
                for u in c.metrics.get("users", [])]
            ut = Table(urows, colWidths=[46 * mm, 32 * mm, 14 * mm, 40 * mm, 16 * mm])
            ut.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5),
                                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#DCE3EC")),
                                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F6"))]))
            block += [Spacer(1, 3), ut]
        story.append(KeepTogether(block))

    story.append(Paragraph("Overrides (FLAG routed for approval with justification)", h2))
    if not report.overrides:
        story.append(Paragraph("No overrides in the period.", body))
    for o in report.overrides:
        story.append(Paragraph(f"• <b>{_esc(o['invoice_number'])}</b> (Rs {_esc(o['total'])}), by {_esc(o['by'])}: "
                               f"\"{_esc(o['justification'])}\". Approved by: {_esc(', '.join(o['approved_by']) or 'pending')}; "
                               f"status {_esc(o['status'])}.", body))
    story += [Spacer(1, 10), Paragraph("Synthetic data. Plant X is a fictional company. Generated by Duly from live "
                                       "application data; every figure can be traced to the audit trail.", small)]
    doc.build(story)
    return buf.getvalue()
