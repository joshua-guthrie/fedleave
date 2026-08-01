# Architecture

FedLeave is one distribution containing a command-line application, two Qt
applications, report renderers, and compatibility entry points. Importable
Python code lives under `src/`; repository-root directories contain project
metadata, documentation, tests, assets, installers, and build orchestration.

## Source map

- `src/fedleave/` owns leave-year data, validation, calculations, storage, and
  the Typer command application. `fedleave.commands` contains command adapters;
  calculation and persistence code remains independently callable below it.
- `src/fedleave_gui/` owns the calendar GUI and its subprocess adapter to the
  `fedleave` command. It does not duplicate leave calculations.
- `src/fedleave_analytics/` owns read-only analytics calculations and their Qt
  presentation.
- `src/*_chart/`, `src/yearly_leave_comparison_chart/`, and
  `src/fedleave_month_report_graphic/` are maintained compatibility packages
  for the published companion commands.
- `scripts/lib/common/application_manifest.toml` is the authoritative map from
  `pyproject.toml` console commands to PyInstaller settings.
- `installer/` packages and installs validated bundles; it does not contain
  application behavior.

## Dependency direction

The core `fedleave` package must not import a GUI package. GUI and report
packages may call or import core code. Installer and build code discovers
application entry points from `pyproject.toml` instead of maintaining another
command list. Runtime, optional, test, and build dependencies are likewise
declared only in `pyproject.toml`.

The GUI normally invokes the CLI through its sibling `fedleave` executable.
This keeps the packaged applications consistent with direct CLI use and makes
the subprocess boundary explicit. Executable discovery checks the active
interpreter or bundle directory before `PATH`.

## Compatibility policy

Existing console command names, module names, JSON shapes, data files, and
installer behavior are public compatibility surfaces. Structural work should
preserve them unless a separately reviewed change provides a migration path.
In particular, the companion package names remain top-level packages even
though all of their source now shares the `src/` tree.

New extraction work should follow cohesive behavior boundaries backed by
characterization tests. File length alone is not a reason to introduce a
service, repository, controller, or wrapper.
