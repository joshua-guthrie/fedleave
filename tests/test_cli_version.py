from typer.testing import CliRunner

from fedleave import __version__
from fedleave.cli import app


def test_version_option_reports_package_version():
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"fedleave {__version__}"
