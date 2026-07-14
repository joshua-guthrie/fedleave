#!/usr/bin/env bash
set -euo pipefail

# Build the CLI and companion console executables using PyInstaller.
# Usage: ./scripts/build_pyinstaller_core.sh [--dist dist/fedleave-Ubuntu]

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV_DIR="$HERE/.pyinstaller-venv"
DIST_DIR="$HERE/dist/fedleave-Ubuntu"

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

DIST_ROOT="$(dirname "$DIST_DIR")"

mkdir -p "$DIST_ROOT"
find "$DIST_ROOT" -maxdepth 1 -type f -delete
rm -rf \
  "$DIST_DIR/fedleave" \
  "$DIST_DIR/AnnualLeaveChartForTheYear" \
  "$DIST_DIR/SickLeaveChartForTheYear" \
  "$DIST_DIR/CreditHoursChartForTheYear" \
  "$DIST_DIR/CompTimeChartForTheYear" \
  "$DIST_DIR/TravelCompChartForTheYear" \
  "$DIST_DIR/TimeOffAwardChartForTheYear" \
  "$DIST_DIR/fedleaveMonthReportGraphic"

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

build_app() {
  local app_name="$1"
  local entry_path="$2"
  shift 2

  rm -rf "$DIST_DIR/$app_name"
  pyinstaller \
    --noconfirm \
    --onedir \
    --name "$app_name" \
    --console \
    "$@" \
    --distpath "$DIST_DIR" \
    --workpath "$HERE/.pyinstaller-build" \
    --specpath "$HERE/.pyinstaller-spec" \
    "$entry_path"

  local executable_path="$DIST_DIR/$app_name/$app_name"
  if [[ ! -x "$executable_path" ]]; then
    echo "Expected executable was not created: $executable_path" >&2
    exit 1
  fi
}

build_app fedleave "$ENTRY" \
  --hidden-import holidays \
  --hidden-import icalendar

# Build AnnualLeaveChartForTheYear companion application
CHART_ENTRY="$HERE/.pyinstaller_chart_entry.py"
cat > "$CHART_ENTRY" <<'PY'
from annual_leave_chart.__main__ import main

if __name__ == '__main__':
    main()
PY

build_app AnnualLeaveChartForTheYear "$CHART_ENTRY" \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageDraw \
  --hidden-import PIL.ImageFont \
  --hidden-import numpy

# Build SickLeaveChartForTheYear companion application
SICK_CHART_ENTRY="$HERE/.pyinstaller_sick_chart_entry.py"
cat > "$SICK_CHART_ENTRY" <<'PY'
from sick_leave_chart.__main__ import main

if __name__ == '__main__':
    main()
PY

build_app SickLeaveChartForTheYear "$SICK_CHART_ENTRY" \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageDraw \
  --hidden-import PIL.ImageFont \
  --hidden-import numpy

# Build CreditHoursChartForTheYear companion application
CREDIT_CHART_ENTRY="$HERE/.pyinstaller_credit_hours_chart_entry.py"
cat > "$CREDIT_CHART_ENTRY" <<'PY'
from credit_hours_chart.__main__ import main

if __name__ == '__main__':
    main()
PY

build_app CreditHoursChartForTheYear "$CREDIT_CHART_ENTRY" \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageDraw \
  --hidden-import PIL.ImageFont \
  --hidden-import numpy

# Build CompTimeChartForTheYear companion application
COMP_CHART_ENTRY="$HERE/.pyinstaller_comp_time_chart_entry.py"
cat > "$COMP_CHART_ENTRY" <<'PY'
from comp_time_chart.__main__ import main

if __name__ == '__main__':
    main()
PY

build_app CompTimeChartForTheYear "$COMP_CHART_ENTRY" \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageDraw \
  --hidden-import PIL.ImageFont \
  --hidden-import numpy

# Build TravelCompChartForTheYear companion application
TRAVEL_CHART_ENTRY="$HERE/.pyinstaller_travel_comp_chart_entry.py"
cat > "$TRAVEL_CHART_ENTRY" <<'PY'
from travel_comp_chart.__main__ import main

if __name__ == '__main__':
    main()
PY

build_app TravelCompChartForTheYear "$TRAVEL_CHART_ENTRY" \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageDraw \
  --hidden-import PIL.ImageFont \
  --hidden-import numpy

# Build TimeOffAwardChartForTheYear companion application
TIME_OFF_CHART_ENTRY="$HERE/.pyinstaller_time_off_award_chart_entry.py"
cat > "$TIME_OFF_CHART_ENTRY" <<'PY'
from time_off_award_chart.__main__ import main

if __name__ == '__main__':
    main()
PY

build_app TimeOffAwardChartForTheYear "$TIME_OFF_CHART_ENTRY" \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageDraw \
  --hidden-import PIL.ImageFont \
  --hidden-import numpy

# Build fedleaveMonthReportGraphic companion application
MONTH_REPORT_ENTRY="$HERE/.pyinstaller_month_report_entry.py"
cat > "$MONTH_REPORT_ENTRY" <<'PY'
from fedleave_month_report_graphic.__main__ import main

if __name__ == '__main__':
    main()
PY

build_app fedleaveMonthReportGraphic "$MONTH_REPORT_ENTRY" \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageDraw \
  --hidden-import PIL.ImageFont

echo "Build complete. Binaries in $DIST_DIR"
echo "  - fedleave/fedleave"
echo "  - AnnualLeaveChartForTheYear/AnnualLeaveChartForTheYear"
echo "  - SickLeaveChartForTheYear/SickLeaveChartForTheYear"
echo "  - CreditHoursChartForTheYear/CreditHoursChartForTheYear"
echo "  - CompTimeChartForTheYear/CompTimeChartForTheYear"
echo "  - TravelCompChartForTheYear/TravelCompChartForTheYear"
echo "  - TimeOffAwardChartForTheYear/TimeOffAwardChartForTheYear"
echo "  - fedleaveMonthReportGraphic/fedleaveMonthReportGraphic"
