from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .executable_search import is_executable, iter_executable_candidates


BASE_WIDTH = 1610
BASE_HEIGHT = 1180
BASE_ASPECT_RATIO = BASE_HEIGHT / BASE_WIDTH
PLOT_LEFT = 78
PLOT_TOP = 122
PLOT_RIGHT = 1580
PLOT_BOTTOM = 912
Y_MIN = Decimal("0")

BLUE = "#4F81BD"
RED = "#C0504D"
GRID_MAJOR = "#8F8F8F"
GRID_MINOR = "#A9A9A9"
BORDER = "#808080"
TEXT = "#000000"
BACKGROUND = "#FFFFFF"

FEDLEAVE_REPO_URL = "https://github.com/joshua-guthrie/fedleave"


@dataclass(frozen=True)
class LeaveChartSpec:
    app_name: str
    title: str
    category: str
    product: str
    point_field: str = "balance_hours"


class ChartDimensions:
    def __init__(self, width_pixels: int = BASE_WIDTH, y_max: Decimal = Decimal("10")):
        self.width = width_pixels
        self.height = int(width_pixels * BASE_ASPECT_RATIO)
        scale = width_pixels / BASE_WIDTH
        self.plot_left = int(PLOT_LEFT * scale)
        self.plot_top = int(PLOT_TOP * scale)
        self.plot_right = int(PLOT_RIGHT * scale)
        self.plot_bottom = int(PLOT_BOTTOM * scale)
        self.y_min = Y_MIN
        self.y_max = y_max
        self.scale = scale


