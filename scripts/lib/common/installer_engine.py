from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EXIT_INVALID_ARGS = 2
EXIT_PREREQ = 3
EXIT_PERMISSION = 5
EXIT_BUILD_FAILED = 20
EXIT_LOCKED = 91


@dataclass
class Options:
    platform: str
    unattended: bool
    build_only: bool
    install_only: str | None
    repair: bool
    rollback: bool
    activate_version: str | None
    uninstall: bool
    clean: bool
    keep_build: bool
    keep_versions: int
    desktop: bool
    allow_downgrade: bool
    python_installer: str | None
    offline: bool
    verbose: bool


@dataclass
class BuildTarget:
    name: str
    module: str
    func: str
    mode: str
    hidden_imports: list[str]
    add_data: list[str]
    collect_all: list[str]
    icon: str | None


class InstallerError(RuntimeError):
    def __init__(self, message: str, code: int = EXIT_BUILD_FAILED) -> None:
        super().__init__(message)
        self.code = code


class InstallerEngine:
    def __init__(self, repo_root: Path, options: Options) -> None:
        self.repo_root = repo_root
        self.options = options
        self.build_root = repo_root / ".build" / options.platform
        self._ensure_build_workspace_access()
        self.log_dir = self.build_root / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"installer-{int(time.time())}.log"
        self.result_path = self.log_dir / "last-result.json"
        self._log_handle = self.log_path.open("a", encoding="utf-8")

    def log(self, message: str) -> None:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        print(line)
        if not hasattr(self, "_log_handle"):
            return
        self._log_handle.write(line + "\n")
        self._log_handle.flush()

    def run(self) -> dict[str, Any]:
        with self._lock_or_fail():
            operation = self._resolve_operation()
            self.log(f"Operation: {operation}")
            self.log(f"Platform: {self.options.platform}")

            if self.options.clean:
                self._clean_build_area()

            if operation == "uninstall":
                self._uninstall()
            elif operation == "activate":
                self._activate(self.options.activate_version or "")
            elif operation == "rollback":
                self._rollback()
            elif operation == "repair":
                self._repair()
            elif operation == "install-only":
                source = Path(self.options.install_only or "").resolve()
                self._install_from_dist(source)
            else:
                self._build_all()
                if not self.options.build_only:
                    dist_dir = self._repo_dist_dir()
                    self._install_from_dist(dist_dir)

            result = {
                "status": "ok",
                "operation": operation,
                "platform": self.options.platform,
                "log": str(self.log_path),
                "result": str(self.result_path),
            }
            self.result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, sort_keys=True))
            return result

    def _resolve_operation(self) -> str:
        if self.options.uninstall:
            return "uninstall"
        if self.options.activate_version:
            return "activate"
        if self.options.rollback:
            return "rollback"
        if self.options.repair:
            return "repair"
        if self.options.install_only:
            return "install-only"
        if self.options.build_only:
            return "build-only"
        return "build-install"

    def _clean_build_area(self) -> None:
        self.log(f"Cleaning build area {self.build_root}")
        shutil.rmtree(self.build_root, ignore_errors=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_build_workspace_access(self) -> None:
        if self.options.platform != "linux":
            return

        if not self.build_root.exists():
            return

        if not self._build_workspace_needs_repair():
            return

        if self.options.unattended:
            raise InstallerError(
                f"Build workspace is not writable: {self.build_root}. Run LinuxInstall.sh with sudo once to repair ownership.",
                EXIT_PERMISSION,
            )

        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Repairing build workspace ownership for {self.build_root}")
        self._run_helper(
            self._linux_helper_path(),
            ["repair-build-workspace", str(self.build_root), str(os.getuid()), str(os.getgid())],
            "Build workspace repair",
            use_sudo=os.geteuid() != 0,
        )

    def _build_workspace_needs_repair(self) -> bool:
        current_uid = os.getuid()
        paths = [self.build_root]
        paths.extend(sorted(self.build_root.rglob("*")))
        for path in paths:
            # A virtualenv's Python launchers are symlinks to the system
            # interpreter.  Their target is intentionally not writable by
            # the project user, which does not make the build workspace bad.
            if path.is_symlink():
                continue
            try:
                stat_result = path.stat()
            except FileNotFoundError:
                continue
            if stat_result.st_uid != current_uid:
                return True
            if path.is_dir():
                if not os.access(path, os.W_OK | os.X_OK):
                    return True
            elif not os.access(path, os.W_OK):
                return True
        return False

    def _ensure_python(self) -> None:
        if sys.version_info < (3, 11):
            raise InstallerError("Python 3.11 or newer is required.", EXIT_PREREQ)

    def _build_all(self) -> None:
        self._ensure_python()
        venv_dir = self.build_root / "venv"
        work_dir = self.build_root / "pyinstaller-work"
        spec_dir = self.build_root / "pyinstaller-spec"
        entries_dir = self.build_root / "entries"
        platform_dist = self._build_dist_dir()

        for path in (venv_dir, work_dir, spec_dir, entries_dir, platform_dist):
            path.mkdir(parents=True, exist_ok=True)

        py_exe = self._create_or_reuse_venv(venv_dir)
        self._install_build_requirements(py_exe)
        targets = self._load_targets()

        for target in targets:
            self._build_target(py_exe, target, entries_dir, work_dir, spec_dir, platform_dist)

        self._validate_build(platform_dist, targets)

        repo_dist = self._repo_dist_dir()
        if repo_dist.exists():
            shutil.rmtree(repo_dist)
        repo_dist.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(platform_dist, repo_dist)
        self.log(f"Build complete at {repo_dist}")

        if not self.options.keep_build:
            for entry in entries_dir.glob("*.py"):
                entry.unlink(missing_ok=True)

    def _build_target(
        self,
        py_exe: Path,
        target: BuildTarget,
        entries_dir: Path,
        work_dir: Path,
        spec_dir: Path,
        platform_dist: Path,
    ) -> None:
        entry_filename = f"{target.name}.py" if target.name != "fedleave" else "fedleave_bootstrap.py"
        entry_path = entries_dir / entry_filename
        entry_path.write_text(
            f"from {target.module} import {target.func}\n\n"
            "if __name__ == '__main__':\n"
            f"    raise SystemExit({target.func}())\n",
            encoding="utf-8",
        )

        cmd = [
            str(py_exe),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onedir",
            "--name",
            target.name,
            "--windowed" if target.mode == "windowed" else "--console",
            "--distpath",
            str(platform_dist),
            "--workpath",
            str(work_dir),
            "--specpath",
            str(spec_dir),
        ]

        for hidden in target.hidden_imports:
            cmd.extend(["--hidden-import", hidden])

        sep = ";" if self.options.platform == "windows" else ":"
        for data_spec in target.add_data:
            src, dst = data_spec.split(":", 1)
            src_path = self.repo_root / src
            cmd.extend(["--add-data", f"{src_path}{sep}{dst}"])

        for package in target.collect_all:
            cmd.extend(["--collect-all", package])

        if target.icon:
            cmd.extend(["--icon", str(self.repo_root / target.icon)])

        cmd.append(str(entry_path))

        self.log(f"Building {target.name}")
        self._run(cmd)

    def _validate_build(self, dist_dir: Path, targets: list[BuildTarget]) -> None:
        missing: list[str] = []
        for target in targets:
            exe_name = f"{target.name}.exe" if self.options.platform == "windows" else target.name
            exe = dist_dir / target.name / exe_name
            if not exe.exists():
                missing.append(str(exe))
        if missing:
            raise InstallerError("Build validation failed. Missing:\n" + "\n".join(missing), EXIT_BUILD_FAILED)

    def _create_or_reuse_venv(self, venv_dir: Path) -> Path:
        py_exe = self._venv_python(venv_dir)
        if not py_exe.exists():
            self.log(f"Creating venv at {venv_dir}")
            self._run([sys.executable, "-m", "venv", str(venv_dir)])
        return self._venv_python(venv_dir)

    def _venv_python(self, venv_dir: Path) -> Path:
        if self.options.platform == "windows":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    def _install_build_requirements(self, py_exe: Path) -> None:
        self.log("Installing build dependencies")
        pip_options = ["--no-index"] if self.options.offline else []
        editable_options = ["--no-build-isolation"] if self.options.offline else []
        self._run([str(py_exe), "-m", "pip", "install", *pip_options, "--upgrade", "pip"])
        self._run([str(py_exe), "-m", "pip", "install", *pip_options, "-r", str(self.repo_root / "requirements.txt")])
        self._run([str(py_exe), "-m", "pip", "install", *pip_options, "-r", str(self.repo_root / "requirements-gui.txt")])
        self._run(
            [
                str(py_exe),
                "-m",
                "pip",
                "install",
                *pip_options,
                "-r",
                str(self.repo_root / "scripts" / "lib" / "common" / "installer-requirements.txt"),
            ]
        )
        self._run([str(py_exe), "-m", "pip", "install", *pip_options, *editable_options, "-e", str(self.repo_root)])

    def _load_targets(self) -> list[BuildTarget]:
        pyproject = tomllib.loads((self.repo_root / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = pyproject.get("project", {}).get("scripts", {})
        if not isinstance(scripts, dict):
            raise InstallerError("pyproject.toml project.scripts is missing or invalid", EXIT_BUILD_FAILED)

        manifest = tomllib.loads(
            (self.repo_root / "scripts" / "lib" / "common" / "application_manifest.toml").read_text(encoding="utf-8")
        )

        missing_meta = [name for name in scripts if name not in manifest]
        if missing_meta:
            raise InstallerError(
                "Missing packaging metadata for script(s): " + ", ".join(sorted(missing_meta)),
                EXIT_BUILD_FAILED,
            )

        targets: list[BuildTarget] = []
        for name, entry in scripts.items():
            if not isinstance(entry, str) or ":" not in entry:
                raise InstallerError(f"Invalid script entry for {name}: {entry}", EXIT_BUILD_FAILED)
            module, func = entry.split(":", 1)
            app_meta = manifest[name]
            targets.append(
                BuildTarget(
                    name=name,
                    module=module,
                    func=func,
                    mode=str(app_meta.get("mode", "console")),
                    hidden_imports=list(app_meta.get("hidden_imports", [])),
                    add_data=list(app_meta.get("add_data", [])),
                    collect_all=list(app_meta.get("collect_all", [])),
                    icon=app_meta.get("icon"),
                )
            )
        return targets

    def _repo_dist_dir(self) -> Path:
        folder = "fedleave-Windows" if self.options.platform == "windows" else "fedleave-Ubuntu"
        return self.repo_root / "dist" / folder

    def _build_dist_dir(self) -> Path:
        folder = "fedleave-Windows" if self.options.platform == "windows" else "fedleave-Ubuntu"
        return self.build_root / "dist" / folder

    def _install_from_dist(self, dist_dir: Path) -> None:
        if self.options.platform == "windows":
            self.log("Windows system-wide installation from batch is not available in this environment; build output remains in dist.")
            return

        if not dist_dir.exists():
            raise InstallerError(f"Install source does not exist: {dist_dir}")

        version = self._project_version()
        if os.geteuid() != 0:
            if self.options.unattended:
                raise InstallerError("System-wide install requires elevated privileges in unattended mode.", EXIT_PERMISSION)
            self.log("Requesting sudo to complete the system-wide installation.")
        helper_args = [
            "install-system",
            str(self.repo_root),
            str(dist_dir),
            version,
            str(self.options.keep_versions),
        ]
        self._run_helper(
            self._linux_helper_path(),
            helper_args,
            "System-wide install",
            use_sudo=os.geteuid() != 0,
        )

    def _run_helper(self, helper_path: Path, args: list[str], description: str, use_sudo: bool = False) -> None:
        cmd = [sys.executable, str(helper_path), *args]
        if use_sudo:
            cmd = ["sudo", *cmd]
        self.log("RUN: " + " ".join(cmd))
        process = subprocess.run(cmd, cwd=str(self.repo_root))
        if process.returncode != 0:
            raise InstallerError(f"{description} failed ({process.returncode}).", EXIT_BUILD_FAILED)

    def _linux_helper_path(self) -> Path:
        return self.repo_root / "scripts" / "lib" / "common" / "linux_installer_helper.py"

    def _project_version(self) -> str:
        pyproject = tomllib.loads((self.repo_root / "pyproject.toml").read_text(encoding="utf-8"))
        return str(pyproject.get("project", {}).get("version", "unknown"))

    def _repair(self) -> None:
        dist = self._repo_dist_dir()
        if not dist.exists():
            self._build_all()
            dist = self._repo_dist_dir()
        self._install_from_dist(dist)

    def _rollback(self) -> None:
        if self.options.platform != "linux":
            raise InstallerError("Rollback is only implemented on Linux in this release.")
        if os.geteuid() != 0:
            raise InstallerError("Rollback requires root privileges.", EXIT_PERMISSION)

        versions = Path("/opt/fedleave/versions")
        items = sorted([p for p in versions.iterdir() if p.is_dir()], key=lambda p: p.name)
        if len(items) < 2:
            raise InstallerError("No previous version is available for rollback.")

        target = items[-2]
        current = Path("/opt/fedleave/current")
        if current.exists() or current.is_symlink():
            current.unlink()
        current.symlink_to(target, target_is_directory=True)
        self.log(f"Rolled back to {target.name}")

    def _activate(self, version: str) -> None:
        if self.options.platform != "linux":
            raise InstallerError("Version activation is only implemented on Linux in this release.")
        if os.geteuid() != 0:
            raise InstallerError("Activation requires root privileges.", EXIT_PERMISSION)

        target = Path("/opt/fedleave/versions") / version
        if not target.exists():
            raise InstallerError(f"Version not found: {version}")
        current = Path("/opt/fedleave/current")
        if current.exists() or current.is_symlink():
            current.unlink()
        current.symlink_to(target, target_is_directory=True)
        self.log(f"Activated version {version}")

    def _uninstall(self) -> None:
        if self.options.platform == "windows":
            self.log("Windows uninstall is not implemented in this environment.")
            return
        if os.geteuid() != 0:
            raise InstallerError("Uninstall requires root privileges.", EXIT_PERMISSION)

        shutil.rmtree(Path("/opt/fedleave"), ignore_errors=True)

        scripts = tomllib.loads((self.repo_root / "pyproject.toml").read_text(encoding="utf-8")).get("project", {}).get("scripts", {})
        for app_name in scripts:
            (Path("/usr/local/bin") / app_name).unlink(missing_ok=True)

        (Path("/usr/local/share/applications") / "fedleave-calendar.desktop").unlink(missing_ok=True)
        self.log("Uninstall complete")

    def _run(self, cmd: list[str]) -> None:
        self.log("RUN: " + " ".join(cmd))
        process = subprocess.run(cmd, cwd=str(self.repo_root), capture_output=True, text=True)
        if process.stdout:
            self._log_handle.write(process.stdout)
        if process.stderr:
            self._log_handle.write(process.stderr)
        self._log_handle.flush()
        if process.returncode != 0:
            raise InstallerError(
                f"Command failed ({process.returncode}): {' '.join(cmd)}\n"
                f"{process.stderr or process.stdout}",
                EXIT_BUILD_FAILED,
            )

    def _lock_or_fail(self):
        lock_path = self.build_root / "installer.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
        try:
            if sys.platform == "win32":
                import msvcrt

                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise InstallerError("Another installer instance is already running.", EXIT_LOCKED) from exc
            else:
                import fcntl

                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise InstallerError("Another installer instance is already running.", EXIT_LOCKED) from exc

            class _Lock:
                def __init__(self, outer: "InstallerEngine", file_desc: int):
                    self.outer = outer
                    self.file_desc = file_desc

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    try:
                        os.close(self.file_desc)
                    finally:
                        return False

            return _Lock(self, fd)
        except Exception:
            os.close(fd)
            raise


def parse_args(argv: list[str]) -> Options:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--platform", choices=["linux", "windows"], required=True)
    parser.add_argument("--unattended", action="store_true")
    parser.add_argument("--console", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--install-only")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--activate-version")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--keep-build", action="store_true")
    parser.add_argument("--keep-versions", type=int, default=1)
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--allow-downgrade", action="store_true")
    parser.add_argument("--python-installer")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    ns = parser.parse_args(argv)

    invalid_pairs = [
        (ns.build_only and ns.uninstall, "--build-only --uninstall"),
        (ns.repair and ns.uninstall, "--repair --uninstall"),
        (ns.rollback and ns.build_only, "--rollback --build-only"),
        (bool(ns.install_only) and ns.build_only, "--install-only PATH --build-only"),
        (bool(ns.activate_version) and ns.clean, "--activate-version VERSION --clean"),
    ]
    for invalid, combo in invalid_pairs:
        if invalid:
            raise InstallerError(f"Invalid option combination: {combo}", EXIT_INVALID_ARGS)

    return Options(
        platform=ns.platform,
        unattended=ns.unattended,
        build_only=ns.build_only,
        install_only=ns.install_only,
        repair=ns.repair,
        rollback=ns.rollback,
        activate_version=ns.activate_version,
        uninstall=ns.uninstall,
        clean=ns.clean,
        keep_build=ns.keep_build,
        keep_versions=max(1, int(ns.keep_versions)),
        desktop=ns.desktop,
        allow_downgrade=ns.allow_downgrade,
        python_installer=ns.python_installer,
        offline=ns.offline,
        verbose=ns.verbose,
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    repo_root = Path(__file__).resolve().parents[3]

    try:
        options = parse_args(argv)
        engine = InstallerEngine(repo_root=repo_root, options=options)
        engine.run()
        return 0
    except InstallerError as exc:
        payload = {
            "status": "error",
            "code": exc.code,
            "message": str(exc),
        }
        print(str(exc), file=sys.stderr)
        print(json.dumps(payload, sort_keys=True))
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
