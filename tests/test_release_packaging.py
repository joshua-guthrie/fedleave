from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "installer" / "package.py"
BOOTSTRAP = ROOT / "installer" / "linux" / "install.sh"


def _load_packaging_module():
    spec = importlib.util.spec_from_file_location("fedleave_release_packaging", PACKAGE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_bundle(module, root: Path, platform: str = "linux") -> Path:
    bundle = root / ("fedleave-Ubuntu" if platform == "linux" else "fedleave-Windows")
    suffix = ".exe" if platform == "windows" else ""
    bundle.mkdir(parents=True)
    for command in module.project_scripts():
        executable = bundle / f"{command}{suffix}"
        if platform == "linux":
            executable.write_text(
                "#!/usr/bin/env bash\nif [[ ${1:-} == --version ]]; then echo 'fedleave 0.2.0'; else echo help; fi\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
        else:
            executable.write_bytes(b"not a real Windows executable")
    (bundle / "_internal").mkdir()
    (bundle / "_internal" / "runtime.dat").write_bytes(b"embedded runtime")
    return bundle


def _rolling_linux_assets(module, bundle: Path, artifacts: Path, version: str) -> None:
    archive, checksum = module.create_linux_archive(bundle, artifacts, version)
    rolling_archive = artifacts / "FedLeave-Latest-Linux-x86_64.tar.gz"
    archive.replace(rolling_archive)
    checksum.unlink()
    module.write_checksum(rolling_archive)


def test_version_and_windows_metadata_come_from_pyproject() -> None:
    module = _load_packaging_module()
    declared_version = module.project_metadata()["version"]

    assert module.project_version() == declared_version
    assert module.development_version("ABCDEF012345") == f"{declared_version}.dev0+gabcdef01"
    assert module.numeric_windows_version("12.3.4rc1") == "12.3.4.0"


def test_release_tag_must_match_project_version() -> None:
    module = _load_packaging_module()
    expected_tag = f"v{module.project_version()}"

    module.verify_tag(expected_tag)
    with pytest.raises(module.PackagingError, match=expected_tag):
        module.verify_tag(f"{expected_tag}-mismatch")


def test_bundle_validation_is_driven_by_all_project_scripts(tmp_path: Path) -> None:
    module = _load_packaging_module()
    bundle = _fake_bundle(module, tmp_path)

    assert len(module.validate_bundle(bundle, "linux")) == len(module.project_scripts())
    missing = bundle / module.project_scripts()[-1]
    missing.unlink()
    with pytest.raises(module.PackagingError, match=re.escape(str(missing))):
        module.validate_bundle(bundle, "linux")


def test_linux_archive_has_stable_root_and_matching_checksum(tmp_path: Path) -> None:
    module = _load_packaging_module()
    bundle = _fake_bundle(module, tmp_path)

    archive, checksum = module.create_linux_archive(bundle, tmp_path / "artifacts", "0.2.0")

    with tarfile.open(archive, "r:gz") as handle:
        names = handle.getnames()
        version_file = handle.extractfile("FedLeave/VERSION")
        version = version_file.read() if version_file is not None else None
    assert names[0] == "FedLeave"
    assert "FedLeave/fedleave" in names
    assert version == b"0.2.0\n"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert checksum.read_text(encoding="utf-8") == f"{digest}  {archive.name}\n"


def test_artifact_size_gate_reports_regressions(tmp_path: Path) -> None:
    module = _load_packaging_module()
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"x" * 2048)

    assert module.validate_file_size(artifact, 1) == 2048
    with pytest.raises(module.PackagingError, match="packaging limit"):
        module.validate_file_size(artifact, 0.001)


def test_distribution_workflow_publishes_only_master_to_rolling_channel() -> None:
    workflow = (ROOT / ".github" / "workflows" / "distribution.yml").read_text(encoding="utf-8")

    assert "github.ref == 'refs/heads/master'" in workflow
    assert "github.ref_type == 'tag'" not in workflow
    assert "\n    tags:\n" not in workflow
    assert 'check-size "$archive" --max-mib 300' in workflow
    for asset_name in (
        "FedLeave-Setup-Latest-Windows-x64.exe",
        "FedLeave-Setup-Latest-Windows-x64.exe.sha256",
        "FedLeave-Latest-Linux-x86_64.tar.gz",
        "FedLeave-Latest-Linux-x86_64.tar.gz.sha256",
        "install.sh",
    ):
        assert asset_name in workflow
    assert "Commit rolling installers to master" in workflow
    assert "git lfs install --local" in workflow
    assert "git add installers" in workflow
    assert "git push origin HEAD:master" in workflow
    assert "[skip ci]" in workflow


def test_large_committed_installer_mirrors_use_git_lfs() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    for artifact in (
        "installers/FedLeave-Setup-Latest-Windows-x64.exe",
        "installers/FedLeave-Latest-Linux-x86_64.tar.gz",
    ):
        assert f"{artifact} filter=lfs diff=lfs merge=lfs -text" in attributes


def test_runtime_dependencies_and_bundle_manifest_remain_lean() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    runtime_requirements = "\n".join(project["dependencies"]).lower()
    development_requirements = "\n".join(project["optional-dependencies"]["dev"]).lower()
    manifest = (ROOT / "scripts" / "lib" / "common" / "application_manifest.toml").read_text(encoding="utf-8")
    charting = (ROOT / "src" / "fedleave" / "charting.py").read_text(encoding="utf-8")

    for dependency in ("numpy", "pytest", "hypothesis", "pyinstaller"):
        assert dependency not in runtime_requirements
    assert "fedleave[gui,test,build]" in development_requirements
    assert "ruff" in development_requirements
    assert "mypy" in development_requirements
    assert 'collect_all = ["shiboken6"]' not in manifest
    assert '"numpy"' not in manifest
    assert "import numpy" not in charting


def test_pyproject_is_the_only_dependency_definition() -> None:
    for obsolete_file in (
        ROOT / "requirements.txt",
        ROOT / "requirements-gui.txt",
        ROOT / "requirements-dev.txt",
        ROOT / "scripts" / "lib" / "common" / "installer-requirements.txt",
    ):
        assert not obsolete_file.exists()

    installer_engine = (ROOT / "scripts" / "lib" / "common" / "installer_engine.py").read_text(encoding="utf-8")
    assert 'f"{self.repo_root}[gui,build]"' in installer_engine
    assert "requirements.txt" not in installer_engine


def test_linux_bootstrap_checks_tmp_capacity_before_extracting() -> None:
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")

    assert 'df -Pk "$TEMP_DIR"' in bootstrap
    assert "unpacked_bytes" in bootstrap
    assert "Temporary-space check passed" in bootstrap
    assert bootstrap.index("Temporary-space check passed") < bootstrap.index('tar -xzf "$TEMP_DIR/$ARCHIVE_NAME"')


@pytest.mark.skipif(os.name == "nt", reason="Linux bootstrap is exercised on POSIX hosts")
def test_bootstrap_installs_local_verified_release_without_python(tmp_path: Path) -> None:
    module = _load_packaging_module()
    bundle = _fake_bundle(module, tmp_path / "bundle")
    artifacts = tmp_path / "assets"
    _rolling_linux_assets(module, bundle, artifacts, "0.2.0")
    install_root = tmp_path / "install root"
    bin_dir = tmp_path / "command links"

    result = subprocess.run(
        [
            str(BOOTSTRAP),
            "--unattended",
            "--asset-base-url",
            artifacts.as_uri(),
            "--install-root",
            str(install_root),
            "--bin-dir",
            str(bin_dir),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert (install_root / "current").is_symlink()
    assert (bin_dir / "fedleave").is_symlink()
    assert (bin_dir / "FedLeaveCalendar").is_symlink()
    assert (install_root / "releases" / "0.2.0" / "fedleave").is_file()


@pytest.mark.skipif(os.name == "nt", reason="Linux bootstrap is exercised on POSIX hosts")
def test_bootstrap_migrates_legacy_fedleave_command_wrappers(tmp_path: Path) -> None:
    module = _load_packaging_module()
    bundle = _fake_bundle(module, tmp_path / "bundle")
    artifacts = tmp_path / "assets"
    _rolling_linux_assets(module, bundle, artifacts, "0.2.0")
    install_root = tmp_path / "install root"
    bin_dir = tmp_path / "command links"
    bin_dir.mkdir()
    legacy_wrapper = bin_dir / "fedleave"
    legacy_wrapper.write_text(
        f'#!/usr/bin/env bash\nexec {install_root}/current/fedleave/fedleave "$@"\n',
        encoding="utf-8",
    )
    legacy_wrapper.chmod(0o755)

    result = subprocess.run(
        [
            str(BOOTSTRAP),
            "--unattended",
            "--asset-base-url",
            artifacts.as_uri(),
            "--install-root",
            str(install_root),
            "--bin-dir",
            str(bin_dir),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Migrating legacy FedLeave command wrapper" in result.stdout
    assert legacy_wrapper.is_symlink()
    assert legacy_wrapper.readlink() == install_root / "current" / "fedleave"


@pytest.mark.skipif(os.name == "nt", reason="Linux bootstrap is exercised on POSIX hosts")
def test_bootstrap_preserves_unrelated_regular_commands(tmp_path: Path) -> None:
    module = _load_packaging_module()
    bundle = _fake_bundle(module, tmp_path / "bundle")
    artifacts = tmp_path / "assets"
    _rolling_linux_assets(module, bundle, artifacts, "0.2.0")
    install_root = tmp_path / "install root"
    bin_dir = tmp_path / "command links"
    bin_dir.mkdir()
    unrelated = bin_dir / "fedleave"
    original = "#!/usr/bin/env bash\necho unrelated\n"
    unrelated.write_text(original, encoding="utf-8")
    unrelated.chmod(0o755)

    result = subprocess.run(
        [
            str(BOOTSTRAP),
            "--unattended",
            "--asset-base-url",
            artifacts.as_uri(),
            "--install-root",
            str(install_root),
            "--bin-dir",
            str(bin_dir),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "not owned by FedLeave" in result.stderr
    assert unrelated.read_text(encoding="utf-8") == original


@pytest.mark.skipif(os.name == "nt", reason="Linux bootstrap is exercised on POSIX hosts")
def test_bootstrap_checksum_failure_does_not_create_install_root(tmp_path: Path) -> None:
    module = _load_packaging_module()
    bundle = _fake_bundle(module, tmp_path / "bundle")
    artifacts = tmp_path / "assets"
    _rolling_linux_assets(module, bundle, artifacts, "0.2.0")
    archive = artifacts / "FedLeave-Latest-Linux-x86_64.tar.gz"
    checksum = archive.with_name(archive.name + ".sha256")
    checksum.write_text(f"{'0' * 64}  {archive.name}\n", encoding="utf-8")
    install_root = tmp_path / "must-not-exist"

    result = subprocess.run(
        [
            str(BOOTSTRAP),
            "--unattended",
            "--asset-base-url",
            artifacts.as_uri(),
            "--install-root",
            str(install_root),
            "--bin-dir",
            str(tmp_path / "bin"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert not install_root.exists()
