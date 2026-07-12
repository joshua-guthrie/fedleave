#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
APP_SRC="$HERE/dist/fedleave-Ubuntu"
INSTALL_DIR="${HOME}/.local/share/fedleave-calendar"
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/.local/share/applications"

if [[ ! -x "$APP_SRC/FedLeaveCalendar" ]]; then
  echo "Build the GUI first with scripts/build_gui_pyinstaller.sh" >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR"
cp "$APP_SRC/FedLeaveCalendar" "$APP_SRC/fedleave" "$INSTALL_DIR/"
ln -sf "$INSTALL_DIR/FedLeaveCalendar" "$BIN_DIR/fedleave-calendar"
cat > "$DESKTOP_DIR/fedleave-calendar.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=FedLeave Calendar
Exec=$INSTALL_DIR/FedLeaveCalendar
Terminal=false
Categories=Office;
EOF

echo "Installed FedLeave Calendar to $INSTALL_DIR"
