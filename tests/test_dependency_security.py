import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.version import Version


@pytest.mark.parametrize(
    "name,minimum", [("Pillow", "13.0.0"), ("icalendar", "7.1.3"), ("opentelemetry-api", "1.45.2")]
)
def test_loaded_environment_excludes_audited_vulnerable_versions(name, minimum):
    assert Version(version(name)) >= Version(minimum)


@pytest.mark.parametrize("runtime_only", [False, True])
def test_inventory_describes_resolved_environment_without_local_metadata(tmp_path, runtime_only):
    output = tmp_path / "inventory.json"
    requirements = tmp_path / "requirements.txt"
    command = [
        sys.executable,
        "scripts/lib/common/dependency_inventory.py",
        "--output",
        str(output),
        "--requirements",
        str(requirements),
    ]
    if runtime_only:
        command.append("--runtime-only")
    subprocess.run(command, cwd=Path(__file__).resolve().parents[1], check=True)
    result = json.loads(output.read_text())
    packages = result["packages"]
    for name in ("pillow", "icalendar", "mcp", "opentelemetry-api", "pyside6", "cryptography"):
        assert packages[name] == version(name)
    assert ("pytest" in packages) is (not runtime_only)
    lines = requirements.read_text().splitlines()
    assert "fedleave" in packages
    assert not any(line.startswith("fedleave==") for line in lines)
    assert lines == [f"{name}=={value}" for name, value in sorted(packages.items()) if name != "fedleave"]
    assert str(Path.cwd()) not in output.read_text() + requirements.read_text()
