#!/usr/bin/env python3
"""Generate example ODT templates for fedleave reports."""
from pathlib import Path
from odf.opendocument import OpenDocumentText
from odf.style import Style, TextProperties
from odf.text import H, P

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
TEMPLATES_DIR.mkdir(exist_ok=True)

odt = OpenDocumentText()

# Title style
hstyle = Style(name="TitleStyle", family="paragraph")
hstyle.addElement(TextProperties(attributes={"fontsize": "26pt", "fontweight": "bold"}))
odt.automaticstyles.addElement(hstyle)

# Subtitle style
subtitle_style = Style(name="SubtitleStyle", family="paragraph")
subtitle_style.addElement(TextProperties(attributes={"fontsize": "12pt", "fontstyle": "italic"}))
odt.automaticstyles.addElement(subtitle_style)

# Section heading style
h2style = Style(name="Heading2", family="paragraph")
h2style.addElement(TextProperties(attributes={"fontsize": "14pt", "fontweight": "bold"}))
odt.automaticstyles.addElement(h2style)

odt.text.addElement(H(outlinelevel=1, text="{{TITLE}}"))
odt.text.addElement(P(text="{{DATE}}", stylename=subtitle_style))
odt.text.addElement(P(text="{{PREPARED_BY}}", stylename=subtitle_style))
odt.text.addElement(P(text=""))

odt.text.addElement(H(outlinelevel=2, text="Executive Summary"))
odt.text.addElement(P(text="{{SUMMARY_TABLE}}"))
odt.text.addElement(P(text=""))

odt.text.addElement(H(outlinelevel=2, text="Leave Balance Chart"))
odt.text.addElement(P(text="{{CHART}}"))
odt.text.addElement(P(text=""))

odt.text.addElement(H(outlinelevel=2, text="Notes"))
odt.text.addElement(P(text="This report includes a summary of core leave balances and an embedded chart. Use the fedleave CLI for detailed ledger and transaction reports."))

out = TEMPLATES_DIR / "report_template.odt"
odt.save(str(out))
print("Wrote template:", out)
