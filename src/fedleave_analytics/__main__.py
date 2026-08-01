"""Launch analytics in package and frozen PyInstaller execution contexts."""

if __package__:
    from .app import main
else:
    # PyInstaller can execute this file as the frozen application's
    # top-level __main__ module, where relative imports have no package.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fedleave_analytics.app import main


if __name__ == "__main__":
    raise SystemExit(main())
