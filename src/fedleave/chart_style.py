"""Shared visual constants and line rendering for FedLeave charts."""

from __future__ import annotations

from datetime import date
from math import hypot
from typing import Any

BASE_WIDTH = 1610
BASE_HEIGHT = 1180
BASE_ASPECT_RATIO = BASE_HEIGHT / BASE_WIDTH
PLOT_LEFT = 78
PLOT_TOP = 122
PLOT_RIGHT = 1580
PLOT_BOTTOM = 912

BLUE = "#4F81BD"
RED = "#C0504D"
GRID_MAJOR = "#8F8F8F"
GRID_MINOR = "#A9A9A9"
BORDER = "#808080"
TEXT = "#000000"
BACKGROUND = "#FFFFFF"


def _draw_dashed_polyline(
    draw: Any,
    points: list[tuple[float, float]],
    *,
    fill: str,
    width: int,
    dash_length: float = 18.0,
    gap_length: float = 12.0,
) -> None:
    drawing = True
    remaining = dash_length
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        segment_length = hypot(dx, dy)
        if segment_length <= 1e-9:
            continue
        position = 0.0
        while position < segment_length - 1e-9:
            step = min(remaining, segment_length - position)
            next_position = position + step
            if drawing:
                first = (
                    start[0] + dx * position / segment_length,
                    start[1] + dy * position / segment_length,
                )
                second = (
                    start[0] + dx * next_position / segment_length,
                    start[1] + dy * next_position / segment_length,
                )
                draw.line((first, second), fill=fill, width=width)
            position = next_position
            remaining -= step
            if remaining <= 1e-9:
                drawing = not drawing
                remaining = dash_length if drawing else gap_length


def draw_historical_and_future_line(
    draw: Any,
    points: list[tuple[date, float, float]],
    *,
    as_of: date,
    fill: str = BLUE,
    width: int = 5,
) -> None:
    """Draw dated points as a solid past/current line and dashed future line."""
    if len(points) < 2:
        return

    future_index = next(
        (index for index, (point_date, _x, _y) in enumerate(points) if point_date > as_of),
        len(points),
    )
    historical = [(x, y) for _point_date, x, y in points[:future_index]]
    if len(historical) >= 2:
        draw.line(historical, fill=fill, width=width)

    if future_index < len(points):
        future = [(x, y) for _point_date, x, y in points[future_index:]]
        if future_index > 0:
            _point_date, x, y = points[future_index - 1]
            future.insert(0, (x, y))
        _draw_dashed_polyline(draw, future, fill=fill, width=width)
