import json, re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, PageBreak
from reportlab.lib.enums import TA_CENTER

SRC = 'akhil_gollapudi_resume_executive_customer_impact.json'
OUT = 'Akhil_Gollapudi_Resume_Executive_Customer_Impact_Readable.pdf'

with open(SRC, encoding='utf-8') as f:
    d = json.load(f)

base = getSampleStyleSheet()
INK = colors.HexColor('#202124')
MUTED = colors.HexColor('#5F6368')
ACC = colors.HexColor('#174EA6')
RULE = colors.HexColor('#DADCE0')

styles = {
    'name': ParagraphStyle('name', parent=base['Normal'], fontName='Helvetica-Bold',
        fontSize=19, leading=22.5, alignment=TA_CENTER, textColor=INK, spaceAfter=4),
    'label': ParagraphStyle('label', parent=base['Normal'], fontName='Helvetica',
        fontSize=11, leading=13.8, alignment=TA_CENTER, textColor=MUTED, spaceAfter=6),
    'contact': ParagraphStyle('contact', parent=base['Normal'], fontName='Helvetica',
        fontSize=9.1, leading=11.5, alignment=TA_CENTER, textColor=MUTED),
    'section': ParagraphStyle('section', parent=base['Normal'], fontName='Helvetica-Bold',
        fontSize=11.3, leading=13.8, textColor=ACC, spaceBefore=8, spaceAfter=4),
    'body': ParagraphStyle('body', parent=base['Normal'], fontName='Helvetica',
        fontSize=10.6, leading=14.4, textColor=INK, spaceAfter=2.8),
    'company': ParagraphStyle('company', parent=base['Normal'], fontName='Helvetica-Bold',
        fontSize=11.2, leading=14, textColor=INK, spaceBefore=6, spaceAfter=2),
    'role': ParagraphStyle('role', parent=base['Normal'], fontName='Helvetica',
        fontSize=10.6, leading=13.8, textColor=MUTED, spaceAfter=4),
    'project': ParagraphStyle('project', parent=base['Normal'], fontName='Helvetica-Bold',
        fontSize=10.7, leading=13.8, textColor=ACC, spaceBefore=4, spaceAfter=2),
    'bullet': ParagraphStyle('bullet', parent=base['Normal'], fontName='Helvetica',
        fontSize=10.6, leading=14.4, textColor=INK, leftIndent=12,
        firstLineIndent=-7, spaceAfter=3.0),
    'skill': ParagraphStyle('skill', parent=base['Normal'], fontName='Helvetica',
        fontSize=10.3, leading=14, textColor=INK, spaceAfter=2.7),
    'small': ParagraphStyle('small', parent=base['Normal'], fontName='Helvetica',
        fontSize=10.2, leading=13.8, textColor=INK, spaceAfter=2.7),
}

def clean(s):
    s = s.replace('—', '-').replace('–', '-')
    return re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)


def highlight_ai_sdlc(s):
    """Bold only the highest-value recruiter-scan terms in the AI-SDLC bullets."""
    terms = [
        # Architecture / platform
        'multi-agent AI SDLC platform',
        'Claude SDK',
        'Agent-to-Agent (A2A)',
        '30%',
        # Requirements / developer workflow
        'Requirement & Developer Agents',
        'Jira',
        'Bitbucket',
        'MCP',
        'spec.md',
        '50%',
        'Human-in-the-Loop (HITL)',
        # PR review
        'PR Review Agent',
        'State Graphs',
        '40%',
        # QA
        'JMeter',
        'Bruno',
        'Playwright',
        '15+ hours',
        # DevOps / architecture
        'DevOps & Architect Agents',
        'AWS MCP',
        'Infrastructure as Code (IaC)',
        'CI/CD',
        '30+ engineering teams',
        # Executive influence and customer outcomes
        'C-suite executives',
        'senior stakeholders',
        'customer pain points',
        'technical roadmaps',
        'adoption opportunities',
    ]

    # Longest first prevents partial matches inside larger phrases.
    for term in sorted(terms, key=len, reverse=True):
        if term in s:
            s = s.replace(term, f'<b>{term}</b>')
    return s

def fmt(x):
    if not x:
        return 'Present'
    p = x.split('-')
    mons = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    return f'{mons[int(p[1])-1]} {p[0]}' if len(p) == 2 else x

def sec(story, title):
    story.append(Paragraph(title, styles['section']))
    story.append(HRFlowable(width='100%', thickness=.6, color=RULE,
                            spaceBefore=2, spaceAfter=4))

story = []
b = d['basics']

story.extend([
    Paragraph(b['name'], styles['name']),
    Paragraph(b['label'], styles['label'])
])

