from pathlib import Path
from types import SimpleNamespace

from fedleave_gui.backend import BackendError
from fedleave_gui.main_window import MainWindow, QMessageBox


class _WorkingBackend:
    def version(self) -> str:
        return "fedleave 0.2.0"

    def executable_path(self) -> Path:
        return Path("/opt/fedleave/fedleave")


class _FailingBackend:
    def version(self) -> str:
        raise BackendError("version command failed")


def test_about_backend_displays_version_and_executable(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda parent, title, text: captured.update(title=title, text=text),
    )
    window = SimpleNamespace(backend=_WorkingBackend())

    MainWindow.about_backend(window)

    assert captured == {
        "title": "About fedleave Backend",
        "text": f"fedleave 0.2.0\n\nExecutable: {Path('/opt/fedleave/fedleave')}",
    }


def test_about_backend_displays_backend_error(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, text: captured.update(title=title, text=text),
    )
    window = SimpleNamespace(backend=_FailingBackend())

    MainWindow.about_backend(window)

    assert captured["title"] == "About fedleave Backend"
    assert "version command failed" in captured["text"]
