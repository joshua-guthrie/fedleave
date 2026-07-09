from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class GuiSettings:
    fedleave_path: str = ""
    data_dir: str = ""
    first_day_of_week: str = "Sunday"
    show_auto_accruals: bool = False
    show_holidays: bool = True
    show_paydays: bool = True
    show_pay_period_end: bool = True
    font_size: int = 10
    print_orientation: str = "Landscape"
    pdf_export_folder: str = ""


def settings_path() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "fedleave-gui" / "settings.json"


def load_settings() -> GuiSettings:
    path = settings_path()
    if not path.exists():
        return GuiSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return GuiSettings()
    settings = GuiSettings()
    for key in asdict(settings):
        if key in data:
            setattr(settings, key, data[key])
    return settings


def save_settings(settings: GuiSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
