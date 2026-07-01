#!/usr/bin/env bash
set -euo pipefail

# Build a standalone `fedleave` executable using PyInstaller.
# Usage: ./scripts/build_pyinstaller.sh [--onefile] [--dist dist]

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV_DIR="$HERE/.pyinstaller-venv"
DIST_DIR="$HERE/dist"
ONEFILE=--onefile

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-onefile)
      ONEFILE=
      shift
      ;;
    --dist)
      DIST_DIR="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

echo "Building fedleave with PyInstaller (venv: $VENV_DIR)"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install pyinstaller

# Install runtime dependencies used by the package and the build itself.
python -m pip install -r "$HERE/requirements.txt"

# create a tiny entry script PyInstaller can use
ENTRY="$HERE/.pyinstaller_entry.py"
cat > "$ENTRY" <<'PY'
from fedleave.__main__ import main

if __name__ == '__main__':
    main()
PY

pyinstaller $ONEFILE \
  --name fedleave \
  --console \
  --hidden-import holidays \
  --hidden-import icalendar \
  --distpath "$DIST_DIR" \
  --workpath "$HERE/.pyinstaller-build" \
  --specpath "$HERE/.pyinstaller-spec" \
  -F "$ENTRY"

# Build AnnualLeaveChartForTheYear companion application
CHART_ENTRY="$HERE/.pyinstaller_chart_entry.py"
cat > "$CHART_ENTRY" <<'PY'
from annual_leave_chart.__main__ import main

if __name__ == '__main__':
    main()
PY

pyinstaller $ONEFILE \
  --name AnnualLeaveChartForTheYear \
  --console \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageDraw \
  --hidden-import PIL.ImageFont \
  --hidden-import numpy \
  --distpath "$DIST_DIR" \
  --workpath "$HERE/.pyinstaller-build" \
  --specpath "$HERE/.pyinstaller-spec" \
  -F "$CHART_ENTRY"

# Build SickLeaveChartForTheYear companion application
SICK_CHART_ENTRY="$HERE/.pyinstaller_sick_chart_entry.py"
cat > "$SICK_CHART_ENTRY" <<'PY'
from sick_leave_chart.__main__ import main

if __name__ == '__main__':
    main()
PY

pyinstaller $ONEFILE \
  --name SickLeaveChartForTheYear \
  --console \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageDraw \
  --hidden-import PIL.ImageFont \
  --hidden-import numpy \
  --distpath "$DIST_DIR" \
  --workpath "$HERE/.pyinstaller-build" \
  --specpath "$HERE/.pyinstaller-spec" \
  -F "$SICK_CHART_ENTRY"

echo "Build complete. Binaries in $DIST_DIR"
echo "  - fedleave"
echo "  - AnnualLeaveChartForTheYear"
echo "  - SickLeaveChartForTheYear"
