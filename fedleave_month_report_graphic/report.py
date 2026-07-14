from __future__ import annotations

import argparse
import calendar
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from fedleave.ledger import TRANSACTION_CATEGORIES
from fedleave.executable_search import is_executable, iter_executable_candidates

from . import __version__


BASE_WIDTH = 1920
BASE_HEIGHT = 1080
MIN_RESOLUTION = 800
MAX_RESOLUTION = 7680
FEDLEAVE_REPO_URL = "https://github.com/joshua-guthrie/fedleave"

TEXT = "#1f2937"
MUTED = "#64748b"
BORDER = "#94a3b8"
GRID = "#cbd5e1"
HEADER = "#f1f5f9"
OUTSIDE = "#f8fafc"
WEEKEND = "#fafafa"
HOLIDAY_FILL = "#fff7ed"
HOLIDAY_STROKE = "#f97316"
PAYDAY_FILL = "#eff6ff"
PAYDAY_STROKE = "#2563eb"
PAY_PERIOD_STROKE = "#16a34a"
TODAY_FILL = "#fefce8"
TODAY_STROKE = "#ca8a04"
WHITE = "#ffffff"

CATEGORY_LABELS = {
    "annual": ("A", "Annual"),
    "sick": ("S", "Sick"),
    "overtime": ("OT", "Overtime"),
    "comp": ("Comp", "Comp Time"),
    "credit": ("Cr", "Credit"),
    "travel_comp": ("TC", "Travel Comp"),
    "admin": ("Admin", "Admin"),
    "lwop": ("LWOP", "LWOP"),
    "military": ("Mil", "Military"),
    "court": ("Court", "Court"),
    "religious_comp": ("RC", "Religious Comp"),
    "time_off_award": ("TOA", "Time-Off Award"),
    "excused": ("Exc", "Excused"),
    "holiday": ("H", "Holiday"),
    "flex": ("Flex", "Flex"),
    "other": ("Other", "Other"),
    "restored_annual": ("RA", "Restored Annual"),
}

NEGATIVE_DIRECTIONS = {"used", "expired", "forfeited", "voided"}


class MonthReportError(Exception):
    exit_code = 1


class ArgumentError(MonthReportError):
    exit_code = 2


class FedleaveMissingError(MonthReportError):
    exit_code = 3


class FedleaveCommandError(MonthReportError):
    exit_code = 4


class FedleaveJsonError(MonthReportError):
    exit_code = 5


class OutputError(MonthReportError):
    exit_code = 7


class RenderError(MonthReportError):
    exit_code = 8


class ResolutionError(MonthReportError):
    exit_code = 9


@dataclass
class Options:
    output_file: Path
    year: int
    month: int
    resolution: int
    data_dir: Path | None
    fedleave: Path | None
    overwrite: bool
    quiet: bool
    verbose: bool


@dataclass
class ReportData:
    month_json: dict[str, Any]
    balance_json: dict[str, Any]
    projected_json: dict[str, Any]
    pay_periods_json: dict[str, Any] | None
    today: date
    generated_at: datetime


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


def _die(message: str, exc_type: type[MonthReportError]) -> None:
    raise exc_type(message)


def parse_month(value: str) -> int:
    text = str(value).strip()
    if text.isdigit():
        month = int(text)
        if 1 <= month <= 12:
            return month
        raise ArgumentError("--month must be between 1 and 12.")

    names = {name.lower(): index for index, name in enumerate(calendar.month_name) if name}
    lowered = text.lower()
    if lowered in names:
        return names[lowered]
    raise ArgumentError("--month must be a number from 1 to 12 or a full English month name.")


