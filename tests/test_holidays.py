from pathlib import Path
import tempfile

from fedleave.holidays import generate_federal_holidays


def test_generate_federal_holidays(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    result = generate_federal_holidays(2026, data_dir)

    assert result["year"] == 2026
    assert result["source"] == "python_holidays"
    assert isinstance(result["holidays"], list)
    assert any(h["name"] == "New Year's Day" for h in result["holidays"])
