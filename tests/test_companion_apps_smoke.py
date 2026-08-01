import json
import os
import subprocess
import sys
from pathlib import Path

from fedleave.config import init_config

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    env = kwargs.pop("env", os.environ.copy())
    env["PATH"] = os.pathsep.join([str(ROOT / "bin"), env.get("PATH", "")])
    result = subprocess.run(cmd, text=True, capture_output=True, check=False, env=env, **kwargs)
    if result.returncode != 0:
        raise AssertionError(
            "Command failed with exit code "
            f"{result.returncode}: {cmd}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def test_companion_chart_apps_generate_pngs_from_source(tmp_path):
    data_dir = tmp_path / "data"
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={
            "annual": 120.0,
            "sick": 180.0,
            "comp": 0.0,
            "credit": 0.0,
            "travel_comp": 0.0,
            "time_off_award": 0.0,
            "religious_comp": 0.0,
            "restored_annual": 0.0,
        },
        data_dir=data_dir,
    )

    apps = [
        ("annual_leave_chart", tmp_path / "annual.png", "annual-leave-chart-png"),
        ("sick_leave_chart", tmp_path / "sick.png", "sick-leave-chart-png"),
        ("credit_hours_chart", tmp_path / "credit.png", "credit-hours-chart-png"),
        ("comp_time_chart", tmp_path / "comp.png", "comp-time-chart-png"),
        ("travel_comp_chart", tmp_path / "travel.png", "travel-comp-chart-png"),
        ("time_off_award_chart", tmp_path / "toa.png", "time-off-award-chart-png"),
    ]
    for module, output, product in apps:
        result = _run(
            [
                sys.executable,
                "-m",
                module,
                "--outputFile",
                str(output),
                "--data-dir",
                str(data_dir),
            ]
        )
        payload = json.loads(result.stdout)

        assert payload["ok"] is True
        assert payload["product"] == product
        assert payload["year"] == 2026
        assert payload["point_count"] == 26
        assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    month_png = tmp_path / "month.png"
    result = _run(
        [
            sys.executable,
            "-m",
            "fedleave_month_report_graphic",
            "--year",
            "2026",
            "--month",
            "July",
            "--outputFile",
            str(month_png),
            "--data-dir",
            str(data_dir),
        ]
    )
    assert "Created output:" in result.stdout
    assert month_png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
