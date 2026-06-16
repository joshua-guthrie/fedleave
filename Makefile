PYENV?=.venv

.PHONY: build
build:
	@echo "Building standalone fedleave executable (PyInstaller)"
	@./scripts/build_pyinstaller.sh
