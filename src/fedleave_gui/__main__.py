"""Launch the calendar GUI as a Python module."""

from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
