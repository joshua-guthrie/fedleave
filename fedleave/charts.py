from __future__ import annotations

from pathlib import Path
import json
import typer
import matplotlib.pyplot as plt

from .ledger import calculate_balances
from .config import get_default_data_dir

app = typer.Typer()


@app.command()
def generate(
    year: int = typer.Option(..., help="Leave year."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
    output: str = typer.Option("chart.png", help="Output PNG path."),
) -> None:
    """Generate a simple PNG chart of core leave balances for a year."""
    base = get_default_data_dir(data_dir)
    year_file = base / "leave_years" / f"{year}.json"
    if not year_file.exists():
        raise typer.Exit(code=1)

    ly = json.loads(year_file.read_text())
    balances = calculate_balances(ly)

    categories = ["annual", "sick", "comp", "credit"]
    values = [balances.get(c, 0.0) for c in categories]

    plt.style.use("seaborn-v0_8")
    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(categories, values, color=["#2b8cbe", "#7fbf7b", "#fdae61", "#d7191c"])
    ax.set_title(f"Leave Balances — {year}")
    ax.set_ylabel("Hours")
    ax.set_ylim(0, max(values) * 1.2 if max(values) > 0 else 10)

    for bar in bars:
        h = bar.get_height()
        ax.annotate(f"{h:.1f}", xy=(bar.get_x() + bar.get_width() / 2, h), xytext=(0, 3), textcoords="offset points", ha="center", va="bottom")

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    typer.echo(f"Saved chart to {output}")


if __name__ == "__main__":
    app()
