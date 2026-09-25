@echo off
setlocal enabledelayedexpansion

REM Resolve repo root as the parent of this script directory
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%\..") do set "REPO_ROOT=%%~fI"

pushd "%REPO_ROOT%" >nul 2>&1 || (
  echo [ERROR] Failed to change directory to repo root: "%REPO_ROOT%".
  exit /b 1
)

if "%~1"=="" goto :usage
if "%~1"=="--freeze" goto :freeze
if "%~1"=="--install" goto :install
if "%~1"=="-h" goto :usage
if "%~1"=="--help" goto :usage

echo [ERROR] Unknown option: %~1
goto :usage

:freeze
  REM pyproject.toml is the real dependency source in this repo — this is
  REM just a debug snapshot of what's actually installed, not reinstallable
  REM input. See README.md's "Kiem tra / export danh sach package da cai".
  echo [INFO] Writing installed packages to pip-freeze.txt ...
  python -m pip freeze > pip-freeze.txt
  set "EC=%ERRORLEVEL%"
  if not "%EC%"=="0" (
    echo [ERROR] pip freeze failed with exit code %EC%.
    popd >nul
    exit /b %EC%
  )
  echo [OK] Saved to "%REPO_ROOT%\pip-freeze.txt".
  popd >nul
  exit /b 0

:install
  echo [INFO] Installing claude-tidy + dev extras from pyproject.toml ...
  python -m pip install -e .[dev]
  set "EC=%ERRORLEVEL%"
  if not "%EC%"=="0" (
    echo [ERROR] pip install failed with exit code %EC%.
    popd >nul
    exit /b %EC%
  )
  echo [OK] Installed from pyproject.toml (editable install + [dev] extras).
  popd >nul
  exit /b 0

:usage
  echo Usage: .\.bin\py-requirements.bat [--freeze ^| --install]
  echo.
  echo   --freeze   Save currently installed packages to pip-freeze.txt (debug
  echo              snapshot only — pyproject.toml stays the source of truth)
  echo   --install  Install claude-tidy + dev extras from pyproject.toml
  echo              (pip install -e .[dev])
  echo.
  echo Run from anywhere; operates at repo root: "%REPO_ROOT%"
  popd >nul
  exit /b 1
