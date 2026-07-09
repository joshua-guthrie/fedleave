import json
from pathlib import Path

from fedleave_gui.backend import BackendOptions, FedleaveBackend


def _fake_fedleave(path: Path) -> Path:
    path.write_text(
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
else:
    print("ok")
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_gui_backend_uses_fedleave_binary_for_month_and_set_day(tmp_path: Path):
    fake = _fake_fedleave(tmp_path / "fedleave")
    backend = FedleaveBackend(BackendOptions(fedleave_path=str(fake), data_dir=str(tmp_path / "data")))

    month = backend.load_month(2026, 7)
    assert month["year"] == 2026
    assert month["month"] == 7

    result = backend.set_day("2026-07-08", {"annual": -5.0, "credit": 2.0})
    args = result["args"]
    assert args[:4] == ["set-day", "--date", "2026-07-08", "--authoritative"]
    assert "--json" in args
    assert "--annual" in args
    assert "-5" in args
    assert "--credit" in args
    assert "2" in args
    assert args[-2:] == ["--data-dir", str(tmp_path / "data")]
