import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

from fedleave_gui.resources import asset_file, help_file, window_icon


def test_gui_resource_helpers_find_packaged_files():
    assert help_file("about-fedleave-calendar.html").is_file()
    assert asset_file("fedleave-logo.png").is_file()
    assert asset_file("fedleave-icon.ico").is_file()


def test_about_identifies_author_and_official_website_without_email():
    about = help_file("about-fedleave-calendar.html").read_text(encoding="utf-8")

    assert "Joshua Guthrie" in about
    assert "https://www.westmouthbay.com/fedleave-application/" in about
    assert "@" not in about


def test_gui_window_icon_loads_from_asset():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert app is not None
    assert window_icon().isNull() is False


def test_gui_resource_helpers_use_pyinstaller_meipass(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("fedleave_gui.resources.sys._MEIPASS", str(tmp_path), raising=False)
    (tmp_path / "assets").mkdir()
    (tmp_path / "help").mkdir()
    (tmp_path / "assets" / "fedleave-logo.png").write_bytes(b"logo")
    (tmp_path / "assets" / "fedleave-icon.ico").write_bytes(b"icon")
    (tmp_path / "help" / "about-fedleave-calendar.html").write_text("about", encoding="utf-8")

    assert help_file("about-fedleave-calendar.html") == tmp_path / "help" / "about-fedleave-calendar.html"
    assert asset_file("fedleave-logo.png") == tmp_path / "assets" / "fedleave-logo.png"
    assert asset_file("fedleave-icon.ico") == tmp_path / "assets" / "fedleave-icon.ico"
