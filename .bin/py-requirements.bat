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
  echo [INFO] Writing installed packages to requirements.txt ...
  python -m pip freeze > requirements.txt
  set "EC=%ERRORLEVEL%"
  if not "%EC%"=="0" (
    echo [ERROR] pip freeze failed with exit code %EC%.
    popd >nul
    exit /b %EC%
  )
  echo [OK] Saved to "%REPO_ROOT%\requirements.txt".
  popd >nul
  exit /b 0

:install
  if not exist requirements.txt (
    echo [ERROR] requirements.txt not found in "%REPO_ROOT%".
    echo         Run \.\.bin\py-requirements.bat --freeze to generate it.
    popd >nul
    exit /b 1
  )
  echo [INFO] Installing packages from requirements.txt ...
  python -m pip install -r requirements.txt
  set "EC=%ERRORLEVEL%"
  if not "%EC%"=="0" (
    echo [ERROR] pip install failed with exit code %EC%.
    popd >nul
    exit /b %EC%
  )
  echo [OK] Packages installed from requirements.txt.
  popd >nul

  echo [INFO] Installing packages from requirements-dev.txt ...
  python -m pip install -r requirements-dev.txt
  set "EC=%ERRORLEVEL%"
  if not "%EC%"=="0" (
    echo [ERROR] pip install failed with exit code %EC%.
    popd >nul
    exit /b %EC%
  )
  echo [OK] Packages installed from requirements-dev.txt.
  popd >nul
  exit /b 0

:usage
  echo Usage: .\.bin\py-requirements.bat [--freeze ^| --install]
  echo.
  echo   --freeze   Save current env packages to requirements.txt
  echo   --install  Install packages from requirements.txt
  echo.
  echo Run from anywhere; operates at repo root: "%REPO_ROOT%"
  popd >nul
  exit /b 1