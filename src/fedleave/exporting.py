"""Guarded, private staging for user-requested report exports."""

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from .config import get_default_data_dir


@contextmanager
def export_file(path: Path | str, data_dir: Path | str | None = None, *, overwrite: bool = True):
    """Publish a new inode without following a destination or staging link."""
    if os.name == "nt":
        # Earlier Windows Python releases ignore mkdtemp's private mode.
        version = sys.version_info
        if version < (3, 11, 10) or (3, 12) <= version < (3, 12, 4):
            raise OSError("Secure exports require Python 3.11.10, 3.12.4, or a newer maintained release on Windows.")
    path = Path(path).expanduser()
    destination = path.parent.resolve() / path.name
    store = Path(data_dir).expanduser().resolve() if data_dir else get_default_data_dir().resolve()
    if destination.is_relative_to(store) or destination.resolve().is_relative_to(store):
        raise ValueError("Choose an export location outside the selected leave datastore.")
    if destination.is_symlink():
        raise ValueError("Choose an export filename that is not a symbolic link.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # External renderers accept filenames. A private directory protects their
    # staging files from pre-planted links and other users in a shared folder.
    with TemporaryDirectory(prefix=".fedleave-export-", dir=destination.parent) as workspace:
        with NamedTemporaryFile(dir=workspace, suffix=destination.suffix, delete=False) as handle:
            temporary = Path(handle.name)
        yield temporary
        if temporary.is_symlink():
            raise ValueError("Export renderer replaced its staging file with a symbolic link.")
        temporary.chmod(0o600)
        if overwrite:
            temporary.replace(destination)
        elif os.name == "nt":
            # Windows rename fails if the destination already exists.
            temporary.rename(destination)
        else:
            # Atomic create-only publication; a concurrent creator wins safely.
            os.link(temporary, destination)


def write_export_text(path: Path | str, text: str, data_dir: Path | str | None = None) -> None:
    with export_file(path, data_dir) as temporary:
        temporary.write_text(text, encoding="utf-8", newline="")


def render_print_job(printer, render, data_dir=None, *, export_target=None) -> None:
    """Apply export protections when a print dialog selects a file destination."""
    output = printer.outputFileName()
    if not output:
        render(printer)
        return
    with export_target(output) if export_target else export_file(output, data_dir) as destination:
        printer.setOutputFileName(str(destination))
        try:
            render(printer)
        finally:
            # Renderers end their painter before returning, closing the document.
            # Restore the selection for preview dialogs that emit more than once.
            printer.setOutputFileName(output)
