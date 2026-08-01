"""Build, validate, install, repair, and remove FedLeave application suites.

Platform entry scripts normalize their environment and delegate here so Linux
and Windows share target discovery, PyInstaller configuration, and lifecycle
rules while retaining small privileged platform helpers.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
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
    """Normalized command-line choices controlling one installer operation."""

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
    smoke_test: bool = False


@dataclass
class BuildTarget:
    """One application entry point and its PyInstaller-specific requirements."""

    name: str
    module: str
    func: str
    mode: str
    hidden_imports: list[str]
    add_data: list[str]
    collect_all: list[str]
    icon: str | None


class InstallerError(RuntimeError):
    """An actionable installer failure paired with a stable process exit code."""

    def __init__(self, message: str, code: int = EXIT_BUILD_FAILED) -> None:
        super().__init__(message)
        self.code = code


class InstallerEngine:
    """Coordinate one locked build, installation, maintenance, or removal run."""

    def __init__(self, repo_root: Path, options: Options) -> None:
        self.repo_root = repo_root
        self.options = options
        configured_build_root = os.environ.get("FEDLEAVE_BUILD_ROOT")
        self.build_root = (
            Path(configured_build_root).resolve() / options.platform
            if configured_build_root
            else repo_root / ".build" / options.platform
        )
        self._ensure_build_workspace_access()
        self.log_dir = self.build_root / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"installer-{int(time.time())}.log"
        self.result_path = self.log_dir / "last-result.json"
        self._log_handle = self.log_path.open("a", encoding="utf-8")

    def log(self, message: str) -> None:
        """Write a timestamped message to both the console and operation log."""
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        print(line)
        if not hasattr(self, "_log_handle"):
            return
        self._log_handle.write(line + "\n")
        self._log_handle.flush()

    def run(self) -> dict[str, Any]:
        """Resolve and execute exactly one operation under the installer lock."""
        with self._lock_or_fail():
            operation = self._resolve_operation()
            self.log(f"Operation: {operation}")
            self.log(f"Platform: {self.options.platform}")

            if self.options.clean:
                self._clean_build_area()

            if operation == "smoke-test":
                self._smoke_test_build_configuration()
            elif operation == "uninstall":
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
        if self.options.smoke_test:
            return "smoke-test"
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
        build_version, source_commit = self._build_identity()
        self.log(f"Build identity: {build_version} ({source_commit[:12] or 'source-only'})")

        entry_paths: dict[str, Path] = {}
        for target in targets:
            entry_paths[target.name] = self._write_entry(
                target,
                entries_dir,
                build_version=build_version,
                source_commit=source_commit,
            )
        config_path = self._write_suite_config(
            targets, entry_paths, spec_dir / "fedleave-suite.json", platform_dist.name
        )
        self.log(f"Building shared suite with {len(targets)} entry points")
        self._run(self._build_suite_command(py_exe, config_path, work_dir, platform_dist))

        self._deduplicate_linux_bundle(platform_dist)
        self._validate_build(platform_dist, targets)

        repo_dist = self._repo_dist_dir()
        self._publish_build(platform_dist, repo_dist)
        self.log(f"Build complete at {repo_dist}")

        if not self.options.keep_build:
            for entry in entries_dir.glob("*.py"):
                entry.unlink(missing_ok=True)

    def _write_suite_config(
        self,
        targets: list[BuildTarget],
        entry_paths: dict[str, Path],
        config_path: Path,
        suite_name: str,
    ) -> Path:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config = {
            "repo_root": str(self.repo_root),
            "source_root": str(self.repo_root / "src"),
            "suite_name": suite_name,
            # These are development/test-only or an intentionally removed
            # heavyweight optional dependency. Excluding them also keeps a
            # reused build venv from silently reintroducing package bloat.
            "excludes": ["_pytest", "hypothesis", "numpy", "pytest"],
            "targets": [],
        }
        for target in targets:
            datas = []
            for data_spec in target.add_data:
                source, destination = data_spec.split(":", 1)
                datas.append([str(self.repo_root / source), destination])
            config["targets"].append(
                {
                    "name": target.name,
                    "entry": str(entry_paths[target.name]),
                    "console": target.mode != "windowed",
                    "hidden_imports": target.hidden_imports,
                    "datas": datas,
                    "collect_all": target.collect_all,
                    "icon": str(self.repo_root / target.icon) if target.icon else None,
                }
            )
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        return config_path

    def _write_entry(
        self,
        target: BuildTarget,
        entries_dir: Path,
        *,
        build_version: str,
        source_commit: str,
    ) -> Path:
        entries_dir.mkdir(parents=True, exist_ok=True)
        entry_filename = f"{target.name}.py" if target.name != "fedleave" else "fedleave_bootstrap.py"
        entry_path = entries_dir / entry_filename
        entry_path.write_text(
            "import os\n\n"
            f"os.environ['FEDLEAVE_BUILD_VERSION'] = {build_version!r}\n"
            f"os.environ['FEDLEAVE_SOURCE_COMMIT'] = {source_commit!r}\n\n"
            f"from {target.module} import {target.func}\n\n"
            "if __name__ == '__main__':\n"
            f"    raise SystemExit({target.func}())\n",
            encoding="utf-8",
        )
        return entry_path

    def _build_suite_command(
        self,
        py_exe: Path,
        config_path: Path,
        work_dir: Path,
        platform_dist: Path,
    ) -> list[str]:
        return [
            str(py_exe),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            str(platform_dist.parent),
            "--workpath",
            str(work_dir),
            str(self.repo_root / "scripts" / "lib" / "common" / "fedleave_suite.spec"),
            "--",
            "--config",
            str(config_path),
        ]

    def _smoke_test_build_configuration(self) -> None:
        """Exercise build discovery and command construction without running PyInstaller."""
        self._ensure_python()
        targets = self._load_targets()
        build_version, source_commit = self._build_identity()
        source_path = str(self.repo_root / "src")
        if source_path not in sys.path:
            sys.path.insert(0, source_path)
        smoke_root = self.build_root / "smoke-test"
        entries_dir = smoke_root / "entries"
        work_dir = smoke_root / "work"
        spec_dir = smoke_root / "spec"
        platform_dist = smoke_root / "dist"
        for path in (entries_dir, work_dir, spec_dir, platform_dist):
            path.mkdir(parents=True, exist_ok=True)

        entry_paths: dict[str, Path] = {}
        for target in targets:
            try:
                module_spec = importlib.util.find_spec(target.module)
            except ModuleNotFoundError:
                module_spec = None
            if module_spec is None:
                raise InstallerError(f"Build target module could not be imported: {target.module}")
            for data_spec in target.add_data:
                source, _destination = data_spec.split(":", 1)
                if not (self.repo_root / source).exists():
                    raise InstallerError(f"Build data source does not exist: {source}")
            if target.icon and not (self.repo_root / target.icon).exists():
                raise InstallerError(f"Build icon does not exist: {target.icon}")
            entry_paths[target.name] = self._write_entry(
                target,
                entries_dir,
                build_version=build_version,
                source_commit=source_commit,
            )

        config_path = self._write_suite_config(
            targets, entry_paths, spec_dir / "fedleave-suite.json", platform_dist.name
        )
        command = self._build_suite_command(Path(sys.executable), config_path, work_dir, platform_dist)
        if "PyInstaller" not in command or str(config_path) != command[-1]:
            raise InstallerError("Invalid shared PyInstaller suite command")

        self.log(f"Build-script smoke test passed for {len(targets)} application targets.")
        if not self.options.keep_build:
            shutil.rmtree(smoke_root, ignore_errors=True)

    def _build_identity(self) -> tuple[str, str]:
        source_commit = (os.environ.get("FEDLEAVE_SOURCE_COMMIT") or os.environ.get("GITHUB_SHA") or "").strip().lower()
        if not source_commit:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_root,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                source_commit = result.stdout.strip().lower()
        if source_commit and not re.fullmatch(r"[0-9a-f]{7,64}", source_commit):
            raise InstallerError(f"Invalid build source commit: {source_commit!r}")

        build_version = (os.environ.get("FEDLEAVE_BUILD_VERSION") or os.environ.get("PACKAGE_VERSION") or "").strip()
        if not build_version:
            build_version = self._project_version()
            if source_commit:
                build_version = f"{build_version}.dev0+g{source_commit[:8]}"
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", build_version):
            raise InstallerError(f"Invalid build version: {build_version!r}")
        return build_version, source_commit

    def _publish_build(self, platform_dist: Path, repo_dist: Path) -> None:
        """Publish a complete build without deleting files from the active Windows tree."""
        repo_dist.parent.mkdir(parents=True, exist_ok=True)
        for abandoned in sorted(repo_dist.parent.glob(f".{repo_dist.name}.previous-*")):
            try:
                self._remove_tree_with_retries(abandoned)
            except OSError as exc:
                self.log(f"WARNING: Earlier build still remains at {abandoned}: {exc}")
        token = f"{os.getpid()}-{time.time_ns()}"
        staging = repo_dist.parent / f".{repo_dist.name}.staging-{token}"
        previous = repo_dist.parent / f".{repo_dist.name}.previous-{token}"
        # Linux bundle deduplication uses relative links within _internal.
        # Preserve them while staging instead of expanding the linked files.
        shutil.copytree(platform_dist, staging, symlinks=True)
        moved_previous = False
        try:
            if repo_dist.exists():
                self._replace_path_with_retries(repo_dist, previous, "move the previous build aside")
                moved_previous = True
            self._replace_path_with_retries(staging, repo_dist, "activate the completed build")
        except Exception:
            if moved_previous and previous.exists() and not repo_dist.exists():
                self._replace_path_with_retries(previous, repo_dist, "restore the previous build")
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise

        if previous.exists():
            try:
                self._remove_tree_with_retries(previous)
            except OSError as exc:
                # Windows can keep mapped .pyd files locked after a program exits.
                # The new build is already active, so leave the uniquely named old
                # tree for a later clean instead of failing a successful build.
                self.log(f"WARNING: Previous build remains at {previous}: {exc}")

    @staticmethod
    def _replace_path_with_retries(source: Path, destination: Path, description: str) -> None:
        last_error: OSError | None = None
        for attempt in range(6):
            try:
                source.replace(destination)
                return
            except OSError as exc:
                last_error = exc
                if attempt < 5:
                    time.sleep(0.2 * (attempt + 1))
        raise InstallerError(f"Could not {description}: {last_error}") from last_error

    @staticmethod
    def _remove_tree_with_retries(path: Path) -> None:
        last_error: OSError | None = None
        for attempt in range(6):
            try:
                shutil.rmtree(path)
                return
            except OSError as exc:
                last_error = exc
                if attempt < 5:
                    time.sleep(0.2 * (attempt + 1))
        if last_error is not None:
            raise last_error

    def _validate_build(self, dist_dir: Path, targets: list[BuildTarget]) -> None:
        missing: list[str] = []
        for target in targets:
            exe_name = f"{target.name}.exe" if self.options.platform == "windows" else target.name
            exe = dist_dir / exe_name
            if not exe.exists():
                missing.append(str(exe))
        if not (dist_dir / "_internal").is_dir():
            missing.append(str(dist_dir / "_internal"))
        if missing:
            raise InstallerError("Build validation failed. Missing:\n" + "\n".join(missing), EXIT_BUILD_FAILED)

    def _deduplicate_linux_bundle(self, dist_dir: Path) -> None:
        """Replace large byte-identical support files with relative symlinks."""
        if self.options.platform != "linux":
            return
        support_dir = dist_dir / "_internal"
        if not support_dir.is_dir():
            return

        groups: dict[tuple[int, int, str], list[Path]] = {}
        for path in sorted(support_dir.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            metadata = path.stat()
            if metadata.st_size < 1024 * 1024:
                continue
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            key = (metadata.st_size, stat.S_IMODE(metadata.st_mode), digest.hexdigest())
            groups.setdefault(key, []).append(path)

        linked_files = 0
        saved_bytes = 0
        for (size, _mode, _digest), paths in groups.items():
            if len(paths) < 2:
                continue
            canonical = min(paths, key=lambda path: (len(path.parts), str(path)))
            for duplicate in paths:
                if duplicate == canonical:
                    continue
                relative_target = os.path.relpath(canonical, duplicate.parent)
                duplicate.unlink()
                duplicate.symlink_to(relative_target)
                linked_files += 1
                saved_bytes += size

        if linked_files:
            self.log(f"Deduplicated {linked_files} Linux runtime files ({saved_bytes / 1024 / 1024:.1f} MiB saved)")

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
        self._run(
            [
                str(py_exe),
                "-m",
                "pip",
                "install",
                *pip_options,
                *editable_options,
                "-e",
                f"{self.repo_root}[gui,build]",
            ]
        )

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
        configured_dist_root = os.environ.get("FEDLEAVE_DIST_ROOT")
        dist_root = Path(configured_dist_root).resolve() if configured_dist_root else self.repo_root / "dist"
        return dist_root / folder

    def _build_dist_dir(self) -> Path:
        folder = "fedleave-Windows" if self.options.platform == "windows" else "fedleave-Ubuntu"
        return self.build_root / "dist" / folder

    def _install_from_dist(self, dist_dir: Path) -> None:
        if self.options.platform == "windows":
            if not dist_dir.exists():
                raise InstallerError(f"Install source does not exist: {dist_dir}")
            if not self.options.unattended and not self._confirm_windows_install():
                self.log("Windows installation declined; build output remains in dist.")
                return

            helper_path = self._windows_helper_path()
            helper_args = ["install-system", str(dist_dir)]
            if self._windows_is_admin():
                self._run_helper(helper_path, helper_args, "Windows system-wide install")
            else:
                self.log("Requesting administrator privileges for the Windows installation.")
                self._run_windows_helper_elevated(helper_path, helper_args)
            return

        if not dist_dir.exists():
            raise InstallerError(f"Install source does not exist: {dist_dir}")

        version = self._project_version()
        if os.geteuid() != 0:
            if self.options.unattended:
                raise InstallerError(
                    "System-wide install requires elevated privileges in unattended mode.", EXIT_PERMISSION
                )
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

    def _windows_helper_path(self) -> Path:
        return self.repo_root / "scripts" / "lib" / "common" / "windows_installer_helper.py"

    def _confirm_windows_install(self) -> bool:
        try:
            response = input(
                "Build complete. Install FedLeave in C:\\Program Files\\fedleave "
                "and create Desktop and Start Menu shortcuts? [y/N]: "
            )
        except EOFError:
            return False
        return response.strip().lower() in {"y", "yes"}

    @staticmethod
    def _windows_is_admin() -> bool:
        if sys.platform != "win32":
            return False
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    def _run_windows_helper_elevated(self, helper_path: Path, args: list[str]) -> None:
        if sys.platform != "win32":
            raise InstallerError("Windows elevation is only available on Windows.", EXIT_PERMISSION)

        import ctypes
        from ctypes import wintypes

        class ShellExecuteInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("fMask", wintypes.ULONG),
                ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", wintypes.LPVOID),
                ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIconOrMonitor", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        execute_info = ShellExecuteInfo()
        execute_info.cbSize = ctypes.sizeof(execute_info)
        execute_info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
        execute_info.lpVerb = "runas"
        execute_info.lpFile = sys.executable
        execute_info.lpParameters = subprocess.list2cmdline([str(helper_path), *args])
        execute_info.lpDirectory = str(self.repo_root)
        execute_info.nShow = 1

        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(execute_info)):
            raise InstallerError("Administrator approval was cancelled or elevation failed.", EXIT_PERMISSION)
        try:
            ctypes.windll.kernel32.WaitForSingleObject(execute_info.hProcess, 0xFFFFFFFF)
            exit_code = wintypes.DWORD()
            ctypes.windll.kernel32.GetExitCodeProcess(execute_info.hProcess, ctypes.byref(exit_code))
        finally:
            ctypes.windll.kernel32.CloseHandle(execute_info.hProcess)
        if exit_code.value != 0:
            raise InstallerError(f"Windows system-wide install failed ({exit_code.value}).", EXIT_BUILD_FAILED)

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

        scripts = (
            tomllib.loads((self.repo_root / "pyproject.toml").read_text(encoding="utf-8"))
            .get("project", {})
            .get("scripts", {})
        )
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
                f"Command failed ({process.returncode}): {' '.join(cmd)}\n{process.stderr or process.stdout}",
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
    """Parse installer options and reject incompatible operation combinations."""
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
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Validate build targets and PyInstaller command construction without building binaries.",
    )
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
        smoke_test=ns.smoke_test,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the installer engine and serialize known failures for automation."""
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
