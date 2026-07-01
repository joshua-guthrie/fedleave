#!/usr/bin/env python3
"""Sick Leave Chart for the Year - Generates PNG leave balance charts using fedleave data."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


# Chart rendering constants (base dimensions)
BASE_WIDTH = 1610
BASE_HEIGHT = 1180
BASE_ASPECT_RATIO = BASE_HEIGHT / BASE_WIDTH
PLOT_LEFT = 78
PLOT_TOP = 122
PLOT_RIGHT = 1580
PLOT_BOTTOM = 912
Y_MIN = Decimal("0")

BLUE = "#4F81BD"
GRID_MAJOR = "#8F8F8F"
GRID_MINOR = "#A9A9A9"
BORDER = "#808080"
TEXT = "#000000"
BACKGROUND = "#FFFFFF"

# GitHub URL for fedleave
FEDLEAVE_REPO_URL = "https://github.com/joshua-guthrie/fedleave"


class ChartDimensions:
    """Chart dimensions scaled to specific pixel width."""
    
    def __init__(self, width_pixels: int = BASE_WIDTH):
        """
        Initialize chart dimensions based on target width in pixels.
        Height is calculated maintaining aspect ratio.
        
        Args:
            width_pixels: Target image width in pixels (default: 1610)
        """
        self.width = width_pixels
        self.height = int(width_pixels * BASE_ASPECT_RATIO)
        scale = width_pixels / BASE_WIDTH
        self.plot_left = int(PLOT_LEFT * scale)
        self.plot_top = int(PLOT_TOP * scale)
        self.plot_right = int(PLOT_RIGHT * scale)
        self.plot_bottom = int(PLOT_BOTTOM * scale)
        self.y_min = Y_MIN
        self.scale = scale


def find_fedleave_app() -> Path:
    """
    Find the fedleave application in the same directory as the chart executable or in PATH.
    
    Returns:
        Path to fedleave executable
        
    Raises:
        SystemExit: If fedleave cannot be found with helpful error message
    """
    def _is_executable(candidate: Path) -> bool:
        if not candidate.is_file():
            return False
        return os.access(candidate, os.X_OK) or candidate.suffix.lower() in {".exe", ".bat", ".cmd"}

    script_dir = Path(__file__).resolve().parent.parent
    candidate_dirs: list[Path] = []

    argv0 = Path(sys.argv[0]).expanduser()
    if not argv0.is_absolute():
        argv0 = (Path.cwd() / argv0).resolve()
    else:
        argv0 = argv0.resolve()
    if argv0.exists():
        candidate_dirs.append(argv0 if argv0.is_dir() else argv0.parent)

    executable_path = Path(sys.executable).expanduser()
    if not executable_path.is_absolute():
        executable_path = (Path.cwd() / executable_path).resolve()
    else:
        executable_path = executable_path.resolve()
    if executable_path.exists():
        candidate_dirs.append(executable_path.parent)

    candidate_dirs.extend([script_dir, script_dir / "dist", script_dir / "fedleave", script_dir.parent / "dist"])

    seen_dirs: set[Path] = set()
    for base_dir in candidate_dirs:
        resolved_dir = base_dir.resolve() if base_dir.exists() else base_dir
        if resolved_dir in seen_dirs:
            continue
        seen_dirs.add(resolved_dir)
        for candidate_name in ("fedleave", "fedleave.exe"):
            candidate = resolved_dir / candidate_name
            if _is_executable(candidate):
                return candidate

    fedleave_in_path = shutil.which("fedleave")
    if fedleave_in_path:
        return Path(fedleave_in_path)

    raise SystemExit(
        f"""
        
Error: fedleave application not found.

The SickLeaveChartForTheYear application requires fedleave to be installed.

To install fedleave, visit: {FEDLEAVE_REPO_URL}

Or if you downloaded both applications together, ensure they are in the same directory:
  - fedleave (or fedleave.exe on Windows)
  - SickLeaveChartForTheYear (or SickLeaveChartForTheYear.exe on Windows)
        
