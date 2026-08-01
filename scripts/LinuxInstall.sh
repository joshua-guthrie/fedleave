#!/usr/bin/env bash
# Repository entry point for the shared Python build/install engine on Linux.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENGINE="$SCRIPT_DIR/lib/common/installer_engine.py"

if [[ ! -f "$ENGINE" ]]; then
  echo "ERROR: installer engine not found at $ENGINE" >&2
  exit 3
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required to run the installer engine." >&2
  if command -v apt-get >/dev/null 2>&1; then
    if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
      sudo apt-get update
      sudo apt-get install -y python3 python3-venv python3-pip
    else
      apt-get update
      apt-get install -y python3 python3-venv python3-pip
    fi
  else
    echo "ERROR: apt-get not found and python3 is missing." >&2
    exit 3
  fi
fi

cd "$REPO_ROOT"
exec python3 "$ENGINE" --platform linux "$@"