def parse_args(argv: list[str] | None = None) -> Options:
    parser = argparse.ArgumentParser(
        prog="fedleaveMonthReportGraphic",
        description="Generate a landscape FedLeave graphical month report.",
    )
    parser.add_argument("--outputFile", help="Output .png or .svg file path.")
    parser.add_argument("--year", type=int, help="Calendar year to report.")
    parser.add_argument("--month", help="Month number or full English month name.")
    parser.add_argument("--resolution", type=int, default=BASE_WIDTH, help="Output image width in pixels.")
    parser.add_argument("--data-dir", help="fedleave data directory override.")
    parser.add_argument("--fedleave", help="Explicit path to fedleave executable.")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output file.")
    parser.add_argument("--verbose", action="store_true", help="Print diagnostic information.")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-error output.")
    parser.add_argument("--version", action="store_true", help="Print version and exit.")
    args = parser.parse_args(argv)

    if args.version:
        print(f"fedleaveMonthReportGraphic {__version__}")
        raise SystemExit(0)

    if not args.outputFile:
        raise ArgumentError("--outputFile is required.")

    if (args.year is None) ^ (args.month is None):
        raise ArgumentError("--year and --month must be supplied together.")

    today = date.today()
    year = args.year if args.year is not None else today.year
    month = parse_month(args.month) if args.month is not None else today.month

    if args.resolution < MIN_RESOLUTION or args.resolution > MAX_RESOLUTION:
        raise ResolutionError(f"--resolution must be between {MIN_RESOLUTION} and {MAX_RESOLUTION}.")

    output_file = Path(args.outputFile).expanduser()
    suffix = output_file.suffix.lower()
    if suffix not in {".png", ".svg"}:
        raise ArgumentError("Only .png and .svg output files are supported.")
    if output_file.exists() and not args.overwrite:
        raise OutputError(f"Output file already exists: {output_file}. Use --overwrite to replace it.")

    return Options(
        output_file=output_file,
        year=year,
        month=month,
        resolution=args.resolution,
        data_dir=Path(args.data_dir).expanduser() if args.data_dir else None,
        fedleave=Path(args.fedleave).expanduser() if args.fedleave else None,
        overwrite=args.overwrite,
        quiet=bool(args.quiet),
        verbose=bool(args.verbose),
    )


def find_fedleave(explicit: Path | None = None) -> Path:
    searched: list[Path] = []
    if explicit is not None:
        candidate = explicit.resolve()
        searched.append(candidate)
        if sys.platform.startswith("win") and candidate.is_file():
            return candidate
        if is_executable(candidate):
            return candidate
        raise FedleaveMissingError(f"fedleave executable not found or not executable: {candidate}")

    for candidate in iter_executable_candidates("fedleave"):
        searched.append(candidate)
        if is_executable(candidate):
            return candidate

    path_hit = shutil.which("fedleave")
    if path_hit:
        return Path(path_hit)

    details = "\n".join(f"  - {path}" for path in searched)
    raise FedleaveMissingError(
        "fedleave executable not found.\n\n"
        f"Searched:\n{details}\n\n"
        f"Install fedleave from {FEDLEAVE_REPO_URL} or pass --fedleave PATH."
    )


