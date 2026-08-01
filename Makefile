PYTHON ?= python
PYTHON_SOURCES := src tests installer scripts

.PHONY: format format-check lint typecheck test quality check package build
format:
	$(PYTHON) -m ruff format $(PYTHON_SOURCES)

format-check:
	$(PYTHON) -m ruff format --check $(PYTHON_SOURCES)

lint:
	$(PYTHON) -m ruff check $(PYTHON_SOURCES)

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest -q

quality: format-check lint typecheck

check: quality test

package:
	$(PYTHON) -m build

build:
	@echo "Building complete FedLeave PyInstaller bundles"
	@./scripts/LinuxInstall.sh --unattended --build-only --verbose
