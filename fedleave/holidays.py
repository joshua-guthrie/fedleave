from __future__ import annotations

from datetime import datetime
from pathlib import Path

import holidays


def generate_federal_holidays(year: int, data_dir: Path) -> dict[str, object]:
    us_holidays = holidays.US(years=[year])
    entries = []
    for dt, name in sorted(us_holidays.items()):
        code = "H"
        actual_date = dt.isoformat()
        observed_date = actual_date
        entries.append(
            {
                "name": name,
                "actual_date": actual_date,
                "observed_date": observed_date,
                "display_date": observed_date,
                "code": code,
                "short_name": None,
                "source": "python_holidays",
                "manual_override": False,
            }
        )
    return {
        "schema_version": 1,
        "year": year,
        "source": "python_holidays",
        "generated_at": datetime.now().isoformat(),
        "holidays": entries,
    }
