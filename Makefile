PYENV?=.venv

.PHONY: build
build:
	@echo "Building complete FedLeave PyInstaller bundles"
	@./scripts/build_pyinstaller.sh
