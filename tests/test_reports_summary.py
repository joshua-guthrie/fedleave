from pathlib import Path
import json
import base64

from fedleave.reports import generate as generate_report
from fedleave.ledger import create_transaction, add_transaction_to_leave_year
from fedleave.storage import write_json
from fedleave.config import init_config


def test_report_summary_includes_balances(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={"annual": 10.0},
        data_dir=data_dir,
    )

    year_file = data_dir / "leave_years" / "2026.json"
    ly = json.loads(year_file.read_text())

    tx1 = create_transaction(date="2026-06-01", category="annual", direction="used", hours=4.0, existing_ids=[])
    tx2 = create_transaction(date="2026-06-02", category="sick", direction="earned", hours=2.5, existing_ids=[tx1.id])
    add_transaction_to_leave_year(ly, tx1)
    add_transaction_to_leave_year(ly, tx2)
    write_json(year_file, ly)

    # write a tiny PNG to use as chart
    png_b64 = b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQMAAAAl21bKAAAAA1BMVEUAAACnej3aAAAAAXRSTlMAQObYZgAAAApJREFUCNdjYAAAAAIAAeIhvDMAAAAASUVORK5CYII="
    chart_path = tmp_path / "chart.png"
    chart_path.write_bytes(base64.b64decode(png_b64))

    out_odt = tmp_path / "report.odt"
    generate_report(year=2026, data_dir=data_dir, chart=str(chart_path), output=str(out_odt))

    assert out_odt.exists()

    # inspect the content.xml inside the ODT
    import zipfile
    with zipfile.ZipFile(out_odt, "r") as zf:
        with zf.open("content.xml") as cf:
            content = cf.read().decode("utf-8")
    # Expect category labels and numeric totals
    assert "Annual" in content
    assert "Sick" in content
    # the annual balance should reflect starting 10 - used 4 = 6.00
    assert "6.00" in content