@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo =========================================
echo   RPV Bill OCR - Setup (Windows)
echo =========================================
echo.

REM 1. Python 3.9 or newer
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.9 or newer was not found.
    echo         Install Python 3.12 and tick "Add Python to PATH" on the first screen.
    pause
    exit /b 1
)
for /f "delims=" %%v in ('python --version') do echo [OK] %%v found.

REM 2. Virtual environment
if not exist venv\Scripts\python.exe (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if !errorlevel! neq 0 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
)
set PYTHON_EXE="%CD%\venv\Scripts\python.exe"

REM 3. Packages (uses the offline_packages folder if it exists)
echo [INFO] Installing packages...
if exist offline_packages\ (
    %PYTHON_EXE% -m pip install --no-index --find-links=offline_packages -r requirements.txt
) else (
    %PYTHON_EXE% -m pip install --upgrade pip
    %PYTHON_EXE% -m pip install -r requirements.txt
)
if !errorlevel! neq 0 (
    echo [ERROR] Package install failed.
    pause
    exit /b 1
)
echo [OK] Packages installed.

REM 4. Tesseract
set TESS_FOUND=0
where tesseract >nul 2>&1 && set TESS_FOUND=1
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set TESS_FOUND=1
if exist "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" set TESS_FOUND=1
if exist "%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe" set TESS_FOUND=1
if !TESS_FOUND! equ 1 (
    echo [OK] Tesseract OCR found.
) else (
    echo [WARNING] Tesseract OCR not found. Install it before running - reading will not work.
)

REM 5. Settings for this computer (Google Sheet link + computer name)
if not exist settings.json (
    %PYTHON_EXE% -m rpv_app --setup
) else (
    echo [OK] settings.json found. To change it run: venv\Scripts\python.exe -m rpv_app --setup
)

REM 6. Google login file
if exist credentials\client_secret.json (
    echo [OK] Google client_secret.json found.
) else (
    echo [WARNING] credentials\client_secret.json is missing - Google Sheets will not connect.
    echo           Create a folder named credentials here and put client_secret.json in it.
    echo           See README.md - "Google setup".
)
if exist credentials\token.json (
    echo [WARNING] credentials\token.json is an old copied Google login. Delete it;
    echo           each computer now logs in once and keeps its own login.
)

REM 7. Party codes
if not exist party_codes.csv (
    echo [INFO] No party_codes.csv - party codes will only be checked for format.
)

REM 8. Desktop shortcut that opens the capture window directly
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'RPV Bill Capture.lnk')); $s.TargetPath='%CD%\start_capture.bat'; $s.WorkingDirectory='%CD%'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,22'; $s.Save()" >nul 2>&1
if !errorlevel! equ 0 (
    echo [OK] Desktop shortcut "RPV Bill Capture" created - double-click it to start capturing.
) else (
    echo [INFO] Could not create the desktop shortcut. Use start_capture.bat instead.
)

echo.
echo =========================================
echo   SETUP COMPLETE - now double-click run.bat
echo   and choose 2 (Calibrate) the first time.
echo   Problems? run.bat option 7 checks everything.
echo =========================================
pause
