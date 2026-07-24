from __future__ import annotations

import re
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


EXPECTED_SCREENSHOTS = {
    "examples/fedleave-calendar-main-screen.png",
    "examples/fedleave-calendar-edit-leave.png",
    "examples/fedleave-calendar-preferences.png",
    "examples/fedleave-calendar-force-balance.png",
    "examples/fedleave-calendar-expiring-leave.png",
    "examples/fedleave-calendar-transactions.png",
    "examples/fedleave-analytics-main.png",
    "examples/fedleave-analytics-seasonality.png",
    "examples/fedleave-analytics-calendar-heatmap.png",
    "examples/fedleave-analytics-overtime-comp-credit.png",
    "examples/fedleave-analytics-supporting-transactions.png",
    "examples/annual-leave-chart-sample.png",
    "examples/sick-leave-chart-sample.png",
    "examples/credit-hours-chart-sample.png",
    "examples/comp-time-chart-sample.png",
    "examples/travel-comp-chart-sample.png",
    "examples/time-off-award-chart-sample.png",
    "examples/annual-leave-yearly-comparison-sample.png",
    "examples/sick-leave-yearly-comparison-sample.png",
    "examples/credit-hours-yearly-comparison-sample.png",
    "examples/comp-time-yearly-comparison-sample.png",
    "examples/travel-comp-yearly-comparison-sample.png",
    "examples/time-off-award-yearly-comparison-sample.png",
    "examples/overtime-yearly-comparison-sample.png",
    "examples/month-report-sample.png",
}


def test_readme_references_every_companion_and_popup_screenshot() -> None:
    text = README.read_text(encoding="utf-8")
    referenced = set(re.findall(r"!\[[^]]*]\((examples/[^)]+\.png)\)", text))

    assert EXPECTED_SCREENSHOTS <= referenced
    for relative_path in referenced:
        assert (ROOT / relative_path).is_file(), f"Missing README image: {relative_path}"


def test_readme_screenshots_are_high_resolution_png_files() -> None:
    for relative_path in EXPECTED_SCREENSHOTS:
        with Image.open(ROOT / relative_path) as image:
            assert image.format == "PNG"
            assert image.width >= 1200, f"{relative_path} is only {image.width}px wide"
            assert image.height >= 700, f"{relative_path} is only {image.height}px high"


def test_readme_identifies_fedleave_as_main_and_analytics_as_a_companion() -> None:
    text = README.read_text(encoding="utf-8")

    assert "The main application is `fedleave`" in text
    companion_section = text.split("## Companion Applications", 1)[1]
    assert "### Companion Application: FedLeaveAnalytics" in companion_section
    assert "Analysis > Analytics..." in companion_section
    for page in ("Summary", "Seasonality", "Calendar Heatmap", "Overtime, Comp, and Credit"):
        assert page in companion_section
