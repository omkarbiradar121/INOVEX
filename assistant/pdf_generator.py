import io
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
    HRFlowable,
)

from .models import QueryLog


class SimpleNumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to print dynamic 'Page X of Y' footers and running headers
    in a clean, plain black-and-white style.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.black)

        page_w, page_h = A4
        margin = 54  # 0.75 in

        # Header on page 2 and later
        if self._pageNumber > 1:
            self.drawString(margin, page_h - 36, "INOVEX \u2014 Manufacturing Manual Assistant \u2013 Answer Report")
            self.setStrokeColor(colors.black)
            self.setLineWidth(0.5)
            self.line(margin, page_h - 40, page_w - margin, page_h - 40)

        # Footer on all pages
        self.setStrokeColor(colors.black)
        self.setLineWidth(0.5)
        self.line(margin, 46, page_w - margin, 46)

        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(page_w - margin, 32, page_str)
        self.drawString(margin, 32, "INOVEX \u2014 Manufacturing Manual Assistant")

        self.restoreState()


def generate_query_pdf_report(query_log: QueryLog) -> bytes:
    """
    Generates a simple, clean, normally structured A4 PDF report for an answered
    or investigated maintenance query in accordance with the specified standard format:
    1. Title: Manufacturing Manual Assistant – Answer Report
    2. Date and time
    3. Selected Machine (HP-200 / AC-90)
    4. Engineer's Question
    5. Generated Answer
    6. Supporting Manual References: Document name/ID, Revision, PDF page number, Supporting passage
    7. Answer Status (Answered / Insufficient Evidence)
    """
    buffer = io.BytesIO()

    margin = 54  # 0.75 inch margins
    printable_width = A4[0] - (2 * margin)  # 487.27 pt

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )

    base_styles = getSampleStyleSheet()

    # Clean, black-text typography
    style_brand = ParagraphStyle(
        "BrandHeader",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#1687E8"),
        spaceAfter=4,
    )

    style_title = ParagraphStyle(
        "ReportTitle",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.black,
        spaceAfter=12,
    )

    style_meta_label = ParagraphStyle(
        "MetaLabel",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        textColor=colors.black,
    )

    style_meta_val = ParagraphStyle(
        "MetaVal",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.black,
    )

    style_h2 = ParagraphStyle(
        "ReportH2",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12.5,
        leading=16.5,
        textColor=colors.black,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True,
    )

    style_body = ParagraphStyle(
        "ReportBody",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14.5,
        textColor=colors.black,
        spaceAfter=8,
    )

    style_citation_title = ParagraphStyle(
        "CitTitle",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13.5,
        textColor=colors.black,
        spaceBefore=6,
        spaceAfter=3,
        keepWithNext=True,
    )

    style_citation_detail = ParagraphStyle(
        "CitDetail",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=colors.black,
        spaceAfter=3,
    )

    style_citation_passage = ParagraphStyle(
        "CitPassage",
        parent=base_styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=9.5,
        leading=13.5,
        textColor=colors.black,
        leftIndent=14,
        spaceAfter=8,
    )

    story = []

    # -------------------------------------------------------------
    # 1. Title: Manufacturing Manual Assistant – Answer Report
    # -------------------------------------------------------------
    story.append(Paragraph("<b>INOVEX</b> &bull; Intelligent Manufacturing. Assured Quality.", style_brand))
    story.append(Paragraph("Manufacturing Manual Assistant &ndash; Answer Report", style_title))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceBefore=2, spaceAfter=12))

    # -------------------------------------------------------------
    # 2. Date and time & 3. Selected Machine (HP-200 / AC-90)
    # -------------------------------------------------------------
    timestamp_str = query_log.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    machine_display = f"{query_log.machine.name} ({query_log.machine.machine_id})"

    meta_table_data = [
        [Paragraph("Date and Time:", style_meta_label), Paragraph(timestamp_str, style_meta_val)],
        [Paragraph("Selected Machine:", style_meta_label), Paragraph(machine_display, style_meta_val)],
    ]
    t_meta = Table(meta_table_data, colWidths=[115, printable_width - 115])
    t_meta.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 8))

    # -------------------------------------------------------------
    # 4. Engineer's Question
    # -------------------------------------------------------------
    story.append(Paragraph("Engineer&rsquo;s Question", style_h2))
    story.append(Paragraph(query_log.question, style_body))
    story.append(Spacer(1, 4))

    # -------------------------------------------------------------
    # 5. Generated Answer
    # -------------------------------------------------------------
    story.append(Paragraph("Generated Answer", style_h2))
    answer_paragraphs = [p.strip() for p in query_log.answer.split("\n\n") if p.strip()]
    if not answer_paragraphs:
        answer_paragraphs = [query_log.answer]

    for p_text in answer_paragraphs:
        clean_p = p_text.replace("\n", "<br/>")
        story.append(Paragraph(clean_p, style_body))
    story.append(Spacer(1, 4))

    # -------------------------------------------------------------
    # 6. Supporting Manual References
    #    - Document name/ID
    #    - Revision
    #    - PDF page number
    #    - Supporting passage
    # -------------------------------------------------------------
    story.append(Paragraph("Supporting Manual References", style_h2))
    citations = query_log.citations or []
    if citations:
        for idx, cit in enumerate(citations, start=1):
            doc_id = cit.get("document_id", "N/A")
            doc_name = cit.get("document_name", doc_id)
            rev = cit.get("revision", "1.0")
            page_num = cit.get("page_number", "N/A")
            passage = cit.get("passage_text", "").replace("\n", " ").strip()

            ref_elements = []
            ref_elements.append(Paragraph(f"Reference {idx}: {doc_name} ({doc_id})", style_citation_title))
            ref_elements.append(Paragraph(f"&bull; <b>Revision:</b> {rev} &nbsp;&nbsp;&nbsp;&nbsp;&bull; <b>PDF Page Number:</b> Page {page_num}", style_citation_detail))
            if passage:
                ref_elements.append(Paragraph(f"&bull; <b>Supporting Passage:</b> &ldquo;{passage}&rdquo;", style_citation_passage))

            story.append(KeepTogether(ref_elements))
    else:
        story.append(Paragraph("No supporting manual references available for this query.", style_body))
    story.append(Spacer(1, 6))

    # -------------------------------------------------------------
    # 7. Answer Status (Answered / Insufficient Evidence)
    # -------------------------------------------------------------
    story.append(Paragraph("Answer Status", style_h2))
    status_display = "Answered" if query_log.status == QueryLog.STATUS_ANSWERED else "Insufficient Evidence"
    story.append(Paragraph(f"<b>Status:</b> {status_display}", style_body))

    # Build PDF
    doc.build(story, canvasmaker=SimpleNumberedCanvas)

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
