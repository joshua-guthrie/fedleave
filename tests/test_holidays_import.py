from pathlib import Path

from fedleave.cli import holidays


def test_import_ics_creates_cache(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ics = tmp_path / "opm.ics"
    ics.write_text("""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:1@example.com
DTSTAMP:20260101T000000Z
DTSTART;VALUE=DATE:20260101
SUMMARY:New Year's Day
END:VEVENT
END:VCALENDAR
""")

    holidays(action="import-ics", year=2026, file=str(ics), data_dir=data_dir)
    cache = data_dir / "holiday_cache" / "federal_holidays_2026.json"
    assert cache.exists()
    data = __import__("json").loads(cache.read_text())
    assert isinstance(data.get("holidays"), list)
    names = [h.get("name") or h.get("short_name") for h in data.get("holidays", [])]
    assert any("New Year's Day" in (n or "") for n in names)
