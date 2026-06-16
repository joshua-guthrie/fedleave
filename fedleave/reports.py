from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import typer

from .charts import generate as generate_chart
from .config import get_default_data_dir
from .ledger import calculate_balances

try:
    from odf.opendocument import OpenDocumentText
except Exception:
    OpenDocumentText = None

app = typer.Typer()


@app.command()
def generate(
    year: int = typer.Option(..., help="Leave year."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
    chart: str | None = typer.Option(None, help="Path to existing chart PNG."),
    output: str = typer.Option("fedleave_report.odt", help="Output ODT path."),
    template: str | None = typer.Option(None, help="Path to ODT template."),
) -> None:
    """Generate an ODT report for a leave year embedding a chart PNG.

    If `libreoffice` is available the ODT will be converted to PDF as well.
    """
    if not (isinstance(data_dir, Path) or data_dir is None):
        data_dir = None
    if not (isinstance(chart, str) or chart is None):
        chart = None
    if not (isinstance(template, str) or template is None):
        template = None
    if not (isinstance(output, str) or output is None):
        output = "fedleave_report.odt"

    base = get_default_data_dir(data_dir)
    report_dir = Path(output).parent
    report_dir.mkdir(parents=True, exist_ok=True)

    if chart:
        chart_path = Path(chart)
    else:
        chart_path = report_dir / f"chart_{year}.png"
        generate_chart(year=year, data_dir=data_dir, output=str(chart_path))

    if not chart_path.exists():
        typer.echo("Chart not found; aborting")
        raise typer.Exit(code=2)

    odt_path = Path(output)

    if OpenDocumentText is None:
        typer.echo("odfpy not installed; cannot generate ODT. Provide --chart or install odfpy.")
        raise typer.Exit(code=2)

    if template:
        template_path = Path(template)
    else:
        template_path = Path(__file__).parent.parent / "templates" / "report_template.odt"

    if not template_path.exists():
        typer.echo(f"Template not found: {template_path}")
        raise typer.Exit(code=2)

    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td) / "extracted"
        tmp_dir.mkdir()

        with zipfile.ZipFile(template_path, "r") as zin:
            zin.extractall(tmp_dir)

        pictures_dir = tmp_dir / "Pictures"
        pictures_dir.mkdir(exist_ok=True)

        pic_name = chart_path.name
        try:
            shutil.copy2(chart_path, pictures_dir / pic_name)
        except Exception:
            try:
                shutil.copy2(chart_path.resolve(), pictures_dir / pic_name)
            except Exception:
                raise typer.Exit(code=2)

        content_file = tmp_dir / "content.xml"
        if content_file.exists():
            content = content_file.read_text(encoding="utf-8")
            content = content.replace("{{TITLE}}", f"Fedleave Report — {year}")
            content = content.replace("{{DATE}}", datetime.now().strftime("%Y-%m-%d"))
            content = content.replace("{{PREPARED_BY}}", f"Prepared by {getpass.getuser()}")
            frame_xml = (
                f'<draw:frame draw:name="picture1" text:anchortype="as-char" svg:width="16cm" svg:height="10cm">'
                f'<draw:image xlink:href="Pictures/{pic_name}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>'
                f'</draw:frame>'
            )
            content = content.replace("{{CHART}}", frame_xml)
            balance_table = _build_summary_table(base, year)
            content = content.replace("<text:p>{{SUMMARY_TABLE}}</text:p>", balance_table)
            content_file.write_text(content, encoding="utf-8")
        else:
            typer.echo("Template content.xml missing; aborting")
            raise typer.Exit(code=2)

        with zipfile.ZipFile(str(odt_path), "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for root, dirs, files in os.walk(tmp_dir):
                for file in files:
                    full = Path(root) / file
                    rel = full.relative_to(tmp_dir)
                    zout.write(full, arcname=str(rel))

    typer.echo(f"Saved ODT report to {odt_path}")
    _convert_to_pdf(odt_path)


def _build_summary_table(base: Path, year: int) -> str:
    year_file = base / "leave_years" / f"{year}.json"
    if not year_file.exists():
        return "<text:p>Balance summary unavailable.</text:p>"

    leave_year = json.loads(year_file.read_text(encoding="utf-8"))
    balances = calculate_balances(leave_year)
    categories = [
        "annual",
        "sick",
        "comp",
        "credit",
        "travel_comp",
        "time_off_award",
        "religious_comp",
        "restored_annual",
    ]

    table_rows = [
        '<table:table table:name="SummaryTable">',
        '<table:table-row>',
        '<table:table-cell office:value-type="string"><text:p>Category</text:p></table:table-cell>',
        '<table:table-cell office:value-type="string"><text:p>Hours</text:p></table:table-cell>',
        '</table:table-row>',
    ]

    for category in categories:
        hours = f"{balances.get(category, 0.0):.2f}"
        table_rows.extend([
            '<table:table-row>',
            f'<table:table-cell office:value-type="string"><text:p>{category.replace("_", " ").title()}</text:p></table:table-cell>',
            f'<table:table-cell office:value-type="float" office:value="{hours}"><text:p>{hours}</text:p></table:table-cell>',
            '</table:table-row>',
        ])

    total_hours = sum(balances.get(category, 0.0) for category in categories)
    total_text = f"{total_hours:.2f}"
    table_rows.extend([
        '<table:table-row>',
        '<table:table-cell office:value-type="string"><text:p>Total</text:p></table:table-cell>',
        f'<table:table-cell office:value-type="float" office:value="{total_text}"><text:p>{total_text}</text:p></table:table-cell>',
        '</table:table-row>',
        '</table:table>',
    ])

    return "".join(table_rows)


def _convert_to_pdf(odt_path: Path) -> None:
    lo = shutil.which("libreoffice") or shutil.which("soffice")
    if not lo:
        return

    try:
        subprocess.run([lo, "--headless", "--convert-to", "pdf", str(odt_path), "--outdir", str(odt_path.parent)], check=True)
        pdf_path = odt_path.with_suffix(".pdf")
        if pdf_path.exists():
            typer.echo(f"Converted to PDF: {pdf_path}")
    except Exception as exc:
        typer.echo(f"LibreOffice conversion failed: {exc}")


if __name__ == "__main__":
    app()
