@echo off
REM Opens the capture window directly (the desktop shortcut points here).
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist venv\Scripts\python.exe (
    echo Not set up yet. Run setup_windows.bat first.
    pause
    exit /b 1
)
start "RPV Bill Capture" /min venv\Scripts\python.exe -m rpv_app
