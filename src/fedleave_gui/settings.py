"""Persist calendar GUI preferences independently from leave ledger data."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class GuiSettings:
    """User preferences and reminder state stored by the calendar GUI."""

    fedleave_path: str = ""
    data_dir: str = ""
    first_day_of_week: str = "Sunday"
    payday_offset_days: int = 6
    show_auto_accruals: bool = False
    show_holidays: bool = True
    show_paydays: bool = True
    show_pay_period_end: bool = True
    font_size: int = 10
    print_orientation: str = "Landscape"
    pdf_export_folder: str = ""
    last_update_check_utc: str = ""
    last_update_notified_version: str = ""
    expiration_reminder_pay_periods: list[int] = field(default_factory=lambda: [1, 3, 6, 12])
    last_expiration_reminder_date: str = ""


def settings_path() -> Path:
    """Return the platform-appropriate per-user GUI settings path."""
    if sys.platform.startswith("win"):
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "fedleave-gui" / "settings.json"


def load_settings() -> GuiSettings:
    """Load recognized settings, falling back safely when the file is invalid."""
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
    """Write all current GUI settings to the per-user configuration file."""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
