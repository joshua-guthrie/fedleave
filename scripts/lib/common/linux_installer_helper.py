from __future__ import annotations

import argparse
import os
import shlex
import shutil
import tomllib
from pathlib import Path


def repair_build_workspace(build_root: Path, uid: int, gid: int) -> None:
    if not build_root.exists():
        return

    for path in sorted(build_root.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
        try:
            os.chown(path, uid, gid)
        except FileNotFoundError:
            continue
    os.chown(build_root, uid, gid)


def write_linux_wrappers(repo_root: Path, current_link: Path) -> None:
    scripts = (
        tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8")).get("project", {}).get("scripts", {})
    )
    bin_dir = Path("/usr/local/bin")
    bin_dir.mkdir(parents=True, exist_ok=True)

    for app_name in scripts:
        wrapper = bin_dir / app_name
        wrapper_text = (
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "exec " + shlex.quote(str(current_link / app_name / app_name)) + ' "$@"',
                ]
            )
            + "\n"
        )
        wrapper.write_text(wrapper_text, encoding="utf-8")
        wrapper.chmod(0o755)

    desktop_dir = Path("/usr/local/share/applications")
    desktop_dir.mkdir(parents=True, exist_ok=True)
    desktop_file = desktop_dir / "fedleave-calendar.desktop"
    desktop_file.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=FedLeave Calendar",
                "Exec=/usr/local/bin/FedLeaveCalendar",
                "Terminal=false",
                "Categories=Office;Utility;",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def cleanup_old_versions(versions_dir: Path, keep_count: int) -> None:
    items = sorted([p for p in versions_dir.iterdir() if p.is_dir()], key=lambda path: path.name)
    if len(items) <= keep_count:
        return
    for stale in items[:-keep_count]:
        shutil.rmtree(stale, ignore_errors=True)


def install_system(repo_root: Path, dist_dir: Path, version: str, keep_versions: int) -> None:
    install_root = Path("/opt/fedleave")
    versions = install_root / "versions"
    versions.mkdir(parents=True, exist_ok=True)

    target = versions / version
    staging = versions / f"{version}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    if target.exists():
        shutil.rmtree(target)

    shutil.copytree(dist_dir, staging)
    staging.rename(target)

    current_link = install_root / "current"
    if current_link.exists() or current_link.is_symlink():
        current_link.unlink()
    current_link.symlink_to(target, target_is_directory=True)

    write_linux_wrappers(repo_root, current_link)
    cleanup_old_versions(versions, max(1, keep_versions))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    repair = subparsers.add_parser("repair-build-workspace")
    repair.add_argument("build_root")
    repair.add_argument("uid", type=int)
    repair.add_argument("gid", type=int)

    install = subparsers.add_parser("install-system")
    install.add_argument("repo_root")
    install.add_argument("dist_dir")
    install.add_argument("version")
    install.add_argument("keep_versions", type=int)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "repair-build-workspace":
        repair_build_workspace(Path(args.build_root), args.uid, args.gid)
        return 0
    if args.command == "install-system":
        install_system(Path(args.repo_root), Path(args.dist_dir), args.version, args.keep_versions)
        return 0
    raise SystemExit(2)


if __name__ == "__main__":
    raise SystemExit(main())