"""
    )


def run_fedleave(args: list[str]) -> Any:
    """
    Run fedleave command and return parsed JSON output.
    
    Args:
        args: Command line arguments to pass to fedleave
        
    Returns:
        Parsed JSON output from fedleave --json
        
    Raises:
        SystemExit: If fedleave command fails
    """
    fedleave = find_fedleave_app()
    result = subprocess.run(
        [str(fedleave), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
        raise SystemExit(
            f"fedleave command failed with exit code {result.returncode}:\n{detail}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Failed to parse fedleave output as JSON: {e}\nOutput: {result.stdout}")


def get_default_data_dir() -> Path:
    """Return the same platform-specific default data directory used by fedleave."""
    if sys.platform.startswith("win") or os.name == "nt":
        local_appdata = os.getenv("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "fedleave"
        return Path.home() / "AppData" / "Local" / "fedleave"

    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "fedleave"

    return Path.home() / ".local" / "share" / "fedleave"


def infer_leave_year(data_dir: Path) -> int:
    """Infer the current leave year from the data directory."""
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
    """
    Get leave year snapshot data using fedleave.
    
    Args:
        year: Leave year number
        data_dir: Optional data directory path
        
    Returns:
        Dictionary with leave_year_start, leave_year_end, transactions, starting_balances, etc.
    """
    data_dir = data_dir or get_default_data_dir()

    # Let fedleave validate the year and post any automatic accruals before reading the ledger.
    args = ["balance", "--year", str(year), "--json", "--project"]
    args.extend(["--data-dir", str(data_dir)])
    run_fedleave(args)

    year_file = data_dir / "leave_years" / f"{year}.json"
    try:
        return json.loads(year_file.read_text())
    except FileNotFoundError:
        raise SystemExit(f"Leave-year file not found: {year_file}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"Failed to parse leave-year file as JSON: {e}\nFile: {year_file}")


def decimal_hours(value: Any) -> Decimal:
    """Convert value to Decimal hours."""
    return Decimal(str(value or "0"))


def format_hours(value: Decimal) -> str:
    """Format Decimal hours for display."""
    if value == value.to_integral():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f")


def pay_period_end_date(period_data: Any) -> date:
    """Return a pay period's end date from supported fedleave schemas."""
    if isinstance(period_data, dict):
        end_value = period_data.get("end_date") or period_data.get("end")
        if not end_value:
            raise SystemExit(f"Pay period is missing end_date: {period_data}")
        return date.fromisoformat(str(end_value))
    return period_data


