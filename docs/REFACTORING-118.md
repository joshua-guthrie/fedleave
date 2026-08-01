# Issue 118 review record

This record distinguishes agreed maintainability work from recommendations
that would add compatibility risk or abstraction without demonstrated value.

## Implemented

- Removed tracked virtual-environment, PyInstaller, and distribution output;
  added a repository-hygiene regression check.
- Moved every importable package under `src/` and updated setuptools, pytest,
  installer smoke tests, PyInstaller search paths, resource lookup, and helper
  scripts.
- Made `pyproject.toml` the only dependency definition and updated CI and the
  build installer to consume extras from it.
- Added standard format, lint, strict scoped type-check, test, package, and
  bundle targets. CI now enforces quality and builds sdist/wheel artifacts.
- Applied deterministic formatting and safe lint cleanup across maintained
  Python code.
- Removed a duplicate `sanitize_text` implementation and unused analytics/test
  assignments. Declared the intentional `fedleave.cli` compatibility exports
  explicitly instead of leaving ambiguous unused imports.
- Documented source ownership, dependency direction, compatibility surfaces,
  and the developer workflow.

## Retained intentionally

- Existing console command names and the `fedleave.cli` import facade.
- Existing top-level companion package names. Renaming them into
  `fedleave.*` would break import and module-launch compatibility without
  improving runtime behavior.
- The shared application manifest and PyInstaller spec. They contain packaging
  metadata that is not expressible as standard project entry-point metadata.
- The CLI subprocess boundary used by GUI/report applications, which keeps one
  authoritative behavior path in packaged and source installations.

## Not implemented in this issue

- Blanket service/repository/controller classes. Those layers are useful only
  when a concrete boundary requires them; introducing them speculatively would
  increase indirection.
- Splitting modules solely by line count. Large GUI and analytics modules need
  focused characterization tests and cohesive extraction plans so signal/slot
  wiring, monkeypatch seams, and JSON presentation behavior remain stable.
- Removing public-looking modules or compatibility imports based only on a
  static "unused" report. Dynamic entry points, tests, PyInstaller discovery,
  and downstream imports make reachability part of the compatibility contract.

Future extractions should be small, separately reviewed changes with a named
responsibility, a preserved import path where needed, and before/after behavior
tests.
