#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
APP_SRC="$HERE/dist/fedleave-Ubuntu"
INSTALL_DIR="${HOME}/.local/share/fedleave-app"
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/.local/share/applications"

if [[ ! -x "$APP_SRC/FedLeaveCalendar/FedLeaveCalendar" ]]; then
  echo "Build the GUI first with scripts/build_gui_pyinstaller.sh" >&2
  exit 1
fi

rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR"
cp -a "$APP_SRC"/. "$INSTALL_DIR"/

for bundle in "$INSTALL_DIR"/*; do
  [[ -d "$bundle" ]] || continue
  app="$(basename "$bundle")"
  if [[ -x "$bundle/$app" ]]; then
    ln -sf "$bundle/$app" "$BIN_DIR/$app"
  fi
done
ln -sf "$INSTALL_DIR/FedLeaveCalendar/FedLeaveCalendar" "$BIN_DIR/fedleave-calendar"

cat > "$DESKTOP_DIR/fedleave-calendar.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=FedLeave Calendar
Exec=$INSTALL_DIR/FedLeaveCalendar/FedLeaveCalendar
Terminal=false
Categories=Office;
EOF

echo "Installed FedLeave Calendar to $INSTALL_DIR"