def load_font(size: int, bold: bool = False, scale: float = 1.0) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load TrueType font or fall back to default."""
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


def sick_leave_balance_points(year: int, data_dir: Path | None = None) -> tuple[list[tuple[date, Decimal]], dict[str, Any], Decimal]:
    """
    Get sick leave balance points for each pay period.
    
    Args:
        year: Leave year number
        data_dir: Optional data directory path
        
    Returns:
        Tuple of (points list, snapshot dict, max_balance)
    """
    snapshot = get_leave_year_data(year, data_dir)
    
    starts = snapshot.get("starting_balances", {})
    running = decimal_hours(starts.get("sick", 0))
    
    # Get all sick leave transactions, sorted by date and ID
    txs = sorted(
        [
            tx
            for tx in snapshot.get("transactions", [])
            if not tx.get("void") and tx.get("category") == "sick"
        ],
        key=lambda tx: (tx.get("date", ""), str(tx.get("id", ""))),
    )
    
    # Get pay period end dates
    pay_periods = snapshot.get("pay_periods", [])
    if not pay_periods:
        # Fallback: generate standard 26 pay periods
        start = date.fromisoformat(snapshot["leave_year_start"])
        end = date.fromisoformat(snapshot["leave_year_end"])
        for index in range(26):
            period_end = min(start + timedelta(days=index * 14 + 13), end)
            pay_periods.append({"end_date": period_end.isoformat()})
    
    # Calculate balance at each pay period end
    tx_index = 0
    points: list[tuple[date, Decimal]] = []
    max_balance = running
    
    for period_data in pay_periods:
        period_end = pay_period_end_date(period_data)
        
        while tx_index < len(txs) and date.fromisoformat(txs[tx_index]["date"]) <= period_end:
            tx = txs[tx_index]
            hours = decimal_hours(tx.get("hours"))
            direction = tx.get("direction")
            if direction in {"earned", "worked", "adjusted"}:
                running += hours
            elif direction == "used":
                running -= hours
            tx_index += 1
        
        points.append((period_end, running))
        max_balance = max(max_balance, running)
    
    return points, snapshot, max_balance


def round_up_to_hundred(value: Decimal) -> Decimal:
    """Round value up to the next hundred."""
    return ((value + 99) // 100) * 100


def y_to_px(value: Decimal, dims: ChartDimensions, y_max: Decimal) -> float:
    """Convert Y-axis value to pixel coordinate."""
    clamped = max(dims.y_min, min(y_max, value))
    return float(dims.plot_bottom - ((clamped - dims.y_min) / (y_max - dims.y_min)) * (dims.plot_bottom - dims.plot_top))


def x_positions(count: int, dims: ChartDimensions) -> list[float]:
    """Get X-axis pixel positions for data points."""
    if count <= 1:
        return [(dims.plot_left + dims.plot_right) / 2]
    return [
        dims.plot_left + (dims.plot_right - dims.plot_left) * index / (count - 1) for index in range(count)
    ]


def catmull_rom(
    points: list[tuple[float, float]], samples_per_segment: int = 18
) -> list[tuple[float, float]]:
    """
    Interpolate points using Catmull-Rom spline for smooth curve.
    
    Args:
        points: List of (x, y) tuples
        samples_per_segment: Number of interpolated points per segment
        
    Returns:
        List of interpolated (x, y) tuples
    """
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
    """Create a rotated text label."""
    bbox = font.getbbox(text)
    width = bbox[2] - bbox[0] + 8
    height = bbox[3] - bbox[1] + 8
    label = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(label)
    draw.text((4 - bbox[0], 4 - bbox[1]), text, font=font, fill=TEXT)
    return label.rotate(90, expand=True)


def draw_diamond(draw: ImageDraw.ImageDraw, x: float, y: float, radius: int = 9) -> None:
    """Draw a diamond marker at (x, y)."""
    pts = [(x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y)]
    draw.polygon(pts, fill=BLUE, outline=BLUE)


def render(points: list[tuple[date, Decimal]], output: Path, dims: ChartDimensions, y_max: Decimal) -> None:
    """
    Render sick leave balance chart to PNG file.
    
    Args:
        points: List of (pay_period_end_date, sick_balance_hours) tuples
        output: Output PNG file path
        dims: Chart dimensions object with scaling
        y_max: Maximum Y-axis value
    """
    image = Image.new("RGB", (dims.width, dims.height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    title_font = load_font(50, scale=dims.scale)
    tick_font = load_font(22, scale=dims.scale)
    x_font = load_font(21, scale=dims.scale)

    # Border
    draw.rectangle((4, 6, dims.width - 5, dims.height - 10), outline=BORDER, width=2)
    
    # Title
    title = "Sick Leave"
    title_box = draw.textbbox((0, 0), title, font=title_font)
    draw.text(
        ((dims.width - (title_box[2] - title_box[0])) / 2, 39),
        title,
        font=title_font,
        fill=TEXT,
    )

    # Plot area border
    draw.rectangle((dims.plot_left, dims.plot_top, dims.plot_right, dims.plot_bottom), outline=BORDER, width=2)

    # Y-axis grid and labels - dynamic based on y_max
    y_step = max(Decimal("50"), ((y_max - dims.y_min) // 5))  # Target ~5 major grid lines
    y_value = dims.y_min
    while y_value <= y_max:
        y = round(y_to_px(y_value, dims, y_max))
        draw.line((dims.plot_left, y, dims.plot_right, y), fill=GRID_MAJOR, width=2)
        label = str(int(y_value))
        box = draw.textbbox((0, 0), label, font=tick_font)
        draw.text(
            (dims.plot_left - 22 - (box[2] - box[0]), y - (box[3] - box[1]) / 2 - 2),
            label,
            font=tick_font,
            fill=TEXT,
        )
        y_value += y_step

    # X-axis grid
    xs = x_positions(len(points), dims)
    for x in xs:
        draw.line((round(x), dims.plot_top, round(x), dims.plot_bottom), fill=GRID_MINOR, width=2)

    # Plot data line
    raw_line = [(xs[index], y_to_px(value, dims, y_max)) for index, (_, value) in enumerate(points)]
    smooth = catmull_rom(raw_line)
    draw.line(
        [(round(x), round(y)) for x, y in smooth], fill=BLUE, width=5, joint="curve"
    )
    
    # Plot data points
    for x, y in raw_line:
        draw_diamond(draw, x, y, 9)

    # X-axis labels
    for index, (period_end, _) in enumerate(points):
        label = period_end.isoformat()
        rendered = rotated_label(label, x_font)
        x = round(xs[index] - rendered.width / 2)
        y = dims.plot_bottom + 16
        image.paste(rendered, (x, y), rendered)

    # Save
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Create sick leave balance chart PNG using fedleave data."
    )
    parser.add_argument(
        "--year", type=int, help="Leave year. Defaults to current leave year."
    )
    parser.add_argument("--outputFile", required=True, help="Output PNG file path")
    parser.add_argument(
        "--resolution",
        type=int,
        default=BASE_WIDTH,
        help=f"Image width in pixels (default: {BASE_WIDTH}). Height is scaled maintaining aspect ratio.",
    )
    parser.add_argument(
        "--data-dir", help="fedleave data directory (default: ~/.local/share/fedleave)"
    )
    args = parser.parse_args()

    # Validate output file is PNG
    output_path = Path(args.outputFile).expanduser()
    if not output_path.suffix.lower() == ".png":
        raise SystemExit(
            f"Error: Output file must have .png extension. Got: {output_path}"
        )

    # Validate resolution is positive
    if args.resolution <= 0:
        raise SystemExit(
            f"Error: Resolution must be a positive number of pixels. Got: {args.resolution}"
        )

    data_dir = Path(args.data_dir).expanduser() if args.data_dir else get_default_data_dir()

    # If year not provided, try to determine current year
    if args.year is None:
        args.year = infer_leave_year(data_dir)

    points, snapshot, max_balance = sick_leave_balance_points(args.year, data_dir)
    output = output_path.resolve()
    dims = ChartDimensions(width_pixels=args.resolution)
    
    # Round up max to next hundred for Y-axis
    y_max = round_up_to_hundred(max_balance)
    render(points, output, dims, y_max)
    
    print(
        json.dumps(
            {
                "ok": True,
                "agent": "Sick Leave Chart for the Year",
                "source_of_truth": "fedleave",
                "product": "sick-leave-chart-png",
                "year": args.year,
                "leave_year_start": snapshot.get("leave_year_start"),
                "leave_year_end": snapshot.get("leave_year_end"),
                "point_count": len(points),
                "resolution_pixels": args.resolution,
                "image_dimensions": {
                    "width": dims.width,
                    "height": dims.height,
                },
                "y_axis": {"min": int(Y_MIN), "max": int(y_max)},
                "max_sick_leave_balance": format_hours(max_balance),
                "output_png": str(output),
                "points": [
                    {
                        "pay_period_end": day.isoformat(),
                        "sick_balance_hours": format_hours(value),
                    }
                    for day, value in points
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
