"""Launch the released CLI, Calendar and Analytics on an independent Linux host.

Only standard library modules are used so the test container need not install
FedLeave or Qt. Every application uses the extracted archive's own runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import tempfile
from datetime import date
from pathlib import Path


def smoke(bundle: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="fedleave-runtime-") as folder:
        root = Path(folder)
        data = root / "data"
        env = {
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "xdg"),
        }
        env.pop("LD_LIBRARY_PATH", None)
        env.pop("PYTHONPATH", None)
        cli = bundle / "fedleave"

        def run(command):
            subprocess.run(list(map(str, command)), env=env, check=True, timeout=90)

        today = date.today()
        run([cli, "--version"])
        run(
            [
                cli,
                "init",
                "--year",
                today.year,
                "--leave-year-start",
                f"{today.year}-01-01",
                "--pay-periods",
                "27",
                "--data-dir",
                data,
                "--json",
            ]
        )

        def hashes():
            return {
                str(path.relative_to(data)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in data.rglob("*")
                if path.is_file()
            }

        before = hashes()
        for application in ("FedLeaveCalendar", "FedLeaveAnalytics"):
            command = [bundle / application, "--smoke-test", "--backend", cli, "--data-dir", data]
            if application == "FedLeaveAnalytics":
                command += ["--year", today.year]
            run(command)
        if hashes() != before:
            raise RuntimeError("Packaged GUI smoke tests modified the leave datastore")
        print("Released CLI, Calendar and Analytics launched/rendered; datastore hashes unchanged.")


def release_archive(artifact_dir: Path) -> Path:
    """Uploads with multiple roots preserve artifacts/ inside the downloaded zip."""
    archives = sorted(artifact_dir.rglob("FedLeave-*-Linux-x86_64.tar.gz"))
    if len(archives) != 1:
        raise RuntimeError(f"Expected exactly one Linux archive under {artifact_dir}; found {len(archives)}")
    return archives[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--bundle-dir", type=Path)
    source.add_argument("--archive-dir", type=Path)
    options = parser.parse_args()
    if options.bundle_dir:
        smoke(options.bundle_dir.resolve())
    else:
        archive = release_archive(options.archive_dir.resolve())
        with tempfile.TemporaryDirectory(prefix="fedleave-extracted-") as folder:
            subprocess.run(["tar", "-xzf", str(archive), "-C", folder], check=True)
            smoke(Path(folder) / "FedLeave")
