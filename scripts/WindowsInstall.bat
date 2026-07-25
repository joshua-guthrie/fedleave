@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."
set "ENGINE=%SCRIPT_DIR%lib\common\installer_engine.py"

if not exist "%ENGINE%" (
  echo ERROR: installer engine not found at "%ENGINE%"
  exit /b 3
)

set "PYTHON_CMD="
where python >nul 2>nul
if %ERRORLEVEL%==0 (
  set "PYTHON_CMD=python"
) else (
  where py >nul 2>nul
  if %ERRORLEVEL%==0 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
  where winget >nul 2>nul
  if %ERRORLEVEL%==0 (
    echo Python 3.11+ not found. Attempting bootstrap via winget...
    winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    where py >nul 2>nul
    if %ERRORLEVEL%==0 (
      set "PYTHON_CMD=py -3"
    ) else (
      where python >nul 2>nul
      if %ERRORLEVEL%==0 set "PYTHON_CMD=python"
    )
  )
)

if not defined PYTHON_CMD (
  echo ERROR: Python 3.11+ is required and could not be bootstrapped.
  echo Install Python 3.11+ or rerun with winget available.
  exit /b 3
)

cd /d "%REPO_ROOT%"
%PYTHON_CMD% "%ENGINE%" --platform windows %*
exit /b %ERRORLEVEL%
