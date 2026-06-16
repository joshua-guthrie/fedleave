from __future__ import annotations

from pathlib import Path
import typer
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from .config import get_default_data_dir
from .charts import generate as generate_chart

app = typer.Typer()


@app.command()
def generate(
    year: int = typer.Option(..., help="Leave year."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
    chart: str | None = typer.Option(None, help="Path to existing chart PNG."),
    output: str = typer.Option("fedleave_report.pdf", help="Output PDF path."),
) -> None:
    """Generate a simple PDF report for a leave year embedding a chart PNG.

    If `--chart` is not provided the command will generate a chart PNG first.
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
        raise typer.Exit(code=2)

    # create a simple PDF with the chart embedded
    with PdfPages(output) as pdf:
        fig = plt.figure(figsize=(8.5, 11))
        plt.axis("off")
        plt.text(0.5, 0.95, f"Fedleave Report — {year}", ha="center", va="top", size=20)
        img = plt.imread(str(chart_path))
        ax = fig.add_axes([0.1, 0.2, 0.8, 0.6])
        ax.imshow(img)
        ax.axis("off")
        pdf.savefig(fig)
        plt.close(fig)

    typer.echo(f"Saved report to {output}")


if __name__ == "__main__":
    app()
