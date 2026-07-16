PYENV?=.venv

.PHONY: build
build:
	@echo "Building complete FedLeave PyInstaller bundles"
	@./scripts/LinuxInstall.sh --unattended --build-only --verbose
