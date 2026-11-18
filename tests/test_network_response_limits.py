import io

import pytest

from fedleave import holidays, update_check
from fedleave.config import init_config


class BudgetResponse(io.BytesIO):
    def __init__(self, body, limit):
        super().__init__(body)
        self.limit = limit

    def read(self, size=-1):
        assert 0 <= size <= self.limit + 1, "Network read must have a byte budget"
        return super().read(size)


@pytest.mark.parametrize("size", [31, 32, 33])
def test_calendar_download_bounds_actual_bytes_and_closes_response(monkeypatch, size):
    monkeypatch.setattr(holidays, "HOLIDAY_ICS_MAX_BYTES", 32, raising=False)
    response = BudgetResponse(b"x" * size, 32)
    monkeypatch.setattr(holidays.urllib.request, "urlopen", lambda *a, **k: response)
    if size > 32:
        with pytest.raises(ValueError, match="exceeds"):
            holidays.download_ics("https://example.com/calendar.ics")
    else:
        assert holidays.download_ics("https://example.com/calendar.ics") == b"x" * size
    assert response.closed


@pytest.mark.parametrize("extra", [4, 5, 6])
def test_update_metadata_enforces_limit_without_echoing_body(monkeypatch, extra):
    valid = b"source_commit=" + b"a" * 40 + b"\nversion=0.2.2\n"
    limit = len(valid) + 5
    monkeypatch.setattr(update_check, "UPDATE_METADATA_MAX_BYTES", limit, raising=False)
    response = BudgetResponse(valid + b"x" * extra, limit)
    result = update_check.check_for_updates(opener=lambda *a, **k: response)
    assert result["status"] == ("unavailable" if extra > 5 else "ok")
    assert response.closed


def test_oversized_calendar_commits_no_year_or_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(holidays, "HOLIDAY_ICS_MAX_BYTES", 32, raising=False)
    response = BudgetResponse(b"x" * 33, 32)
    monkeypatch.setattr(holidays.urllib.request, "urlopen", lambda *a, **k: response)
    with pytest.raises(ValueError, match="exceeds"):
        init_config(2026, "2026-01-11", 6, {}, data_dir=tmp_path, holiday_source="opm_ics")
    assert not (tmp_path / "config.json").exists()
    assert not (tmp_path / "leave_years").exists()
