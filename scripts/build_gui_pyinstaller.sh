#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV_DIR="$HERE/.pyinstaller-gui-venv"
DIST_DIR="$HERE/dist/fedleave-Ubuntu"
SKIP_BACKEND_BUILD=

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dist)
      DIST_DIR="$2"
      shift 2
      ;;
    --skip-backend-build)
      SKIP_BACKEND_BUILD=1
      shift
      ;;
    *)
      shift
      ;;
  esac
done

DIST_ROOT="$(dirname "$DIST_DIR")"

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install pyinstaller
python -m pip install -r "$HERE/requirements.txt"
python -m pip install -r "$HERE/requirements-gui.txt"

mkdir -p "$DIST_ROOT"
find "$DIST_ROOT" -maxdepth 1 -type f -delete
rm -rf "$DIST_ROOT/FedLeaveCalendar-Ubuntu" "$DIST_ROOT/FedLeaveCalendar-Windows"

if [[ -z "$SKIP_BACKEND_BUILD" ]]; then
  rm -rf "$DIST_DIR"
  "$HERE/scripts/build_pyinstaller_core.sh" --dist "$DIST_DIR"
else
  rm -f "$DIST_DIR/FedLeaveCalendar"
fi

ENTRY="$HERE/.pyinstaller_gui_entry.py"
cat > "$ENTRY" <<'PY'
from fedleave_gui.__main__ import main

if __name__ == '__main__':
    main()
PY

pyinstaller \
  --noconfirm \
  --onefile \
  --windowed \
  --name FedLeaveCalendar \
  --add-data "$HERE/help:help" \
  --hidden-import PySide6.QtCore \
  --hidden-import PySide6.QtGui \
  --hidden-import PySide6.QtWidgets \
  --hidden-import PySide6.QtPrintSupport \
  --distpath "$DIST_DIR" \
  --workpath "$HERE/.pyinstaller-build" \
  --specpath "$HERE/.pyinstaller-spec" \
  "$ENTRY"

echo "GUI build complete: $DIST_DIR"
echo "  - FedLeaveCalendar"
echo "  - fedleave (shared backend; not duplicated)"
