import json
import sys
from pathlib import Path
import types

from fedleave_gui.backend import BackendOptions, FedleaveBackend


def _fake_fedleave(path: Path) -> Path:
    script = path.with_suffix(".py") if sys.platform.startswith("win") else path
    script.write_text(
        """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:1] == ["month"]:
    print(json.dumps({"year": int(args[args.index("--year") + 1]), "month": int(args[args.index("--month") + 1]), "days": []}))
elif args[:1] == ["set-day"]:
    print(json.dumps({"action": "set-day", "args": args}))
elif args[:1] == ["validate"]:
    print(json.dumps({"ok": True}))
elif args[:1] == ["use-or-lose"]:
    print(
        json.dumps(
            {
                "year": int(args[args.index("--year") + 1]),
                "as_of": "2027-01-09",
                "projected": True,
                "project_to": "2027-01-09",
                "balances": {"annual": 166.0},
                "use_or_lose": {
                    "carryover_limit": 240.0,
                    "annual_carryover": 166.0,
                    "use_or_lose": 0.0,
                },
            }
        )
    )
elif args[:1] == ["--version"]:
    print("fedleave 0.2.0")
else:
    print("ok")
""",
        encoding="utf-8",
    )
    if sys.platform.startswith("win"):
        wrapper = path.with_suffix(".cmd")
        wrapper.write_text(f'@python "{script}" %*\n', encoding="utf-8")
        return wrapper

    script.chmod(0o755)
    return script


def test_gui_backend_uses_fedleave_binary_for_month_and_set_day(tmp_path: Path):
    fake = _fake_fedleave(tmp_path / "fedleave")
    backend = FedleaveBackend(BackendOptions(fedleave_path=str(fake), data_dir=str(tmp_path / "data")))

    month = backend.load_month(2026, 7)
    assert month["year"] == 2026
    assert month["month"] == 7

    projection = backend.use_or_lose(2026)
    assert projection["year"] == 2026
    assert projection["use_or_lose"]["use_or_lose"] == 0.0

    result = backend.set_day("2026-07-08", {"annual": -5.0, "credit": 2.0})
    args = result["args"]
    assert args[:4] == ["set-day", "--date", "2026-07-08", "--authoritative"]
    assert "--json" in args
    assert "--annual" in args
    assert "-5" in args
    assert "--credit" in args
    assert "2" in args
    assert args[-2:] == ["--data-dir", str(tmp_path / "data")]


def test_gui_backend_reports_version_and_executable_path(tmp_path: Path):
    fake = _fake_fedleave(tmp_path / "fedleave")
    backend = FedleaveBackend(BackendOptions(fedleave_path=str(fake), data_dir=str(tmp_path / "data")))

    assert backend.version() == "fedleave 0.2.0"
    assert backend.executable_path() == fake


def test_gui_backend_hides_windows_console_when_launching_backend(monkeypatch, tmp_path: Path):
    fake = _fake_fedleave(tmp_path / "fedleave")
    backend_module = __import__("fedleave_gui.backend", fromlist=["FedleaveBackend"])
    backend = backend_module.FedleaveBackend(
        backend_module.BackendOptions(fedleave_path=str(fake), data_dir=str(tmp_path / "data"))
    )

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=0, stdout="fedleave 0.2.0", stderr="")

    monkeypatch.setattr(backend_module.sys, "platform", "win32")
    monkeypatch.setattr(backend_module.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(backend_module.subprocess, "run", fake_run)
    monkeypatch.setattr(backend_module, "find_fedleave", lambda explicit=None: fake)

    assert backend.version() == "fedleave 0.2.0"
    assert captured["command"] == [str(fake), "--version"]
    assert captured["kwargs"]["creationflags"] == 0x08000000
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["check"] is False
