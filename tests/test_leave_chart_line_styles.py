from datetime import date

from fedleave.chart_style import BLUE, draw_historical_and_future_line


class RecordingDraw:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, int]] = []

    def line(self, points, *, fill, width) -> None:
        self.calls.append((points, fill, width))


def test_leave_chart_line_is_solid_through_today_and_dashed_after_today():
    draw = RecordingDraw()
    points = [
        (date(2026, 7, 1), 0.0, 10.0),
        (date(2026, 7, 21), 30.0, 20.0),
        (date(2026, 8, 1), 60.0, 5.0),
        (date(2026, 8, 15), 100.0, 25.0),
    ]

    draw_historical_and_future_line(draw, points, as_of=date(2026, 7, 21), fill=BLUE, width=5)

    assert draw.calls[0] == ([(0.0, 10.0), (30.0, 20.0)], BLUE, 5)
    dashed_calls = draw.calls[1:]
    assert len(dashed_calls) >= 2
    assert all(len(segment) == 2 for segment, _fill, _width in dashed_calls)
    assert all(fill == BLUE and width == 5 for _segment, fill, width in dashed_calls)


def test_leave_chart_line_is_one_straight_solid_polyline_when_all_data_is_current_or_past():
    draw = RecordingDraw()
    points = [
        (date(2026, 6, 1), 0.0, 10.0),
        (date(2026, 7, 1), 30.0, 20.0),
        (date(2026, 7, 21), 60.0, 5.0),
    ]

    draw_historical_and_future_line(draw, points, as_of=date(2026, 7, 21), fill=BLUE, width=5)

    assert draw.calls == [([(0.0, 10.0), (30.0, 20.0), (60.0, 5.0)], BLUE, 5)]


def test_leave_chart_line_is_entirely_dashed_when_all_data_is_future():
    draw = RecordingDraw()
    points = [
        (date(2026, 8, 1), 0.0, 10.0),
        (date(2026, 8, 15), 100.0, 20.0),
    ]

    draw_historical_and_future_line(draw, points, as_of=date(2026, 7, 21), fill=BLUE, width=5)

    assert len(draw.calls) >= 2
    assert all(len(segment) == 2 for segment, _fill, _width in draw.calls)
