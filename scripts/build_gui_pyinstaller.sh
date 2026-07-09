#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV_DIR="$HERE/.pyinstaller-gui-venv"
DIST_ROOT="$HERE/dist"
APP_DIST="$DIST_ROOT/FedLeaveCalendar-Ubuntu"

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install pyinstaller
python -m pip install -r "$HERE/requirements.txt"
python -m pip install -r "$HERE/requirements-gui.txt"

"$HERE/scripts/build_pyinstaller.sh" --dist "$DIST_ROOT"

ENTRY="$HERE/.pyinstaller_gui_entry.py"
cat > "$ENTRY" <<'PY'
from fedleave_gui.__main__ import main

if __name__ == '__main__':
    main()
PY

rm -rf "$APP_DIST"
pyinstaller \
  --noconfirm \
  --onedir \
  --windowed \
  --name FedLeaveCalendar \
  --add-data "$HERE/help:help" \
  --hidden-import PySide6.QtCore \
  --hidden-import PySide6.QtGui \
  --hidden-import PySide6.QtWidgets \
  --hidden-import PySide6.QtPrintSupport \
  --distpath "$DIST_ROOT" \
  --workpath "$HERE/.pyinstaller-build" \
  --specpath "$HERE/.pyinstaller-spec" \
  "$ENTRY"

mv "$DIST_ROOT/FedLeaveCalendar" "$APP_DIST"
cp "$DIST_ROOT/fedleave" "$APP_DIST/fedleave"
cp -R "$HERE/help" "$APP_DIST/help"

echo "GUI build complete: $APP_DIST"
echo "  - FedLeaveCalendar"
echo "  - fedleave"
