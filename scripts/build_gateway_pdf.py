"""Generate the French delivery guide using the bundled ReportLab runtime."""
from pathlib import Path
from html import escape
import re
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="BodyFR", fontName="Helvetica", fontSize=10, leading=15, spaceAfter=8))
styles.add(ParagraphStyle(name="CodeFR", fontName="Courier", fontSize=7.3, leading=10,
    backColor=colors.HexColor("#f0f4f8"), borderPadding=8, spaceBefore=5, spaceAfter=10))
styles['Title'].textColor = colors.HexColor('#12344b')
styles['Heading2'].textColor = colors.HexColor('#087e8b')
styles['Heading2'].spaceBefore = 15
story = []
text = (ROOT / 'docs/partie3-gateway-mqtt.md').read_text(encoding='utf-8-sig')
code = False
buffer = []

def flush():
    if not buffer:
        return
    if code:
        # Wrap long commands without clipping; continuation indentation is visual only.
        import textwrap
        lines = []
        for line in buffer:
            lines.extend(textwrap.wrap(line, width=104, subsequent_indent='    ',
                                      break_long_words=True, replace_whitespace=False) or [''])
        story.append(Preformatted('\n'.join(lines), styles['CodeFR']))
    else:
        story.append(Paragraph(escape(' '.join(buffer)), styles['BodyFR']))
    buffer.clear()

for line in text.splitlines():
    if line.startswith('```'):
        flush()
        code = not code
    elif code:
        buffer.append(line)
    elif line.startswith('# '):
        flush()
        story.append(Paragraph(escape(line[2:]), styles['Title']))
    elif line.startswith('## '):
        flush()
        story.append(Paragraph(escape(line[3:]), styles['Heading2']))
    elif not line.strip():
        flush()
    else:
        buffer.append(line)
flush()

def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor('#d4e2eb'))
    canvas.line(44, 40, A4[0]-44, 40)
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#496174'))
    canvas.drawString(44, 27, 'SmartHarness | Partie 3 - Gateway & MQTT | 29/10/2026')
    canvas.drawRightString(A4[0]-44, 27, str(doc.page))
    canvas.restoreState()

output = ROOT / 'docs/Partie3_Gateway_MQTT.pdf'
doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=44, leftMargin=44,
                        topMargin=42, bottomMargin=55,
                        title='SmartHarness - Partie 3 Gateway et MQTT', author='SmartHarness')
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(output)
