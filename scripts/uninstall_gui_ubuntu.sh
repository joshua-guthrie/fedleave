#!/usr/bin/env bash
set -euo pipefail

rm -rf "${HOME}/.local/share/fedleave-app"
rm -f \
  "${HOME}/.local/bin/fedleave" \
  "${HOME}/.local/bin/FedLeaveCalendar" \
  "${HOME}/.local/bin/AnnualLeaveChartForTheYear" \
  "${HOME}/.local/bin/SickLeaveChartForTheYear" \
  "${HOME}/.local/bin/fedleaveMonthReportGraphic" \
  "${HOME}/.local/bin/fedleave-calendar"
rm -f "${HOME}/.local/share/applications/fedleave-calendar.desktop"
echo "Removed FedLeave application files. Leave data and GUI settings were preserved."
