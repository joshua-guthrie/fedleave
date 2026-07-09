#!/usr/bin/env bash
set -euo pipefail

rm -rf "${HOME}/.local/share/fedleave-calendar"
rm -f "${HOME}/.local/bin/fedleave-calendar"
rm -f "${HOME}/.local/share/applications/fedleave-calendar.desktop"
echo "Removed FedLeave Calendar application files. Leave data and GUI settings were preserved."
