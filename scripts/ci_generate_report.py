#!/usr/bin/env python3
from pathlib import Path
import base64
import sys

from fedleave.config import init_config
from fedleave.ledger import create_transaction, add_transaction_to_leave_year
from fedleave.storage import write_json
from fedleave.reports import generate as generate_report


def main():
    work = Path(".")
    data_dir = work / ".ci_data"
    if data_dir.exists():
        # reuse
        pass

    # Initialize minimal config and leave year
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={"annual": 10.0},
        data_dir=data_dir,
    )

    year_file = data_dir / "leave_years" / "2026.json"
    ly = None
    try:
        import json
        ly = json.loads(year_file.read_text())
    except Exception:
        print("Failed to read leave year", file=sys.stderr)
        sys.exit(2)

    tx = create_transaction(date="2026-06-01", category="annual", direction="used", hours=4.0, existing_ids=[])
    add_transaction_to_leave_year(ly, tx)
    write_json(year_file, ly)

    reports_dir = work / "reports"
    reports_dir.mkdir(exist_ok=True)

    # tiny transparent PNG
    png_b64 = b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQMAAAAl21bKAAAAA1BMVEUAAACnej3aAAAAAXRSTlMAQObYZgAAAApJREFUCNdjYAAAAAIAAeIhvDMAAAAASUVORK5CYII="
    chart_path = reports_dir / "ci_chart.png"
    chart_path.write_bytes(base64.b64decode(png_b64))

    out_odt = reports_dir / "fedleave_report.odt"
    generate_report(year=2026, data_dir=data_dir, chart=str(chart_path), output=str(out_odt))

    if not out_odt.exists():
        print("Report generation failed", file=sys.stderr)
        sys.exit(1)

    print("Generated report:", out_odt)


if __name__ == "__main__":
    main()
