"""Run the FedLeave command-line application as ``python -m fedleave``."""

from .cli import app


def main() -> None:
    """Invoke the Typer application entry point."""
    app()