def run_fedleave(fedleave: Path, args: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        [str(fedleave), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise FedleaveCommandError(
            "fedleave command failed.\n\n"
            f"Command: {fedleave} {' '.join(args)}\n"
            f"Exit code: {result.returncode}\n"
            f"Details: {detail}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FedleaveJsonError(f"Invalid JSON returned by fedleave: {exc}") from exc
    if not isinstance(payload, dict):
        raise FedleaveJsonError("fedleave returned JSON that was not an object.")
    return payload


def load_report_data(options: Options) -> tuple[Path, ReportData]:
    fedleave = find_fedleave(options.fedleave)
    common = ["--data-dir", str(options.data_dir)] if options.data_dir else []
    month_json = run_fedleave(
        fedleave,
        ["month", "--year", str(options.year), "--month", str(options.month), "--json", *common],
    )
    balance_json = month_json.get("balance_as_of_today")
    if not isinstance(balance_json, dict) or "balances" not in balance_json:
        balance_json = run_fedleave(
            fedleave,
            ["balance", "--year", str(options.year), "--as-of", "today", "--json", *common],
        )

    try:
        projected_json = run_fedleave(
            fedleave,
            ["use-or-lose", "--year", str(options.year), "--json", *common],
        )
    except FedleaveCommandError:
        projected_json = month_json.get("projected_balance")
    if not isinstance(projected_json, dict) or "use_or_lose" not in projected_json:
        projected_json = run_fedleave(
            fedleave,
            ["balance", "--year", str(options.year), "--project", "--use-or-lose", "--json", *common],
        )
    pay_periods_json = None

    return fedleave, ReportData(
        month_json=month_json,
        balance_json=balance_json,
        projected_json=projected_json,
        pay_periods_json=pay_periods_json,
        today=date.today(),
        generated_at=datetime.now(),
    )


def _fmt(value: Any, *, signed: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if abs(number) < 0.00001:
        return ""
    if number.is_integer():
        text = str(int(abs(number)))
    else:
        text = f"{abs(number):.2f}".rstrip("0").rstrip(".")
    sign = ""
    if signed:
        sign = "+" if number > 0 else "-"
    elif number < 0:
        sign = "-"
    return f"{sign}{text}"


def _entry_line(entry: dict[str, Any]) -> tuple[str, str]:
    category = str(entry.get("category", ""))
    label = CATEGORY_LABELS.get(category, (category, category))[0]
    direction = str(entry.get("direction", ""))
    hours = float(entry.get("hours", 0.0) or 0.0)
    if direction in NEGATIVE_DIRECTIONS:
        hours = -abs(hours)
    return label, _fmt(hours, signed=True)


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _svg_text(x: float, y: float, text: Any, size: int, *, weight: int = 400, fill: str = TEXT, anchor: str = "start", family: str = "Arial, Helvetica, sans-serif") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{_escape(text)}</text>'
    )


def _wrap_words(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:2]


def _day_map(days: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(day.get("date")): day for day in days}


def _six_week_days(month_json: dict[str, Any]) -> list[dict[str, Any]]:
    days = list(month_json.get("days", []))
    if not days:
        return []
    mapped = _day_map(days)
    year = int(month_json.get("year", date.fromisoformat(str(days[0]["date"])).year))
    month = int(month_json.get("month", date.fromisoformat(str(days[0]["date"])).month))
    start = date.fromisoformat(str(days[0]["date"]))
    while len(days) < 42:
        next_date = start.fromordinal(start.toordinal() + len(days))
        key = next_date.isoformat()
        days.append(
            mapped.get(
                key,
                {
                    "date": key,
                    "in_display_month": next_date.year == year and next_date.month == month,
                    "holiday_name": None,
                    "entries": [],
                    "display_lines": [],
                },
            )
        )
    return days[:42]


def _pay_period_end_dates(month_json: dict[str, Any]) -> set[str]:
    from_days = {str(day.get("date")) for day in month_json.get("days", []) if day.get("is_pay_period_end")}
    from_periods = {str(period.get("end")) for period in month_json.get("pay_periods", []) if period.get("end")}
    return from_days | from_periods


def _pay_dates(month_json: dict[str, Any]) -> set[str]:
    from_days = {str(day.get("date")) for day in month_json.get("days", []) if day.get("is_payday")}
    from_periods = {str(period.get("pay_date")) for period in month_json.get("pay_periods", []) if period.get("pay_date")}
    from_top_level = {str(pay_date) for pay_date in month_json.get("pay_dates", []) if pay_date}
    return from_days | from_periods | from_top_level


def render_svg(data: ReportData, width: int) -> str:
    height = round(width * 9 / 16)
    scale = width / BASE_WIDTH
    def sx(value: float) -> float:
        return value * scale
    def sy(value: float) -> float:
        return value * scale

    month_json = data.month_json
    month_name = calendar.month_name[int(month_json.get("month", data.today.month))]
    year = int(month_json.get("year", data.today.year))
    title = f"FedLeave Month Report - {month_name} {year}"
    generated = data.generated_at.strftime("%B %-d, %Y %H:%M") if not sys.platform.startswith("win") else data.generated_at.strftime("%B %#d, %Y %H:%M")

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {BASE_WIDTH} {BASE_HEIGHT}">',
        f'<rect width="{BASE_WIDTH}" height="{BASE_HEIGHT}" fill="{WHITE}"/>',
        _svg_text(28, 40, title, 32, weight=700),
        _svg_text(1892, 40, f"Generated: {generated}", 18, fill=MUTED, anchor="end"),
        '<line x1="28" y1="58" x2="1892" y2="58" stroke="#e5e7eb" stroke-width="2"/>',
    ]
    parts.extend(_render_calendar_svg(month_json, data.today))
    parts.extend(_render_side_panel_svg(data))
    parts.extend(_render_bottom_svg(data))
    parts.append("</svg>")
    # Keep the external dimensions scaled while using a stable 1920x1080 layout coordinate system.
    if width != BASE_WIDTH:
        parts[0] = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {BASE_WIDTH} {BASE_HEIGHT}">'
    _ = sx, sy
    return "\n".join(parts)


def _render_calendar_svg(month_json: dict[str, Any], today: date) -> list[str]:
    x0, y0, w, h = 28.0, 88.0, 1180.0, 650.0
    header_h = 34.0
    cell_w = w / 7
    cell_h = (h - header_h) / 6
    days = _six_week_days(month_json)
    pp_end_dates = _pay_period_end_dates(month_json)
    pay_dates = _pay_dates(month_json)
    parts = [
        _svg_text(28, 78, "Calendar", 22, weight=700),
        f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="{WHITE}" stroke="{BORDER}" stroke-width="2" rx="6"/>',
    ]
    for col, name in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
        x = x0 + col * cell_w
        parts.append(f'<rect x="{x:.1f}" y="{y0}" width="{cell_w:.1f}" height="{header_h}" fill="{HEADER}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(_svg_text(x + cell_w / 2, y0 + 23, name, 15, weight=700, anchor="middle"))

    for index, day in enumerate(days):
        row, col = divmod(index, 7)
        x = x0 + col * cell_w
        y = y0 + header_h + row * cell_h
        day_date = date.fromisoformat(str(day["date"]))
        in_month = bool(day.get("in_display_month"))
        is_today = day_date == today
        is_holiday = bool(day.get("holiday_name"))
        is_payday = str(day.get("date")) in pay_dates and in_month
        is_pp_end = str(day.get("date")) in pp_end_dates

        fill = WHITE if in_month else OUTSIDE
        stroke = GRID
        stroke_w = 1
        if col in {0, 6} and in_month:
            fill = WEEKEND
        if is_payday:
            fill, stroke, stroke_w = PAYDAY_FILL, PAYDAY_STROKE, 3
        if is_holiday:
            fill, stroke, stroke_w = HOLIDAY_FILL, HOLIDAY_STROKE, 3
        if is_today:
            fill, stroke, stroke_w = TODAY_FILL, TODAY_STROKE, 3
        if is_pp_end and not is_holiday and not is_today:
            stroke, stroke_w = PAY_PERIOD_STROKE, 3

        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_w:.1f}" height="{cell_h:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w}"/>')
        day_fill = TEXT if in_month else BORDER
        parts.append(_svg_text(x + cell_w - 10, y + 22, day_date.day, 17, weight=700, fill=day_fill, anchor="end"))
        if is_pp_end:
            parts.append(f'<path d="M {x + cell_w - 26:.1f} {y + cell_h - 6:.1f} L {x + cell_w - 6:.1f} {y + cell_h - 6:.1f} L {x + cell_w - 6:.1f} {y + cell_h - 26:.1f} Z" fill="{PAY_PERIOD_STROKE}"/>')

        y_text = y + 42
        if is_holiday:
            for line in _wrap_words(str(day.get("holiday_name")), 16):
                parts.append(_svg_text(x + 10, y_text, line, 13, weight=700, fill="#9a3412"))
                y_text += 16
            y_text += 4
        for entry in day.get("entries", [])[:4]:
            label, amount = _entry_line(entry)
            if not amount:
                continue
            parts.append(_svg_text(x + 14, y_text, label, 15, weight=700))
            parts.append(_svg_text(x + cell_w - 14, y_text, amount, 15, weight=700, anchor="end", family="Consolas, 'Courier New', monospace"))
            y_text += 19
    return parts


def _render_table_svg(x: float, y: float, headers: list[str], rows: list[list[str]], widths: list[float], row_h: float = 22.0, font_size: int = 12) -> list[str]:
    parts: list[str] = []
    total_w = sum(widths)
    parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{total_w:.1f}" height="24" fill="{HEADER}" stroke="{GRID}" stroke-width="1"/>')
    cursor = x
    for i, header in enumerate(headers):
        anchor = "start" if i == 0 else "middle"
        tx = cursor + 6 if i == 0 else cursor + widths[i] / 2
        parts.append(_svg_text(tx, y + 17, header, font_size, weight=700, anchor=anchor))
        parts.append(f'<line x1="{cursor:.1f}" y1="{y:.1f}" x2="{cursor:.1f}" y2="{y + 24 + len(rows) * row_h:.1f}" stroke="{GRID}" stroke-width="1"/>')
        cursor += widths[i]
    parts.append(f'<line x1="{cursor:.1f}" y1="{y:.1f}" x2="{cursor:.1f}" y2="{y + 24 + len(rows) * row_h:.1f}" stroke="{GRID}" stroke-width="1"/>')

    for row_index, row in enumerate(rows):
        ry = y + 24 + row_index * row_h
        parts.append(f'<rect x="{x:.1f}" y="{ry:.1f}" width="{total_w:.1f}" height="{row_h:.1f}" fill="{WHITE}" stroke="{GRID}" stroke-width="1"/>')
        cursor = x
        for i, value in enumerate(row):
            anchor = "start" if i == 0 else "end"
            tx = cursor + 6 if i == 0 else cursor + widths[i] - 6
            family = "Arial, Helvetica, sans-serif" if i == 0 else "Consolas, 'Courier New', monospace"
            parts.append(_svg_text(tx, ry + 15, value, font_size, anchor=anchor, family=family))
            cursor += widths[i]
    return parts


def _pay_period_rows(period: dict[str, Any], *, max_rows: int = 8) -> list[list[str]]:
    totals = period.get("totals", {})
    balances = period.get("ending_balances", {})
    categories = sorted({*totals.keys(), *balances.keys()})
    rows: list[list[str]] = []
    for category in categories:
        period_totals = totals.get(category, {})
        earned = _fmt(period_totals.get("earned"))
        used = _fmt(period_totals.get("used"))
        balance = _fmt(balances.get(category))
        if not any([earned, used, balance]):
            continue
        rows.append([CATEGORY_LABELS.get(category, (category, category))[1], earned, used, balance])
    return rows[:max_rows]


def _render_side_panel_svg(data: ReportData) -> list[str]:
    parts = [
        _svg_text(1224, 78, "Pay Period", 22, weight=700),
        f'<rect x="1224" y="88" width="668" height="650" fill="{WHITE}" stroke="{BORDER}" stroke-width="2" rx="6"/>',
    ]
    y = 122.0
    for period in data.month_json.get("pay_periods", [])[:4]:
        title = f"PP {period.get('number')}   {period.get('start')} - {period.get('end')}"
        parts.append(_svg_text(1234, y, title, 16, weight=700))
        rows = _pay_period_rows(period)
        parts.extend(
            _render_table_svg(
                1234,
                y + 8,
                ["Type", "Earned", "Used", "Balance"],
                rows,
                [184, 72, 72, 86],
                row_h=19,
                font_size=11,
            )
        )
        y += 44 + 19 * max(1, len(rows)) + 14

    return parts


def _balance_rows(data: ReportData) -> list[list[str]]:
    balances = data.balance_json.get("balances", {})
    use_or_lose = data.projected_json.get("use_or_lose") or {}
    rows = []
    for category, value in sorted(balances.items()):
        balance = _fmt(value)
        lose = _fmt(use_or_lose.get("use_or_lose")) if category == "annual" else ""
        if not any([balance, lose]):
            continue
        rows.append([CATEGORY_LABELS.get(category, (category, category))[1], balance, lose])
    return rows[:10]


def _abbreviation_columns() -> list[list[list[str]]]:
    rows = [
        [
            CATEGORY_LABELS.get(category, (category, category))[0],
            CATEGORY_LABELS.get(category, (category, category))[1],
        ]
        for category in TRANSACTION_CATEGORIES
    ]
    return [rows[index:index + 6] for index in range(0, len(rows), 6)]


def _marker_legend_items() -> list[tuple[str, str, str]]:
    return [
        ("Holiday", HOLIDAY_FILL, HOLIDAY_STROKE),
        ("Pay Day", PAYDAY_FILL, PAYDAY_STROKE),
        ("Pay Period End", WHITE, PAY_PERIOD_STROKE),
        ("Today", TODAY_FILL, TODAY_STROKE),
    ]


def _render_marker_legend_svg(x: float, y: float) -> list[str]:
    parts: list[str] = []
    for index, (label, fill, stroke) in enumerate(_marker_legend_items()):
        item_x = x + index * 154
        parts.append(
            f'<rect x="{item_x:.1f}" y="{y - 14:.1f}" width="16" height="16" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        parts.append(_svg_text(item_x + 24, y, label, 11))
    return parts


def _render_bottom_svg(data: ReportData) -> list[str]:
    parts = [
        _svg_text(28, 780, "As of Today", 22, weight=700),
        f'<rect x="28" y="790" width="1180" height="250" fill="{WHITE}" stroke="{BORDER}" stroke-width="2" rx="6"/>',
    ]
    parts.extend(
        _render_table_svg(
            42,
            808,
            ["Category", "Balance", "End of Year Use or Loose"],
            _balance_rows(data),
            [220, 110, 190],
            row_h=21,
            font_size=12,
        )
    )

    parts.extend([
        _svg_text(1224, 780, "Abbreviations", 22, weight=700),
        f'<rect x="1224" y="790" width="668" height="250" fill="{WHITE}" stroke="{BORDER}" stroke-width="2" rx="6"/>',
    ])
    for index, rows in enumerate(_abbreviation_columns()):
        parts.extend(_render_table_svg(1238 + index * 216, 808, ["Abbr", "Category"], rows, [48, 154], row_h=20, font_size=11))
    parts.extend(_render_marker_legend_svg(1240, 1018))
    return parts


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        windows_fonts / ("arialbd.ttf" if bold else "arial.ttf"),
        windows_fonts / ("segoeuib.ttf" if bold else "segoeui.ttf"),
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def render_png(data: ReportData, output: Path, width: int) -> None:
    # PNG rendering mirrors the SVG structure at a raster level. SVG remains the canonical internal report.
    height = round(width * 9 / 16)
    scale = width / BASE_WIDTH
    image = Image.new("RGB", (width, height), _hex_to_rgb(WHITE))
    draw = ImageDraw.Draw(image)
    font = load_font(max(9, int(13 * scale)))
    bold = load_font(max(9, int(13 * scale)), bold=True)
    title_font = load_font(max(16, int(32 * scale)), bold=True)

    def rect(box, fill=WHITE, outline=GRID, width_px=1):
        draw.rectangle(tuple(int(v * scale) for v in box), fill=_hex_to_rgb(fill), outline=_hex_to_rgb(outline), width=max(1, int(width_px * scale)))

    def text(x, y, value, fill=TEXT, font_obj=None, anchor="la"):
        draw.text((int(x * scale), int(y * scale)), str(value), fill=_hex_to_rgb(fill), font=font_obj or font, anchor=anchor)

    text(28, 18, f"FedLeave Month Report - {calendar.month_name[int(data.month_json.get('month', 1))]} {data.month_json.get('year')}", font_obj=title_font)
    text(1892, 24, f"Generated: {data.generated_at:%B %d, %Y %H:%M}", fill=MUTED, anchor="ra")
    draw.line((int(28 * scale), int(58 * scale), int(1892 * scale), int(58 * scale)), fill=_hex_to_rgb("#e5e7eb"), width=max(1, int(2 * scale)))

    # Draw a simplified but complete raster representation. The SVG contains the exact table/grid structure.
    month_json = data.month_json
    x0, y0, w, h = 28.0, 88.0, 1180.0, 650.0
    cell_w, cell_h = w / 7, (h - 34) / 6
    text(28, 64, "Calendar", font_obj=bold)
    rect((x0, y0, x0 + w, y0 + h), outline=BORDER, width_px=2)
    for col, name in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
        x = x0 + col * cell_w
        rect((x, y0, x + cell_w, y0 + 34), fill=HEADER)
        text(x + cell_w / 2, y0 + 17, name, font_obj=bold, anchor="mm")
    pp_end_dates = _pay_period_end_dates(month_json)
    pay_dates = _pay_dates(month_json)
    for index, day in enumerate(_six_week_days(month_json)):
        row, col = divmod(index, 7)
        x, y = x0 + col * cell_w, y0 + 34 + row * cell_h
        day_date = date.fromisoformat(str(day["date"]))
        in_month = bool(day.get("in_display_month"))
        fill = WHITE if in_month else OUTSIDE
        outline, line_w = GRID, 1
        if in_month and col in {0, 6}:
            fill = WEEKEND
        if str(day["date"]) in pay_dates and in_month:
            fill, outline, line_w = PAYDAY_FILL, PAYDAY_STROKE, 3
        if day.get("holiday_name"):
            fill, outline, line_w = HOLIDAY_FILL, HOLIDAY_STROKE, 3
        if day_date == data.today:
            fill, outline, line_w = TODAY_FILL, TODAY_STROKE, 3
        if str(day["date"]) in pp_end_dates and not day.get("holiday_name") and day_date != data.today:
            outline, line_w = PAY_PERIOD_STROKE, 3
        rect((x, y, x + cell_w, y + cell_h), fill=fill, outline=outline, width_px=line_w)
        text(x + cell_w - 10, y + 12, day_date.day, fill=TEXT if in_month else BORDER, font_obj=bold, anchor="ra")
        yy = y + 38
        if day.get("holiday_name"):
            for line in _wrap_words(str(day["holiday_name"]), 15):
                text(x + 10, yy, line, fill="#9a3412", font_obj=bold)
                yy += 17
        for entry in day.get("entries", [])[:4]:
            label, amount = _entry_line(entry)
            if amount:
                text(x + 14, yy, label, font_obj=bold)
                text(x + cell_w - 14, yy, amount, font_obj=bold, anchor="ra")
                yy += 18

    text(1224, 64, "Pay Period", font_obj=bold)
    rect((1224, 88, 1892, 738), outline=BORDER, width_px=2)

    y = 112
    for period in month_json.get("pay_periods", [])[:4]:
        text(1234, y, f"PP {period.get('number')}   {period.get('start')} - {period.get('end')}", font_obj=bold)
        y += 24
        text(1240, y, "Type", font_obj=bold)
        text(1512, y, "Earned", font_obj=bold, anchor="ra")
        text(1588, y, "Used", font_obj=bold, anchor="ra")
        text(1678, y, "Balance", font_obj=bold, anchor="ra")
        y += 18
        for row in _pay_period_rows(period, max_rows=7):
            text(1240, y, row[0])
            text(1512, y, row[1], anchor="ra")
            text(1588, y, row[2], anchor="ra")
            text(1678, y, row[3], anchor="ra")
            y += 17
        y += 14
    text(28, 764, "As of Today", font_obj=bold)
    rect((28, 790, 1208, 1040), outline=BORDER, width_px=2)
    text(42, 802, "Category", font_obj=bold)
    text(480, 802, "Balance", font_obj=bold, anchor="ra")
    text(740, 802, "End of Year Use or Loose", font_obj=bold, anchor="ra")
    yy = 816
    for row in _balance_rows(data):
        text(42, yy, row[0])
        text(480, yy, row[1], anchor="ra")
        text(740, yy, row[2], anchor="ra")
        yy += 19
    text(1224, 764, "Abbreviations", font_obj=bold)
    rect((1224, 790, 1892, 1040), outline=BORDER, width_px=2)
    for column, rows in enumerate(_abbreviation_columns()):
        x = 1240 + column * 216
        text(x, 802, "Abbr", font_obj=bold)
        text(x + 52, 802, "Category", font_obj=bold)
        yy = 816
        for abbr, label in rows:
            text(x, yy, abbr, font_obj=bold)
            text(x + 52, yy, label)
            yy += 18
    for index, (label, fill, outline) in enumerate(_marker_legend_items()):
        x = 1240 + index * 154
        rect((x, 1004, x + 16, 1020), fill=fill, outline=outline, width_px=2)
        text(x + 24, 1005, label)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")


def write_output(data: ReportData, options: Options) -> None:
    output = options.output_file.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix.lower()
    try:
        if suffix == ".svg":
            content = render_svg(data, options.resolution)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(output.parent), suffix=".tmp") as handle:
                handle.write(content)
                temp_name = handle.name
            Path(temp_name).replace(output)
        elif suffix == ".png":
            render_svg(data, options.resolution)
            temp = output.with_name(f".{output.name}.{os.getpid()}.tmp")
            render_png(data, temp, options.resolution)
            temp.replace(output)
        else:
            raise OutputError("Only .png and .svg output files are supported.")
    except MonthReportError:
        raise
    except Exception as exc:
        raise RenderError(f"Failed to render report: {exc}") from exc


def main(argv: list[str] | None = None) -> None:
    start = time.perf_counter()
    try:
        options = parse_args(argv)
        fedleave, data = load_report_data(options)
        write_output(data, options)
        if not options.quiet:
            print(f"Created output: {options.output_file.resolve()}")
        if options.verbose:
            elapsed = time.perf_counter() - start
            print(json.dumps({
                "fedleave": str(fedleave),
                "year": options.year,
                "month": options.month,
                "output": str(options.output_file.resolve()),
                "resolution": options.resolution,
                "image_dimensions": {"width": options.resolution, "height": round(options.resolution * 9 / 16)},
                "render_seconds": round(elapsed, 3),
            }, indent=2))
    except MonthReportError as exc:
        _eprint(f"ERROR: {exc}")
        raise SystemExit(exc.exit_code)


if __name__ == "__main__":
    main()