contact = (
    f"{b['location']}  |  {b['phone']}  |  {b['email']}  |  "
    f"LinkedIn: {b['profiles'][0]['url']}"
)
story.extend([Paragraph(contact, styles['contact']), Spacer(1, 6)])

sec(story, 'SUMMARY')
story.append(Paragraph(clean(b['summary']), styles['body']))

sec(story, 'EXPERIENCE')

work = d['work']
i = 0

while i < len(work):
    company = work[i]['company']
    position = work[i]['position']
    group = []

    while i < len(work) and work[i]['company'] == company and work[i]['position'] == position:
        group.append(work[i])
        i += 1

    start = min(x['startDate'] for x in group if x.get('startDate'))
    end = (
        'Present'
        if any(not x.get('endDate') for x in group)
        else fmt(max(x['endDate'] for x in group if x.get('endDate')))
    )

    for project in group:
        # Balanced two-page layout: continue the long Verisk role on page 2
        # at a natural project boundary rather than leaving large blank areas.
        if project.get('project') == 'Agentic Claims Processing (POC)':
            # Continue naturally on page 2; avoid a forced page break that created page 3.
            pass
        elif project is group[0]:
            story.extend([
                Paragraph(company, styles['company']),
                Paragraph(f'{position}  |  {fmt(start)} - {end}', styles['role'])
            ])

        if project.get('project'):
            story.append(
                Paragraph(
                    f"<b>{project['project']}</b>  |  "
                    f"{fmt(project['startDate'])} - {fmt(project.get('endDate', ''))}",
                    styles['project']
                )
            )

            # AI-SDLC is the flagship project: show its technology stack
            # without turning the whole section into bold text.
            if project['project'] == 'AI-Driven Software Development Life Cycle (AI SDLC) Platform' and project.get('technologies'):
                tech = project['technologies']
                for term in ['Claude SDK (Sonnet)', 'Multi-Agent Systems (A2A)',
                             'LangGraph (State Graphs)', 'Model Context Protocol (MCP)',
                             'AWS', 'Bitbucket', 'Jira', 'Playwright', 'JMeter',
                             'Bruno', 'CI/CD']:
                    tech = tech.replace(term, f'<b>{term}</b>')
                story.append(
                    Paragraph(f'<b>Technologies:</b> {tech}', styles['skill'])
                )

        for highlight in project.get('highlights', []):
            bullet_text = clean(highlight)
            if project.get('project') == 'AI-Driven Software Development Life Cycle (AI SDLC) Platform':
                bullet_text = highlight_ai_sdlc(bullet_text)
            story.append(Paragraph('• ' + bullet_text, styles['bullet']))

sec(story, 'LEADERSHIP & TECHNICAL EXPERTISE')

curated = [
    ('Leadership',
     'People Management, Performance Reviews, Hiring & Interviewing, Coaching, '
     'Technical Strategy, Roadmaps, Cross-Functional Delivery'),
    ('AI & Agentic Systems',
     'Generative AI, Agentic AI, Multi-Agent Systems, Claude/Sonnet, '
     'Amazon Bedrock AgentCore, LangGraph, RAG, MCP, A2A, LLMOps'),
    ('Architecture & Engineering',
     'Distributed Systems, System Architecture, ADRs, Security/Threat Modeling, '
     'Python, SQL, FastAPI, PySpark'),
    ('Cloud & Delivery',
     'AWS, EKS, Lambda, S3, Glue, Batch, IAM, Kubernetes, IaC, CI/CD, '
     'Observability, Reliability Engineering'),
    ('Data Platforms',
     'OpenSearch, PostgreSQL, Snowflake, Redis, Oracle RDS, Data Lakes'),
]

for name, value in curated:
    story.append(Paragraph(f'<b>{name}:</b> {value}', styles['skill']))

sec(story, 'EDUCATION & RECOGNITION')

education = d['education'][0]
story.append(
    Paragraph(
        f"<b>{education['studyType']}, {education['area']}</b> - "
        f"{education['institution']}",
        styles['small']
    )
)

awards = '  |  '.join(
    f"<b>{a['title']}</b> ({a['date']})" if a.get('date')
    else f"<b>{a['title']}</b>"
    for a in d['awards']
)
story.append(Paragraph(awards, styles['small']))

doc = SimpleDocTemplate(
    OUT,
    pagesize=A4,
    rightMargin=42,
    leftMargin=42,
    topMargin=30,
    bottomMargin=30,
    title='Akhil Gollapudi - Engineering Leader Resume',
    author='Akhil Gollapudi'
)

doc.build(story)
print(OUT)