def round_up_to_nearest_ten(value: Decimal) -> Decimal:
    if value <= 0:
        return Decimal("0")
    return ((value + 9) // 10) * 10


def y_tick_step(y_max: Decimal) -> Decimal:
    target = max(y_max / Decimal("5"), Decimal("10"))
    return max(Decimal("10"), round_up_to_nearest_ten(target))


def _executable_names(app_name: str) -> tuple[str, ...]:
    if sys.platform.startswith("win"):
        return (f"{app_name}.exe", f"{app_name}.bat", f"{app_name}.cmd")
    return (app_name,)


def find_companion_app(app_name: str, explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if is_executable(path):
            return path
        raise FileNotFoundError(f"{app_name} executable was not found or is not executable: {path}")

    searched: list[Path] = []
    for candidate in iter_executable_candidates(app_name):
        searched.append(candidate)
        if is_executable(candidate):
            return candidate

    for executable_name in _executable_names(app_name):
        path_hit = shutil.which(executable_name)
        if path_hit:
            return Path(path_hit)

    details = "\n".join(f"  - {candidate}" for candidate in searched)
    raise FileNotFoundError(
        f"{app_name} executable was not found.\n\n"
        f"Searched:\n{details}\n\n"
        f"Install FedLeave from {FEDLEAVE_REPO_URL} or place the companion app next to this application."
    )


def get_default_data_dir() -> Path:
    if sys.platform.startswith("win"):
        local_appdata = os.getenv("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "fedleave"
        xdg_data_home = os.getenv("XDG_DATA_HOME")
        if xdg_data_home:
            return Path(xdg_data_home) / "fedleave"
        return Path.home() / "AppData" / "Local" / "fedleave"

    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "fedleave"

    home = os.getenv("HOME")
    if home:
        return Path(home) / ".local" / "share" / "fedleave"
    return Path.home() / ".local" / "share" / "fedleave"


def infer_leave_year(data_dir: Path) -> int:
    leave_year_dir = data_dir / "leave_years"
    year_files = sorted(leave_year_dir.glob("*.json"))
    if not year_files:
        raise SystemExit(
            f"No leave-year files found in {leave_year_dir}. "
            "Run `fedleave init` first or specify --data-dir PATH."
        )

    today = date.today()
    valid_years: list[int] = []
    for year_file in year_files:
        try:
            year = int(year_file.stem)
            leave_year = json.loads(year_file.read_text())
            valid_years.append(year)
        except (OSError, ValueError, json.JSONDecodeError):
            continue

        try:
            start = date.fromisoformat(str(leave_year["leave_year_start"]))
            end = date.fromisoformat(str(leave_year["leave_year_end"]))
        except (KeyError, ValueError):
            continue
        if start <= today <= end:
            return year

    if valid_years:
        return max(valid_years)

    raise SystemExit(
        f"No readable leave-year files found in {leave_year_dir}. "
        "Run `fedleave init` first or specify --data-dir PATH."
    )


def get_leave_year_data(year: int, data_dir: Path | None = None) -> dict[str, Any]:
    data_dir = data_dir or get_default_data_dir()
    args = ["balance", "--year", str(year), "--json", "--data-dir", str(data_dir)]
    run_fedleave(args)

    year_file = data_dir / "leave_years" / f"{year}.json"
    try:
        return json.loads(year_file.read_text())
    except FileNotFoundError as exc:
        raise SystemExit(f"Leave-year file not found: {year_file}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Failed to parse leave-year file as JSON: {exc}\nFile: {year_file}") from exc


def decimal_hours(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def format_hours(value: Decimal) -> str:
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f")


def pay_period_end_date(period_data: Any) -> date:
    if isinstance(period_data, dict):
        end_value = period_data.get("end_date") or period_data.get("end")
        if not end_value:
            raise SystemExit(f"Pay period is missing end_date: {period_data}")
        return date.fromisoformat(str(end_value))
    return period_data


def load_font(size: int, bold: bool = False, scale: float = 1.0) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    scaled_size = int(size * scale)
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), scaled_size)
    return ImageFont.load_default()


def category_balance_points(
    category: str,
    year: int,
    data_dir: Path | None = None,
) -> tuple[list[tuple[date, Decimal]], dict[str, Any], Decimal]:
    snapshot = get_leave_year_data(year, data_dir)
    starts = snapshot.get("starting_balances", {})
    running = decimal_hours(starts.get(category, 0))

    transactions = sorted(
        [
            tx
            for tx in snapshot.get("transactions", [])
            if not tx.get("void") and tx.get("category") == category
        ],
        key=lambda tx: (tx.get("date", ""), str(tx.get("id", ""))),
    )

    pay_periods = list(snapshot.get("pay_periods", []))
    if not pay_periods:
        start = date.fromisoformat(snapshot["leave_year_start"])
        end = date.fromisoformat(snapshot["leave_year_end"])
        for index in range(26):
            period_end = min(start + timedelta(days=index * 14 + 13), end)
            pay_periods.append({"end_date": period_end.isoformat()})

    tx_index = 0
    points: list[tuple[date, Decimal]] = []
    max_balance = running
    for period_data in pay_periods:
        period_end = pay_period_end_date(period_data)

        while tx_index < len(transactions) and date.fromisoformat(transactions[tx_index]["date"]) <= period_end:
            tx = transactions[tx_index]
            hours = decimal_hours(tx.get("hours"))
            direction = tx.get("direction")
            if direction in {"earned", "worked", "adjusted"}:
                running += hours
            elif direction in {"used", "expired", "forfeited"}:
                running -= hours
            tx_index += 1

        points.append((period_end, running))
        max_balance = max(max_balance, running)

    return points, snapshot, max_balance


def y_to_px(value: Decimal, dims: ChartDimensions) -> float:
    clamped = max(dims.y_min, min(dims.y_max, value))
    return float(dims.plot_bottom - ((clamped - dims.y_min) / (dims.y_max - dims.y_min)) * (dims.plot_bottom - dims.plot_top))


def x_positions(count: int, dims: ChartDimensions) -> list[float]:
    if count <= 1:
        return [(dims.plot_left + dims.plot_right) / 2]
    return [dims.plot_left + (dims.plot_right - dims.plot_left) * index / (count - 1) for index in range(count)]


def catmull_rom(points: list[tuple[float, float]], samples_per_segment: int = 18) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    smooth: list[tuple[float, float]] = []
    extended = [points[0], *points, points[-1]]
    for index in range(1, len(extended) - 2):
        p0 = np.array(extended[index - 1], dtype=float)
        p1 = np.array(extended[index], dtype=float)
        p2 = np.array(extended[index + 1], dtype=float)
        p3 = np.array(extended[index + 2], dtype=float)
        for step in range(samples_per_segment):
            t = step / samples_per_segment
            t2 = t * t
            t3 = t2 * t
            point = 0.5 * (
                (2 * p1)
                + (-p0 + p2) * t
                + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                + (-p0 + 3 * p1 - 3 * p2 + p3) * t3
            )
            smooth.append((float(point[0]), float(point[1])))
    smooth.append(points[-1])
    return smooth


def rotated_label(text: str, font: ImageFont.ImageFont) -> Image.Image:
    bbox = font.getbbox(text)
    width = bbox[2] - bbox[0] + 8
    height = bbox[3] - bbox[1] + 8
    label = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(label)
    draw.text((4 - bbox[0], 4 - bbox[1]), text, font=font, fill=TEXT)
    return label.rotate(90, expand=True)


def draw_diamond(draw: ImageDraw.ImageDraw, x: float, y: float, radius: int = 9) -> None:
    pts = [(x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y)]
    draw.polygon(pts, fill=BLUE, outline=BLUE)


def render_balance_chart(
    title: str,
    points: list[tuple[date, Decimal]],
    output: Path,
    dims: ChartDimensions,
    y_step: Decimal,
) -> None:
    image = Image.new("RGB", (dims.width, dims.height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    title_font = load_font(50, scale=dims.scale)
    tick_font = load_font(22, scale=dims.scale)
    x_font = load_font(21, scale=dims.scale)

    draw.rectangle((4, 6, dims.width - 5, dims.height - 10), outline=BORDER, width=2)

    title_box = draw.textbbox((0, 0), title, font=title_font)
    draw.text(
        ((dims.width - (title_box[2] - title_box[0])) / 2, 39),
        title,
        font=title_font,
        fill=TEXT,
    )

    draw.rectangle((dims.plot_left, dims.plot_top, dims.plot_right, dims.plot_bottom), outline=BORDER, width=2)

    y_labels = list(range(int(dims.y_min), int(dims.y_max) + 1, int(y_step)))
    if not y_labels:
        y_labels = [0]
    if y_labels[-1] != int(dims.y_max):
        y_labels.append(int(dims.y_max))
    for y_value in y_labels:
        y = round(y_to_px(Decimal(y_value), dims))
        draw.line((dims.plot_left, y, dims.plot_right, y), fill=GRID_MAJOR, width=2)
        label = str(y_value)
        box = draw.textbbox((0, 0), label, font=tick_font)
        draw.text(
            (dims.plot_left - 22 - (box[2] - box[0]), y - (box[3] - box[1]) / 2 - 2),
            label,
            font=tick_font,
            fill=TEXT,
        )

    xs = x_positions(len(points), dims)
    for x in xs:
        draw.line((round(x), dims.plot_top, round(x), dims.plot_bottom), fill=GRID_MINOR, width=2)

    raw_line = [(xs[index], y_to_px(value, dims)) for index, (_, value) in enumerate(points)]
    smooth = catmull_rom(raw_line)
    draw.line([(round(x), round(y)) for x, y in smooth], fill=BLUE, width=5, joint="curve")

    for x, y in raw_line:
        draw_diamond(draw, x, y, 9)

    for index, (period_end, _) in enumerate(points):
        rendered = rotated_label(period_end.isoformat(), x_font)
        x = round(xs[index] - rendered.width / 2)
        y = dims.plot_bottom + 16
        image.paste(rendered, (x, y), rendered)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")


def run_fedleave(args: list[str]) -> Any:
    try:
        fedleave = find_companion_app("fedleave")
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    result = subprocess.run([str(fedleave), *args], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
        raise SystemExit(f"fedleave command failed with exit code {result.returncode}:\n{detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Failed to parse fedleave output as JSON: {exc}\nOutput: {result.stdout}") from exc


def run_chart_app(spec: LeaveChartSpec) -> None:
    parser = argparse.ArgumentParser(description=f"Create {spec.title.lower()} balance chart PNG using fedleave data.")
    parser.add_argument("--year", type=int, help="Leave year. Defaults to current leave year.")
    parser.add_argument("--outputFile", required=True, help="Output PNG file path")
    parser.add_argument(
        "--resolution",
        type=int,
        default=BASE_WIDTH,
        help=f"Image width in pixels (default: {BASE_WIDTH}). Height is scaled maintaining aspect ratio.",
    )
    parser.add_argument("--data-dir", help="fedleave data directory (default: ~/.local/share/fedleave)")
    args = parser.parse_args()

    output_path = Path(args.outputFile).expanduser()
    if output_path.suffix.lower() != ".png":
        raise SystemExit(f"Error: Output file must have .png extension. Got: {output_path}")
    if args.resolution <= 0:
        raise SystemExit(f"Error: Resolution must be a positive number of pixels. Got: {args.resolution}")

    data_dir = Path(args.data_dir).expanduser() if args.data_dir else get_default_data_dir()
    if args.year is None:
        args.year = infer_leave_year(data_dir)

    try:
        points, snapshot, max_balance = category_balance_points(spec.category, args.year, data_dir)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    y_max = max(Decimal("10"), round_up_to_nearest_ten(max_balance))
    y_step = y_tick_step(y_max)
    output = output_path.resolve()
    dims = ChartDimensions(width_pixels=args.resolution, y_max=y_max)
    render_balance_chart(spec.title, points, output, dims, y_step)

    print(
        json.dumps(
            {
                "ok": True,
                "agent": f"{spec.title} Chart for the Year",
                "source_of_truth": "fedleave",
                "product": spec.product,
                "year": args.year,
                "leave_year_start": snapshot.get("leave_year_start"),
                "leave_year_end": snapshot.get("leave_year_end"),
                "point_count": len(points),
                "resolution_pixels": args.resolution,
                "image_dimensions": {"width": dims.width, "height": dims.height},
                "y_axis": {"min": int(dims.y_min), "max": int(dims.y_max)},
                "max_balance_hours": format_hours(max_balance),
                "output_png": str(output),
                "points": [
                    {"pay_period_end": day.isoformat(), spec.point_field: format_hours(value)}
                    for day, value in points
                ],
            },
            indent=2,
        )
    )
