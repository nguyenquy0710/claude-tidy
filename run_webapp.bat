@echo off
setlocal
cd /d %~dp0

:: Claude Tidy is a Windows desktop app (ttkbootstrap/Tkinter), not a webapp —
:: this launcher just activates the venv and starts the GUI.

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
