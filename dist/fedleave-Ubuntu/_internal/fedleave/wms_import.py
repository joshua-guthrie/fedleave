from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime as _datetime
from html.parser import HTMLParser
from pathlib import Path
import platform
import re
from typing import Any

from . import __version__
from .config import LeaveYear
from .ledger import create_transaction
from .payperiods import generate_pay_periods


WMS_SUPPORT_URL = "https://github.com/joshua-guthrie/fedleave/issues/new"


class WmsImportError(ValueError):
    """An import failure carrying safe, copyable diagnostic context."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}

    def support_report(self, input_path: Path | None = None) -> str:
        lines = [
            "WMS IMPORT COULD NOT CONTINUE",
            "",
            f"Problem: {self}",
            f"FedLeave version: {__version__}",
            f"Platform: {platform.system()} {platform.release()}",
        ]
        if input_path is not None:
            lines.append(f"Input file: {input_path}")
        for label, value in self.details.items():
            if value not in (None, "", []):
                lines.append(f"{label}: {value}")
        lines.extend(
            [
                "",
                "Please report this WMS format to FedLeave:",
                f"1. Open {WMS_SUPPORT_URL}",
                "2. Copy and paste this complete diagnostic into the issue.",
                "3. Attach the original WMS HTML report so the importer can be updated.",
                "   Review the report for personal information before attaching it.",
            ]
        )
        return "\n".join(lines)


@dataclass(frozen=True)
class WmsTransactionSpec:
    date: str
    category: str
    direction: str
    hours: float
    description: str
    status: str = "reconciled"
    source: str = "wms-http"


@dataclass(frozen=True)
class WmsImportReport:
    leave_year: int
    leave_year_start: str
    leave_year_end: str
    generated_by: str | None
    generated_date: str | None
    specs: list[WmsTransactionSpec]
    ignored_rows: int


@dataclass(frozen=True)
class _WmsRule:
    category: str
    direction: str


_IGNORED_CODES = {"RG", "RF", "RR"}

_CODE_RULES: dict[str, _WmsRule] = {
    "CD": _WmsRule("credit", "earned"),
    "CE": _WmsRule("comp", "earned"),
    "CF": _WmsRule("travel_comp", "used"),
    "CN": _WmsRule("credit", "used"),
    "CT": _WmsRule("comp", "used"),
    "HG": _WmsRule("holiday", "earned"),
    "KA": _WmsRule("lwop", "used"),
    "KB": _WmsRule("lwop", "used"),
    "KC": _WmsRule("lwop", "used"),
    "KD": _WmsRule("lwop", "used"),
    "KE": _WmsRule("lwop", "used"),
    "KG": _WmsRule("military", "used"),
    "LA": _WmsRule("annual", "used"),
    "LB": _WmsRule("annual", "used"),
    "LC": _WmsRule("court", "used"),
    "LG": _WmsRule("sick", "used"),
    "LH": _WmsRule("holiday", "earned"),
    "LM": _WmsRule("military", "used"),
    "LN": _WmsRule("admin", "earned"),
    "LP": _WmsRule("restored_annual", "used"),
    "LQ": _WmsRule("restored_annual", "used"),
    "LR": _WmsRule("restored_annual", "used"),
    "LS": _WmsRule("sick", "used"),
    "LT": _WmsRule("excused", "earned"),
    "LU": _WmsRule("excused", "earned"),
    "LV": _WmsRule("excused", "earned"),
    "LX": _WmsRule("excused", "earned"),
    "LY": _WmsRule("time_off_award", "used"),
    "OC": _WmsRule("overtime", "worked"),
    "OS": _WmsRule("overtime", "worked"),
    "OU": _WmsRule("overtime", "worked"),
    "OX": _WmsRule("overtime", "worked"),
}


class _ClockingReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._jr_page_depth = 0
        self._tr_depth = 0
        self._td_depth = 0
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value or "" for name, value in attrs}
        tag = tag.lower()
        if tag == "table" and "jrPage" in attr_map.get("class", ""):
            self._jr_page_depth += 1
        elif tag == "tr" and self._jr_page_depth:
            self._tr_depth += 1
            if self._tr_depth == 1:
                self._current_row = []
        elif tag == "td" and self._jr_page_depth and self._tr_depth == 1:
            self._td_depth += 1
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "td" and self._jr_page_depth and self._tr_depth == 1 and self._td_depth:
            text = "".join(self._current_cell or []).replace("\xa0", " ")
            text = " ".join(text.split())
            if self._current_row is not None:
                self._current_row.append(text)
            self._current_cell = None
            self._td_depth -= 1
        elif tag == "tr" and self._jr_page_depth:
            if self._tr_depth == 1 and self._current_row is not None:
                self.rows.append(self._current_row)
                self._current_row = None
            if self._tr_depth:
                self._tr_depth -= 1
        elif tag == "table" and self._jr_page_depth:
            self._jr_page_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._jr_page_depth and self._tr_depth == 1 and self._td_depth and self._current_cell is not None:
            self._current_cell.append(data)


def _cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    return str(row[index]).strip()


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        try:
            return _datetime.strptime(value, "%d-%b-%Y").date()
        except Exception as inner_exc:
            raise WmsImportError(f"Invalid WMS date: {value}") from inner_exc


def _parse_date_range(rows: list[list[str]]) -> tuple[date, date]:
    text = " ".join(cell for row in rows[:16] for cell in row if cell)
    match = re.search(
        r"(?P<start>\d{1,2}-[A-Za-z]{3}-\d{4})\s*-\s*(?P<end>\d{1,2}-[A-Za-z]{3}-\d{4})",
        text,
    )
    if not match:
        raise WmsImportError("Could not find the WMS report date range.")
    return _parse_date(match.group("start")), _parse_date(match.group("end"))


def _format_clock_time(raw: str) -> str | None:
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    hours = int(value)
    minutes = int(round((value - hours) * 60))
    if minutes == 60:
        hours += 1
        minutes = 0
    return f"{hours:02d}:{minutes:02d}"


def _format_description(raw_code: str, start_time: str | None, hours: float, status: str | None) -> str:
    parts = ["FRC-E WMS HTTP Leave Report", raw_code, f"{hours:.2f} hours"]
    if start_time:
        parts.insert(2, f"start {start_time}")
    if status and status not in {"", "No Transaction"}:
        parts.append(status)
    return " ".join(parts)


def _row_to_spec(row: list[str], row_number: int | None = None) -> WmsTransactionSpec | None:
    row_date = _cell(row, 13)
    raw_code = _cell(row, 15)
    if not row_date or not raw_code:
        return None
    try:
        parsed_date = _parse_date(row_date)
    except WmsImportError as exc:
        raise WmsImportError(
            f"Invalid WMS transaction date {row_date!r}.",
            details={"Report row": row_number, "Leave code": raw_code, "Row cells": row},
        ) from exc

    base_code, _, _subcode = raw_code.partition("/")
    if base_code in _IGNORED_CODES:
        return None

    rule = _CODE_RULES.get(base_code)
    if rule is None:
        raise WmsImportError(
            f"Unsupported WMS leave code {raw_code} on {row_date}",
            details={"Report row": row_number, "Leave code": raw_code, "Row cells": row},
        )

    hours_text = _cell(row, 25)
    try:
        hours = float(hours_text)
    except ValueError as exc:
        raise WmsImportError(
            f"Invalid hours for {raw_code} on {row_date}: {hours_text}",
            details={"Report row": row_number, "Leave code": raw_code, "Row cells": row},
        ) from exc

    start_time = _format_clock_time(_cell(row, 23))
    status = _cell(row, 31)
    description = _format_description(raw_code, start_time, hours, status or None)
    return WmsTransactionSpec(
        date=parsed_date.isoformat(),
        category=rule.category,
        direction=rule.direction,
        hours=hours,
        description=description,
    )


def parse_wms_http_leave_report(html_text: str) -> WmsImportReport:
    parser = _ClockingReportParser()
    parser.feed(html_text.replace("&nbsp;", " "))
    if not parser.rows:
        raise WmsImportError("The supplied file does not look like a WMS clocking report.")
    if not any("Clocking Report" in cell for row in parser.rows[:10] for cell in row):
        raise WmsImportError("The supplied file does not contain a WMS clocking report title.")

    leave_year_start, leave_year_end = _parse_date_range(parser.rows)
    leave_year = leave_year_start.year
    generated_by = None
    generated_date = None
    for row in parser.rows[:12]:
        if "Generated By:" in row:
            index = row.index("Generated By:")
            if index + 1 < len(row):
                generated_by = row[index + 1] or None
        if "Generated Date:" in row:
            index = row.index("Generated Date:")
            if index + 1 < len(row):
                generated_date = row[index + 1] or None

    specs: list[WmsTransactionSpec] = []
    ignored_rows = 0
    for row_number, row in enumerate(parser.rows, start=1):
        spec = _row_to_spec(row, row_number)
        if spec is None:
            if _cell(row, 13) and _cell(row, 15):
                ignored_rows += 1
            continue
        specs.append(spec)

    return WmsImportReport(
        leave_year=leave_year,
        leave_year_start=leave_year_start.isoformat(),
        leave_year_end=leave_year_end.isoformat(),
        generated_by=generated_by,
        generated_date=generated_date,
        specs=specs,
        ignored_rows=ignored_rows,
    )


def build_leave_year_skeleton(report: WmsImportReport, annual_accrual: float) -> dict[str, Any]:
    start = date.fromisoformat(report.leave_year_start)
    pay_periods = generate_pay_periods(start, 26)
    leave_year = LeaveYear(
        leave_year=report.leave_year,
        leave_year_start=report.leave_year_start,
        leave_year_end=pay_periods[-1]["end_date"],
        pay_period_count=len(pay_periods),
        annual_leave_accrual_hours=annual_accrual,
        sick_leave_accrual_hours=4.0,
        starting_balances={
            "annual": 0.0,
            "sick": 0.0,
            "comp": 0.0,
            "credit": 0.0,
            "travel_comp": 0.0,
            "time_off_award": 0.0,
            "religious_comp": 0.0,
            "restored_annual": 0.0,
        },
        carryover_from_previous_year={
            "annual": 0.0,
            "sick": 0.0,
            "comp": 0.0,
            "credit": 0.0,
            "travel_comp": 0.0,
            "time_off_award": 0.0,
            "religious_comp": 0.0,
            "restored_annual": 0.0,
        },
        pay_periods=pay_periods,
    ).model_dump()
    return leave_year


def build_transactions_from_report(report: WmsImportReport, existing_ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    transactions: list[dict[str, Any]] = []
    used_ids = list(existing_ids)
    for spec in report.specs:
        transaction = create_transaction(
            date=spec.date,
            category=spec.category,
            direction=spec.direction,
            hours=spec.hours,
            description=spec.description,
            status=spec.status,
            source=spec.source,
            existing_ids=used_ids,
        ).model_dump()
        transactions.append(transaction)
        used_ids.append(str(transaction["id"]))
    return transactions, used_ids


def report_transaction_keys(report: WmsImportReport) -> set[tuple[str, str, str]]:
    return {(spec.date, spec.category, spec.direction) for spec in report.specs}
