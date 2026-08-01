# Development

FedLeave supports Python 3.11 and later. Create and activate a virtual
environment, then install the single authoritative development extra:

```bash
python -m pip install -e ".[dev]"
```

The normal local checks are exposed through `make`:

```bash
make format       # apply deterministic Python formatting
make quality      # formatting check, lint, and scoped strict typing
make test         # run the behavior suite
make check        # run quality and tests
make package      # build the source distribution and wheel
make build        # build the complete Linux PyInstaller bundle
```

Set `PYTHON=/path/to/python` when the desired interpreter is not named
`python`, for example `make PYTHON=.venv/bin/python check`.

## Project configuration

`pyproject.toml` owns package metadata, runtime dependencies, optional
dependency groups, console entry points, package discovery, pytest settings,
Ruff settings, and mypy settings. Do not add parallel requirements files.

Ruff checks all maintained Python source and tests. Strict mypy coverage starts
with the small core modules listed in `pyproject.toml`; expand that list as
neighboring contracts are made precise rather than hiding errors with broad
ignores.

CI runs the complete test suite on Ubuntu and Windows. A separate Ubuntu job
runs quality checks and builds both Python distribution formats.

## Generated files

Virtual environments, editable-install metadata, PyInstaller workspaces,
bundles, and Python package build outputs are local artifacts and must remain
untracked. `tests/test_repository_hygiene.py` enforces that rule using Git's
own ignore configuration.
