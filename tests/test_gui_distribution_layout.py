from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scripts_root_contains_only_platform_entry_points():
    scripts = ROOT / "scripts"
    direct_files = sorted(p.name for p in scripts.iterdir() if p.is_file())
    assert direct_files == ["LinuxInstall.sh", "WindowsInstall.bat"]


def test_linux_entry_point_calls_installer_engine_from_repo_root():
    script = (ROOT / "scripts" / "LinuxInstall.sh").read_text(encoding="utf-8")

    assert "installer_engine.py" in script
    assert "--platform linux" in script
    assert "REPO_ROOT" in script
    assert "python3" in script


def test_windows_entry_point_avoids_powershell_and_calls_engine():
    script = (ROOT / "scripts" / "WindowsInstall.bat").read_text(encoding="utf-8")

    assert "powershell" not in script.lower()
    assert "installer_engine.py" in script
    assert "--platform windows" in script


def test_manifest_lists_all_project_scripts():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    manifest = (ROOT / "scripts" / "lib" / "common" / "application_manifest.toml").read_text(encoding="utf-8")

    expected_apps = [
        "fedleave",
        "FedLeaveCalendar",
        "FedLeaveAnalytics",
        "AnnualLeaveChartForTheYear",
        "SickLeaveChartForTheYear",
        "CreditHoursChartForTheYear",
        "CompTimeChartForTheYear",
        "TravelCompChartForTheYear",
        "TimeOffAwardChartForTheYear",
        "AnnualLeaveYearlyComparison",
        "SickLeaveYearlyComparison",
        "CreditHoursYearlyComparison",
        "CompTimeYearlyComparison",
        "TravelCompYearlyComparison",
        "TimeOffAwardYearlyComparison",
        "OvertimeYearlyComparison",
        "fedleaveMonthReportGraphic",
    ]

    for app in expected_apps:
        assert app in pyproject
        assert f"[{app}]" in manifest


def test_readme_documents_consolidated_installers():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "LinuxInstall.sh" in readme
    assert "WindowsInstall.bat" in readme
