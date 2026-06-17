from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Any

import typer
from pydantic import BaseModel, Field
from dateutil.parser import isoparse
from .validation import sanitize_url
from rich.console import Console

from .storage import ensure_data_dir, atomic_write_json
from .payperiods import generate_pay_periods
from .holidays import DEFAULT_OPM_ICS_URL, generate_federal_holidays

console = Console()


class UserConfig(BaseModel):
    display_name: str = "User"
    timezone: str = "America/New_York"


class DefaultsConfig(BaseModel):
    annual_leave_accrual_hours: float = 6.0
    sick_leave_accrual_hours: float = 4.0
    time_increment_hours: float = 0.25
    workday_start: str = "07:00"
    workday_end: str = "15:30"
    lunch_start: str = "11:30"
    lunch_end: str = "12:00"
    normal_workdays: list[str] = Field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])


class HolidaysConfig(BaseModel):
    enabled: bool = True
    country: str = "US"
    source_preference: str = "opm_ics_then_python_holidays"
    ics_url: str = DEFAULT_OPM_ICS_URL
    cache_enabled: bool = True
    cache_dir: str = "holiday_cache"
    allow_manual_override: bool = True
    include_observed_dates: bool = True
    mark_actual_and_observed: bool = False
    fail_if_holidays_unavailable: bool = False


class AnnualRules(BaseModel):
    carryover_limit_hours: float = 240.0
    track_use_or_lose: bool = True
    allow_restored_leave: bool = True


class SickRules(BaseModel):
    carryover_limit_hours: float | None = None
    expires: bool = False


class CompRules(BaseModel):
    expires: bool = True
    expiration_pay_periods_after_earned: int = 26
    expiration_action: str = "warn"
    allow_payout_tracking: bool = True
    allow_forfeiture_tracking: bool = True


class TravelCompRules(BaseModel):
    expires: bool = True
    expiration_pay_periods_after_earned: int = 26
    expiration_action: str = "forfeit"
    allow_extension: bool = True
    extension_pay_periods: int = 26


class CreditRules(BaseModel):
    enabled: bool = True
    max_carryover_hours: float = 24.0
    max_earn_per_day_hours: float | None = None
    max_earn_per_pay_period_hours: float | None = None
    max_balance_hours: float = 24.0
    usable_when: str = "next_day"
    same_day_use_allowed: bool = False
    same_pay_period_use_allowed: bool = True
    expires: bool = False
    forfeit_excess_at_pay_period_rollover: bool = True
    requires_flexible_work_schedule: bool = True


class TimeOffAwardRules(BaseModel):
    expires: bool = False
    expiration_days_after_earned: int | None = None
    agency_policy_required: bool = True


class ReligiousCompRules(BaseModel):
    expires: bool = False
    agency_policy_required: bool = True


class ReportingConfig(BaseModel):
    default_paper_size: str = "11x17"
    default_orientation: str = "landscape"
    libreoffice_command: str = "libreoffice"
    chart_engine: str = "matplotlib"
    chart_dpi: int = 300


class Config(BaseModel):
    schema_version: int = 1
    user: UserConfig = Field(default_factory=UserConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    holidays: HolidaysConfig = Field(default_factory=HolidaysConfig)
    rules: dict[str, object] = Field(default_factory=lambda: {
        "annual": AnnualRules().model_dump(),
        "sick": SickRules().model_dump(),
        "comp": CompRules().model_dump(),
        "travel_comp": TravelCompRules().model_dump(),
        "credit": CreditRules().model_dump(),
        "time_off_award": TimeOffAwardRules().model_dump(),
        "religious_comp": ReligiousCompRules().model_dump(),
    })
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)


class LeaveYear(BaseModel):
    schema_version: int = 1
    leave_year: int
    leave_year_start: str
    leave_year_end: str
    pay_period_count: int
    annual_leave_accrual_hours: float
    sick_leave_accrual_hours: float
    starting_balances: dict[str, float]
    carryover_from_previous_year: dict[str, float]
    transactions: list[dict] = Field(default_factory=list)
    pay_periods: list[dict] = Field(default_factory=list)
    holidays: list[dict] = Field(default_factory=list)
    rollover_status: dict[str, object] = Field(default_factory=lambda: {
        "rolled_from_previous_year": False,
        "rolled_to_next_year": False,
        "rollover_completed_at": None,
    })


def get_default_data_dir(data_dir: Path | None = None) -> Path:
    if data_dir is not None:
        return data_dir
    env_dir = Path("/home/jlguthri/.local/share/fedleave")
    return env_dir


def load_config(data_dir: Path | None = None) -> dict[str, Any]:
    config_path = get_default_data_dir(data_dir) / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    return json.loads(config_path.read_text())


def init_config(
    year: int,
    leave_year_start: str,
    annual_accrual: float,
    starting_balances: dict[str, float],
    data_dir: Path | None = None,
    holiday_source: str = "python_holidays",
    holiday_ics_url: str = DEFAULT_OPM_ICS_URL,
) -> None:
    data_dir = get_default_data_dir(data_dir)
    ensure_data_dir(data_dir)

    config = Config()
    config.user.display_name = "User"
    config.defaults.annual_leave_accrual_hours = annual_accrual
    config.holidays.source_preference = holiday_source
    # sanitize holiday ICS URL
    try:
        config.holidays.ics_url = sanitize_url(holiday_ics_url)
    except Exception:
        # fallback to default if provided URL invalid
        config.holidays.ics_url = DEFAULT_OPM_ICS_URL

    config_path = data_dir / "config.json"
    if config_path.exists():
        raise typer.Exit(code=1)

    try:
        leave_year_start_date = isoparse(leave_year_start).date()
    except Exception as exc:
        raise ValueError(
            f"Invalid leave year start date: {leave_year_start}. Use YYYY-MM-DD, for example 2026-01-11."
        ) from exc
    pay_periods = generate_pay_periods(leave_year_start_date, 26)
    leave_year_end = pay_periods[-1]["end_date"]

    leave_year = LeaveYear(
        leave_year=year,
        leave_year_start=leave_year_start_date.isoformat(),
        leave_year_end=leave_year_end,
        pay_period_count=len(pay_periods),
        annual_leave_accrual_hours=annual_accrual,
        sick_leave_accrual_hours=4.0,
        starting_balances=starting_balances,
        carryover_from_previous_year=starting_balances.copy(),
        pay_periods=pay_periods,
    )

    atomic_write_json(config_path, config.model_dump(), overwrite=False)
    year_path = data_dir / "leave_years"
    year_path.mkdir(exist_ok=True)
    year_file = year_path / f"{year}.json"
    atomic_write_json(year_file, leave_year.model_dump(), overwrite=False)

    holiday_cache = generate_federal_holidays(year, data_dir, source=holiday_source, ics_url=holiday_ics_url)
    atomic_write_json(data_dir / "holiday_cache" / f"federal_holidays_{year}.json", holiday_cache, overwrite=True)

    console.print(f"Initialized fedleave data in [bold]{data_dir}[/bold]")
