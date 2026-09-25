@echo off
setlocal

REM Resolve repo root as the parent of this script directory
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%\..") do set "REPO_ROOT=%%~fI"

cd /d "%REPO_ROOT%" || (
    echo [ERROR] Failed to change directory to repo root: "%REPO_ROOT%".
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Please run installation first:
    echo python -m venv .venv
    echo .venv\Scripts\activate
    echo pip install -e .[dev]
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing build dependencies...
    pip install -e .[dev]
    if errorlevel 1 (
        echo [ERROR] Failed to install dev dependencies.
        call .venv\Scripts\deactivate.bat
        pause
        exit /b 1
    )
)

echo [INFO] Bumping app version...
for /f %%v in ('python .bin\bump_version.py') do set NEW_VERSION=%%v
if errorlevel 1 (
    echo [ERROR] Failed to bump app version.
    call .venv\Scripts\deactivate.bat
    pause
    exit /b 1
)
echo [INFO] New version: %NEW_VERSION%

echo [INFO] Cleaning previous build output...
if exist "build" rmdir /s /q "build"
if exist "dist\claude-tidy" rmdir /s /q "dist\claude-tidy"

echo [INFO] Building Claude Tidy desktop app...
pyinstaller claude-tidy.spec

if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    call .venv\Scripts\deactivate.bat
    pause
    exit /b 1
)

echo [INFO] Build complete: dist\claude-tidy\claude-tidy.exe

call .venv\Scripts\deactivate.bat
pause
