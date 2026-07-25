#!/usr/bin/env python3
"""Create and validate FedLeave release artifacts.

The project version and executable list are read from pyproject.toml so the
Windows installer, Linux archive, and CI workflow cannot drift independently.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tomllib


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class PackagingError(RuntimeError):
    """An actionable packaging validation failure."""


def project_metadata() -> dict:
    with PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project")
    if not isinstance(project, dict):
        raise PackagingError("pyproject.toml does not contain a [project] table")
    return project


def project_version() -> str:
    version = project_metadata().get("version")
    if not isinstance(version, str) or not version:
        raise PackagingError("pyproject.toml does not declare project.version")
    if not SAFE_VERSION.fullmatch(version):
        raise PackagingError(f"Project version is unsafe for artifact filenames: {version!r}")
    return version


def project_scripts() -> list[str]:
    scripts = project_metadata().get("scripts")
    if not isinstance(scripts, dict) or not scripts:
        raise PackagingError("pyproject.toml does not declare any project.scripts")
    return list(scripts)


def abbreviated_sha(explicit_sha: str | None = None) -> str:
    sha = explicit_sha or os.environ.get("GITHUB_SHA")
    if not sha:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        sha = result.stdout.strip()
    sha = re.sub(r"[^0-9A-Fa-f]", "", sha)[:8].lower()
    if not sha:
        raise PackagingError("Could not derive an abbreviated Git commit hash")
    return sha


def development_version(sha: str | None = None) -> str:
    # PEP 440 development/local suffixes retain the human-readable project
    # version while making every branch artifact traceable to a commit.
    return f"{project_version()}.dev0+g{abbreviated_sha(sha)}"


def numeric_windows_version(version: str) -> str:
    """Convert a human version to NSIS's four unsigned 16-bit components."""
    release_match = re.match(r"^(?:[0-9]+!)?(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
    if not release_match:
        raise PackagingError(f"Version has no numeric release component: {version!r}")
    values = [int(value or 0) for value in release_match.groups()]
    values.append(0)
    if any(value > 65535 for value in values):
        raise PackagingError(f"Version component exceeds the Windows limit of 65535: {version!r}")
    return ".".join(str(value) for value in values)


def expected_executable(bundle_dir: Path, platform: str, command: str) -> Path:
    suffix = ".exe" if platform == "windows" else ""
    return bundle_dir / command / f"{command}{suffix}"


def validate_bundle(bundle_dir: Path, platform: str) -> list[Path]:
    if platform not in {"linux", "windows"}:
        raise PackagingError(f"Unsupported bundle platform: {platform}")
    if not bundle_dir.is_dir():
        raise PackagingError(f"Bundle directory does not exist: {bundle_dir}")

    missing: list[str] = []
    executables: list[Path] = []
    for command in project_scripts():
        executable = expected_executable(bundle_dir, platform, command)
        support_dir = executable.parent / "_internal"
        if not executable.is_file():
            missing.append(str(executable))
        elif platform == "linux" and not os.access(executable, os.X_OK):
            missing.append(f"{executable} (not executable)")
        else:
            executables.append(executable)
        if not support_dir.is_dir():
            missing.append(str(support_dir))

    if missing:
        detail = "\n".join(f"  - {path}" for path in missing)
        raise PackagingError(f"Application bundle is incomplete. Missing:\n{detail}")
    return executables


def write_checksum(path: Path) -> Path:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    checksum_path = path.with_name(path.name + ".sha256")
    checksum_path.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return checksum_path


def create_linux_archive(bundle_dir: Path, output_dir: Path, version: str) -> tuple[Path, Path]:
    validate_bundle(bundle_dir, "linux")
    if not SAFE_VERSION.fullmatch(version):
        raise PackagingError(f"Version is unsafe for artifact filenames: {version!r}")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"FedLeave-{version}-Linux-x86_64.tar.gz"
    pending_archive = archive.with_name(archive.name + ".tmp")
    pending_archive.unlink(missing_ok=True)
    # "FedLeave" is intentionally version independent. The bootstrap installer
    # supplies the versioned /opt destination after checksum verification.
    try:
        with tarfile.open(
            pending_archive, "w:gz", format=tarfile.PAX_FORMAT, dereference=False
        ) as tar:
            tar.add(bundle_dir, arcname="FedLeave", recursive=True)
            version_bytes = f"{version}\n".encode()
            version_info = tarfile.TarInfo("FedLeave/VERSION")
            version_info.size = len(version_bytes)
            version_info.mode = 0o644
            tar.addfile(version_info, io.BytesIO(version_bytes))
        pending_archive.replace(archive)
    except BaseException:
        pending_archive.unlink(missing_ok=True)
        raise
    return archive, write_checksum(archive)


def verify_tag(tag: str) -> None:
    expected = f"v{project_version()}"
    if tag != expected:
        raise PackagingError(
            f"Release tag {tag!r} does not match pyproject.toml version; expected {expected!r}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    version_parser = subparsers.add_parser("version", help="print the authoritative package version")
    version_parser.add_argument("--development", action="store_true")
    version_parser.add_argument("--sha")

    numeric_parser = subparsers.add_parser("numeric-version", help="print a four-part Windows version")
    numeric_parser.add_argument("--version", default=None)

    tag_parser = subparsers.add_parser("verify-tag", help="verify v<version> against pyproject.toml")
    tag_parser.add_argument("tag")

    validate_parser = subparsers.add_parser("validate-bundle", help="verify every packaged application")
    validate_parser.add_argument("--platform", choices=("linux", "windows"), required=True)
    validate_parser.add_argument("--bundle-dir", type=Path, required=True)

    archive_parser = subparsers.add_parser("linux-archive", help="create the Linux tarball and checksum")
    archive_parser.add_argument("--bundle-dir", type=Path, required=True)
    archive_parser.add_argument("--output-dir", type=Path, required=True)
    archive_parser.add_argument("--version", required=True)

    checksum_parser = subparsers.add_parser("checksum", help="write FILE.sha256")
    checksum_parser.add_argument("file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "version":
            print(development_version(args.sha) if args.development else project_version())
        elif args.command == "numeric-version":
            print(numeric_windows_version(args.version or project_version()))
        elif args.command == "verify-tag":
            verify_tag(args.tag)
            print(f"Tag {args.tag} matches project version {project_version()}.")
        elif args.command == "validate-bundle":
            executables = validate_bundle(args.bundle_dir.resolve(), args.platform)
            print(f"Validated {len(executables)} {args.platform} application executables.")
        elif args.command == "linux-archive":
            archive, checksum = create_linux_archive(
                args.bundle_dir.resolve(), args.output_dir.resolve(), args.version
            )
            print(archive)
            print(checksum)
        elif args.command == "checksum":
            if not args.file.is_file():
                raise PackagingError(f"File does not exist: {args.file}")
            print(write_checksum(args.file.resolve()))
    except (OSError, PackagingError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
