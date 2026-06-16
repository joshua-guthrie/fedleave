#!/usr/bin/env python3
"""Generate example ODT templates for fedleave reports."""
from pathlib import Path
from odf.opendocument import OpenDocumentText
from odf.style import Style, TextProperties
from odf.text import H, P

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
TEMPLATES_DIR.mkdir(exist_ok=True)

# create a report template with placeholders for TITLE, CHART, and SUMMARY_TABLE
odt = OpenDocumentText()
# add a title style
hstyle = Style(name="TitleStyle", family="paragraph")
hstyle.addElement(TextProperties(attributes={"fontsize": "18pt", "fontweight": "bold"}))
odt.automaticstyles.addElement(hstyle)

odt.text.addElement(H(outlinelevel=1, text="{{TITLE}}"))
odt.text.addElement(P(text=""))
odt.text.addElement(P(text="{{CHART}}"))
odt.text.addElement(P(text=""))
odt.text.addElement(P(text="{{SUMMARY_TABLE}}"))

out = TEMPLATES_DIR / "report_template.odt"
odt.save(str(out))
print("Wrote template:", out)
