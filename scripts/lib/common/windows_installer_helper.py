from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _create_shortcut(shortcut_path: Path, target_path: Path, working_directory: Path) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    script_text = "\n".join([
        'Set shell = CreateObject("WScript.Shell")',
        'Set shortcut = shell.CreateShortcut(WScript.Arguments(0))',
        'shortcut.TargetPath = WScript.Arguments(1)',
        'shortcut.WorkingDirectory = WScript.Arguments(2)',
        'shortcut.IconLocation = WScript.Arguments(1) & ",0"',
        'shortcut.Description = "FedLeave Calendar"',
        "shortcut.Save",
        "",
    ])
    with tempfile.TemporaryDirectory(prefix="fedleave-shortcut-") as temp_dir:
        script_path = Path(temp_dir) / "create-shortcut.vbs"
        script_path.write_text(script_text, encoding="utf-8")
        result = subprocess.run(
            [
                "cscript.exe",
                "//NoLogo",
                str(script_path),
                str(shortcut_path),
                str(target_path),
                str(working_directory),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown shortcut error").strip()
        raise RuntimeError(f"Could not create shortcut {shortcut_path}: {detail}")


def install_system(
    dist_dir: Path,
    install_dir: Path | None = None,
    desktop_dir: Path | None = None,
    start_menu_dir: Path | None = None,
) -> None:
    source = dist_dir.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Install source does not exist: {source}")

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    public_profile = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    target = install_dir or program_files / "fedleave"
    desktop = desktop_dir or public_profile / "Desktop"
    start_menu = start_menu_dir or program_data / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "FedLeave"
    staging = target.with_name(f"{target.name}.staging")
    backup = target.with_name(f"{target.name}.previous")

    if staging.exists():
        shutil.rmtree(staging)
    if backup.exists():
        shutil.rmtree(backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, staging)

    had_previous = target.exists()
    if had_previous:
        target.rename(backup)
    try:
        staging.rename(target)
    except Exception:
        if had_previous and backup.exists() and not target.exists():
            backup.rename(target)
        raise

    calendar = target / "FedLeaveCalendar" / "FedLeaveCalendar.exe"
    if not calendar.is_file():
        if target.exists():
            shutil.rmtree(target)
        if had_previous and backup.exists():
            backup.rename(target)
        raise FileNotFoundError(f"Packaged calendar executable was not found: {calendar}")

    try:
        _create_shortcut(desktop / "FedLeave Calendar.lnk", calendar, calendar.parent)
        _create_shortcut(start_menu / "FedLeave Calendar.lnk", calendar, calendar.parent)
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        if had_previous and backup.exists():
            backup.rename(target)
        raise

    if backup.exists():
        shutil.rmtree(backup)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install-system")
    install.add_argument("dist_dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "install-system":
        install_system(Path(args.dist_dir))
        return 0
    raise SystemExit(2)


if __name__ == "__main__":
    raise SystemExit(main())
