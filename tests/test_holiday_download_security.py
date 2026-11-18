import io
import json

import pytest
from typer.testing import CliRunner

from fedleave.cli import app
from fedleave.config import init_config
from fedleave.holidays import download_ics, generate_opm_holidays
from fedleave.mcp.catalog import discover
from fedleave.mcp.execution import Executor
from fedleave.mcp.policy import Policy
from test_mcp_execution import call

CALENDAR = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20260704\r\nSUMMARY:Holiday\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"


@pytest.mark.parametrize(
    "url",
    [
        "file:///private.ics",
        "data:text/plain,secret",
        "ftp://example.com/a",
        "relative.ics",
        "http:///a",
        "https://:443/a",
        "https://example.com/\x00",
        "https://example.com/" + "x" * 2048,
    ],
)
def test_invalid_download_urls_never_open_a_resource(monkeypatch, url):
    opened = []

    def opener(*args, **kwargs):
        opened.append(args)
        return io.BytesIO(CALENDAR)

    monkeypatch.setattr("fedleave.holidays.urllib.request.urlopen", opener)
    with pytest.raises(ValueError):
        download_ics(url)
    assert opened == []


def test_valid_url_is_normalized_at_download_and_initialization(monkeypatch, tmp_path):
    opened = []

    def opener(url, **kwargs):
        opened.append(url)
        return io.BytesIO(CALENDAR)

    monkeypatch.setattr("fedleave.holidays.urllib.request.urlopen", opener)
    init_config(
        2026,
        "2026-01-11",
        6,
        {},
        data_dir=tmp_path,
        holiday_source="opm_ics",
        holiday_ics_url=" https://example.com/a.ics ",
    )
    assert opened == ["https://example.com/a.ics"]
    assert json.loads((tmp_path / "config.json").read_text())["holidays"]["ics_url"] == opened[0]


@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize(
    "body", [b"SYNTHETIC_PRIVATE_MARKER", CALENDAR.replace(b"DTSTART;VALUE=DATE:20260704\r\n", b"")]
)
def test_calendar_parse_errors_are_controlled_without_source_contents(monkeypatch, tmp_path, body, json_output):
    monkeypatch.setattr("fedleave.holidays.urllib.request.urlopen", lambda *a, **k: io.BytesIO(body))
    result = CliRunner().invoke(
        app,
        [
            "init",
            "--year",
            "2026",
            "--leave-year-start",
            "2026-01-11",
            "--holiday-source",
            "opm_ics",
            "--holiday-ics-url",
            "https://example.com/a",
            "--data-dir",
            str(tmp_path),
            *(["--json"] if json_output else []),
        ],
    )
    assert result.exit_code != 0
    assert "Invalid holiday calendar data" in result.output
    assert "SYNTHETIC_PRIVATE_MARKER" not in result.output
    assert not (tmp_path / "leave_years" / "2026.json").exists()


@pytest.mark.parametrize(
    "body", [b"SYNTHETIC_PRIVATE_MARKER", CALENDAR.replace(b"Holiday", b"SYNTHETIC_PRIVATE_MARKER")]
)
def test_restricted_mcp_network_permission_cannot_read_local_files(tmp_path, body):
    private = tmp_path / "private.ics"
    private.write_bytes(body)
    base = tmp_path / "store"
    executor = Executor(discover(), Policy(mode="unattended", data_dir=base, allow_network=True))
    result = call(
        executor,
        "init",
        {
            "year": 2026,
            "leave_year_start": "2026-01-11",
            "holiday_source": "opm_ics",
            "holiday_ics_url": private.as_uri(),
        },
    )
    assert not result["ok"]
    assert "SYNTHETIC_PRIVATE_MARKER" not in json.dumps(result)
    assert private.read_bytes() == body
    assert not (base / "leave_years" / "2026.json").exists()
    assert not (base / "holiday_cache" / "federal_holidays_2026.json").exists()


def test_invalid_unused_url_retains_offline_initialization(tmp_path):
    init_config(2026, "2026-01-11", 6, {}, data_dir=tmp_path, holiday_ics_url="file:///unused")
    assert (tmp_path / "leave_years" / "2026.json").exists()


def test_invalid_remote_calendar_helper_hides_parser_input(monkeypatch):
    monkeypatch.setattr(
        "fedleave.holidays.urllib.request.urlopen", lambda *a, **k: io.BytesIO(b"SYNTHETIC_PRIVATE_MARKER")
    )
    with pytest.raises(ValueError, match="^Invalid holiday calendar data$"):
        generate_opm_holidays(2026, "https://example.com/a.ics")
