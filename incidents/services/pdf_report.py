import io
import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


def build_incident_pdf(incident):
    """
    Generates a professional INOVEX Quality Incident PDF report in memory.
    Returns bytes buffer.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=54,
        bottomMargin=45
    )

    styles = getSampleStyleSheet()

    brand_style = ParagraphStyle(
        'PDFBrand',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=colors.HexColor('#14243A'),
    )
    tagline_style = ParagraphStyle(
        'PDFTagline',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#1687E8'),
        spaceAfter=10
    )
    title_style = ParagraphStyle(
        'PDFTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#14243A'),
        spaceAfter=12
    )
    section_h_style = ParagraphStyle(
        'PDFSecHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#14243A'),
        spaceBefore=8,
        spaceAfter=4
    )
    cell_bold = ParagraphStyle(
        'PDFCellBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#202B38')
    )
    cell_val = ParagraphStyle(
        'PDFCellVal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#202B38')
    )
    body_style = ParagraphStyle(
        'PDFBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#202B38'),
        spaceAfter=6
    )
    citation_style = ParagraphStyle(
        'PDFCitation',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#718096'),
        spaceAfter=4
    )

    story = []

    # Header / Branding
    story.append(Paragraph("<b>INOVEX</b> &nbsp;|&nbsp; QUALITY ASSURANCE DIVISION", brand_style))
    story.append(Paragraph("Intelligent Manufacturing. Assured Quality.", tagline_style))
    story.append(Paragraph(f"Quality Incident Report — {incident.incident_id}", title_style))
    story.append(Spacer(1, 4))

    # Overview Table
    created_str = incident.created_at.strftime('%Y-%m-%d %H:%M UTC') if incident.created_at else "N/A"
    overview_data = [
        [Paragraph("Incident ID:", cell_bold), Paragraph(incident.incident_id, cell_val),
         Paragraph("Created Date:", cell_bold), Paragraph(created_str, cell_val)],
        [Paragraph("Product ID:", cell_bold), Paragraph(incident.product.product_id, cell_val),
         Paragraph("Product Name:", cell_bold), Paragraph(incident.product.name, cell_val)],
        [Paragraph("Inspection ID:", cell_bold), Paragraph(f"#{incident.inspection.id}", cell_val),
         Paragraph("Initiated By:", cell_bold), Paragraph(incident.created_by.username, cell_val)],
        [Paragraph("Original AI Prediction:", cell_bold), Paragraph(f"<b>{incident.original_prediction}</b>", cell_val),
         Paragraph("AI Confidence:", cell_bold), Paragraph(f"{incident.original_confidence:.4f}" if incident.original_confidence else "N/A", cell_val)],
        [Paragraph("Evidence Status:", cell_bold), Paragraph(f"<b>{incident.evidence_status}</b>", cell_val),
         Paragraph("Review Status:", cell_bold), Paragraph(f"<b>{incident.review_status}</b>", cell_val)],
    ]
    t_overview = Table(overview_data, colWidths=[120, 145, 110, 155])
    t_overview.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_overview)
    story.append(Spacer(1, 10))

    # Incident Summary
    story.append(Paragraph("Incident Summary", section_h_style))
    story.append(Paragraph(incident.incident_summary, body_style))
    if incident.evidence_failure_reason:
        story.append(Paragraph(f"<b>Evidence Verification Note:</b> {incident.evidence_failure_reason}", body_style))
    story.append(Spacer(1, 8))

    # Suggested Actions & SOP Citations
    story.append(Paragraph("Evidence-Based Suggested Actions", section_h_style))
    actions = list(incident.actions.all())
    if actions:
        for act in actions:
            act_text = f"<b>Action #{act.action_order}:</b> {act.action_description}"
            story.append(Paragraph(act_text, body_style))
            citation_text = f"<b>Source Citation:</b> {act.sop_document_id} (Rev {act.revision}), Page {act.pdf_page_number} — <i>\"{act.supporting_passage}\"</i>"
            story.append(Paragraph(citation_text, citation_style))
            story.append(Spacer(1, 3))
    else:
        if incident.evidence_status == 'Insufficient':
            story.append(Paragraph("<i>No automated actions generated. Manual Review Required due to insufficient verified procedural evidence.</i>", body_style))
        else:
            story.append(Paragraph("<i>No actions recorded.</i>", body_style))

    story.append(Spacer(1, 10))

    # Supervisor Review Section
    story.append(Paragraph("Supervisor Review & Disposition History", section_h_style))
    reviews = list(incident.reviews.all())
    if reviews:
        for rev in reviews:
            rev_time = rev.reviewed_at.strftime('%Y-%m-%d %H:%M UTC')
            rev_data = [
                [Paragraph("Decision:", cell_bold), Paragraph(f"<b>{rev.decision}</b>", cell_val)],
                [Paragraph("Reviewed By:", cell_bold), Paragraph(rev.supervisor.username, cell_val)],
                [Paragraph("Timestamp:", cell_bold), Paragraph(rev_time, cell_val)],
                [Paragraph("Supervisor Comment:", cell_bold), Paragraph(rev.comment, cell_val)],
            ]
            t_rev = Table(rev_data, colWidths=[120, 410])
            t_rev.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFFFFF')),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(t_rev)
            story.append(Spacer(1, 6))
    else:
        story.append(Paragraph("<i>Pending Supervisor Review. No review decision has been recorded yet.</i>", body_style))

    def add_page_decorations(canvas, d):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#718096'))
        canvas.drawString(40, 755, 'INOVEX QUALITY INCIDENT DISPOSITION REPORT')
        canvas.drawRightString(572, 755, f'Page {d.page}')
        canvas.setStrokeColor(colors.HexColor('#CBD5E1'))
        canvas.line(40, 748, 572, 748)
        canvas.line(40, 38, 572, 38)
        canvas.drawString(40, 26, 'CONFIDENTIAL — INOVEX MANUFACTURING QUALITY SYSTEM')
        canvas.drawRightString(572, 26, 'VERIFIED INDUSTRIAL AUDIT TRAIL')
        canvas.restoreState()

    doc.build(story, onFirstPage=add_page_decorations, onLaterPages=add_page_decorations)
    buffer.seek(0)
    return buffer.getvalue()
