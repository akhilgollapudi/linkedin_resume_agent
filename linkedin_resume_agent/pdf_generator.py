import re
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, KeepTogether
from pypdf import PdfReader
from .utils import plain_text

INK = colors.HexColor('#202124')
MUTED = colors.HexColor('#5F6368')
ACC = colors.HexColor('#174EA6')
RULE = colors.HexColor('#DADCE0')


def markup(text):
    """Escape untrusted text while retaining intentional <b> tags from the master JSON."""
    text = str(text or '').translate(str.maketrans({
        '‐': '-',
        '‑': '-',
        '‒': '-',
        '–': '-',
        '—': '-',
    }))
    parts = re.split(r'(<b>.*?</b>)', text)
    out = []
    for part in parts:
        if part.startswith('<b>') and part.endswith('</b>'):
            out.append('<b>' + escape(part[3:-4]) + '</b>')
        else:
            part = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', part)
            if '<b>' in part:
                bits = re.split(r'(<b>.*?</b>)', part)
                for bit in bits:
                    if bit.startswith('<b>') and bit.endswith('</b>'):
                        out.append('<b>' + escape(bit[3:-4]) + '</b>')
                    else:
                        out.append(escape(bit))
            else:
                out.append(escape(part))
    return ''.join(out)


def build_pdf(data, output_path, target_pages=2):
    base = getSampleStyleSheet()
    styles = {
        'name': ParagraphStyle('name', parent=base['Normal'], fontName='Helvetica-Bold', fontSize=19, leading=22.5, alignment=TA_CENTER, textColor=INK, spaceAfter=4),
        'label': ParagraphStyle('label', parent=base['Normal'], fontName='Helvetica', fontSize=11, leading=13.8, alignment=TA_CENTER, textColor=MUTED, spaceAfter=6),
        'contact': ParagraphStyle('contact', parent=base['Normal'], fontName='Helvetica', fontSize=9.1, leading=11.5, alignment=TA_CENTER, textColor=MUTED),
        'section': ParagraphStyle('section', parent=base['Normal'], fontName='Helvetica-Bold', fontSize=11.3, leading=13.4, textColor=ACC, spaceBefore=6, spaceAfter=3),
        'body': ParagraphStyle('body', parent=base['Normal'], fontName='Helvetica', fontSize=10.4, leading=13.2, textColor=INK, spaceAfter=2),
        'company': ParagraphStyle('company', parent=base['Normal'], fontName='Helvetica-Bold', fontSize=11.1, leading=13.2, textColor=INK, spaceBefore=4, spaceAfter=2),
        'role': ParagraphStyle('role', parent=base['Normal'], fontName='Helvetica', fontSize=10.4, leading=12.8, textColor=MUTED, spaceAfter=2),
        'project': ParagraphStyle('project', parent=base['Normal'], fontName='Helvetica-Bold', fontSize=10.5, leading=12.8, textColor=ACC, spaceBefore=2.5, spaceAfter=1),
        'bullet': ParagraphStyle('bullet', parent=base['Normal'], fontName='Helvetica', fontSize=10.2, leading=12.8, textColor=INK, leftIndent=12, firstLineIndent=-7, spaceAfter=1.5),
        'skill': ParagraphStyle('skill', parent=base['Normal'], fontName='Helvetica', fontSize=9.9, leading=12.5, textColor=INK, spaceAfter=1.5),
        'small': ParagraphStyle('small', parent=base['Normal'], fontName='Helvetica', fontSize=9.9, leading=12.5, textColor=INK, spaceAfter=1.5),
    }
    story = []
    b = data['basics']
    story += [Paragraph(markup(b['name']), styles['name']), Paragraph(markup(b.get('label', '')), styles['label'])]
    profile = (b.get('profiles') or [{}])[0].get('url', '')
    contact = '  |  '.join(x for x in [b.get('location', ''), b.get('phone', ''), b.get('email', ''), ('LinkedIn: ' + profile if profile else '')] if x)
    story += [Paragraph(markup(contact), styles['contact']), Spacer(1, 6)]

    def section(title):
        story.append(Paragraph(escape(title), styles['section']))
        story.append(HRFlowable(width='100%', thickness=.6, color=RULE, spaceBefore=1, spaceAfter=3))

    section('SUMMARY')
    story.append(Paragraph(markup(b.get('summary', '')), styles['body']))
    section('EXPERIENCE')
    work = data.get('work', [])
    # Group consecutive entries by employer + role, preserving the relevance order created by the tailoring engine.
    i = 0
    while i < len(work):
        company, position = work[i].get('company', ''), work[i].get('position', '')
        group = []
        while i < len(work) and work[i].get('company', '') == company and work[i].get('position', '') == position:
            group.append(work[i]); i += 1
        dates = [x.get('startDate') for x in group if x.get('startDate')]
        ends = [x.get('endDate') for x in group]
        def fmt(value):
            if not value: return 'Present'
            try:
                y, m = value.split('-')
                return ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(m)-1] + ' ' + y
            except Exception:
                return value
        start = fmt(min(dates)) if dates else ''
        end = 'Present' if any(not x for x in ends) else (fmt(max(ends)) if ends else '')
        story += [Paragraph(markup(company), styles['company']), Paragraph(markup(f'{position}  |  {start} - {end}'), styles['role'])]
        for project in group:
            p_name = project.get('project') or ''
            p_dates = f"{fmt(project.get('startDate'))} - {fmt(project.get('endDate'))}"
            if p_name:
                story.append(Paragraph(markup(f'{p_name}  |  {p_dates}'), styles['project']))
            for bullet in project.get('highlights', []):
                story.append(Paragraph('• ' + markup(bullet), styles['bullet']))

    section('LEADERSHIP & TECHNICAL EXPERTISE')
    for group in data.get('skills', []):
        kws = group.get('keywords', [])
        if kws:
            story.append(Paragraph(f"<b>{escape(group.get('name',''))}:</b> {markup(', '.join(kws))}", styles['skill']))
    section('EDUCATION & RECOGNITION')
    for edu in data.get('education', []):
        story.append(Paragraph(markup(f"{edu.get('studyType','')}, {edu.get('area','')} - {edu.get('institution','')} ({edu.get('startDate','')}–{edu.get('endDate','')})"), styles['small']))
    awards = data.get('awards', [])
    if awards:
        story.append(Paragraph('  |  '.join(markup(a.get('title','') + (f" ({a.get('date')})" if a.get('date') else '')) for a in awards), styles['small']))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, rightMargin=42, leftMargin=42, topMargin=30, bottomMargin=30,
                            title=f"{b.get('name','')} - Tailored Resume", author=b.get('name',''))
    doc.build(story)
    pages = len(PdfReader(str(output_path)).pages)
    if pages != target_pages:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"Generated resume is {pages} pages; required exactly {target_pages}. PDF was not retained. Reduce selected content or adjust layout deliberately.")
    return pages
