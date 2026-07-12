#!/usr/bin/env bash
set -euo pipefail

# Build the regular executable set and then the GUI using the shared backend artifacts.
# Usage: ./scripts/build_pyinstaller.sh [--dist dist]

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DIST_DIR="$HERE/dist"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dist)
      DIST_DIR="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

"$HERE/scripts/build_pyinstaller_core.sh" --dist "$DIST_DIR"
"$HERE/scripts/build_gui_pyinstaller.sh" --dist "$DIST_DIR" --skip-backend-build
