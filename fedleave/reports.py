from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import typer
import matplotlib.pyplot as plt

from .config import get_default_data_dir
from .charts import generate as generate_chart

try:
    from odf.opendocument import OpenDocumentText
    from odf.text import P
    from odf.draw import Frame, Image
except Exception:
    OpenDocumentText = None

app = typer.Typer()


@app.command()
def generate(
    year: int = typer.Option(..., help="Leave year."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
    chart: str | None = typer.Option(None, help="Path to existing chart PNG."),
    output: str = typer.Option("fedleave_report.odt", help="Output ODT path."),
) -> None:
    """Generate an ODT report for a leave year embedding a chart PNG.

    If `libreoffice` is available the ODT will be converted to PDF as well.
    """
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

    # build a minimal ODT with header and embedded image
    doc = OpenDocumentText()
    doc.text.addElement(P(text=f"Fedleave Report — {year}"))

    # Create frame and image; odfpy will attempt to include the referenced file
    frame = Frame(width="16cm", height="10cm")
    img = Image(href=str(chart_path.name))
    frame.addElement(img)
    doc.text.addElement(frame)

    # Save ODT into the same directory as chart so relative image href resolves
    prev_cwd = None
    try:
        prev_cwd = Path.cwd()
        # Save from the report directory so image reference is local
        Path.chdir = None
    except Exception:
        pass

    # odfpy saves relative hrefs but will not package external files automatically in all cases.
    # Best-effort: copy chart into a temporary name next to odt and reference it by filename.
    target_chart_name = odt_path.parent / chart_path.name
    if chart_path.resolve() != target_chart_name.resolve():
        try:
            shutil.copy2(chart_path, target_chart_name)
        except Exception:
            pass

    doc.save(str(odt_path))

    typer.echo(f"Saved ODT report to {odt_path}")

    # If libreoffice is available, convert to PDF
    lo = shutil.which("libreoffice") or shutil.which("soffice")
    if lo:
        try:
            subprocess.run([lo, "--headless", "--convert-to", "pdf", str(odt_path), "--outdir", str(odt_path.parent)], check=True)
            pdf_path = odt_path.with_suffix(".pdf")
            if pdf_path.exists():
                typer.echo(f"Converted to PDF: {pdf_path}")
        except Exception as exc:
            typer.echo(f"LibreOffice conversion failed: {exc}")


if __name__ == "__main__":
    app()
