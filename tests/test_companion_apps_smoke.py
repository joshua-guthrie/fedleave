import json
import shutil
import subprocess
import sys


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, check=True, **kwargs)


def test_companion_chart_apps_generate_pngs_from_source(tmp_path):
    fedleave = shutil.which("fedleave")
    assert fedleave is not None

    data_dir = tmp_path / "data"
    _run(
        [
            fedleave,
            "init",
            "--year",
            "2026",
            "--leave-year-start",
            "2026-01-11",
            "--annual-accrual",
            "6",
            "--annual-start",
            "120",
            "--sick-start",
            "180",
            "--data-dir",
            str(data_dir),
        ]
    )

    apps = [
        ("annual_leave_chart", tmp_path / "annual.png", "annual-leave-chart-png"),
        ("sick_leave_chart", tmp_path / "sick.png", "sick-leave-chart-png"),
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
