@echo off
setlocal

REM Resolve repo root as the parent of this script directory
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%\..") do set "REPO_ROOT=%%~fI"

cd /d "%REPO_ROOT%" || (
    echo [ERROR] Failed to change directory to repo root: "%REPO_ROOT%".
    exit /b 1
)

:: Claude Tidy is a Windows desktop app (pywebview + HTML/Bootstrap 5), not a
:: browser webapp — this launcher just activates the venv and starts the GUI.

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Please run installation first:
    echo python -m venv .venv
    echo .venv\Scripts\activate
    echo pip install -e .[dev]
    pause
    exit /b 1
)

echo [INFO] Starting Claude Tidy...
echo [INFO] Press Ctrl+C to stop.

call .venv\Scripts\activate.bat

:: Clear stale bytecode cache so code changes always take effect
if exist "claude_tidy\__pycache__" (
    echo [INFO] Clearing Python cache...
    for /d /r "claude_tidy" %%d in (__pycache__) do (
        if exist "%%d" rmdir /s /q "%%d"
    )
)

python -m claude_tidy

call .venv\Scripts\deactivate.bat
pause
