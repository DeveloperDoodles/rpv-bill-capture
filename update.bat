@echo off
REM Download and install the latest version from GitHub. Your settings, calibration,
REM Google login file and logs are kept.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1"
pause
