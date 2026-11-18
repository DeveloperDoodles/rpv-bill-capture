@echo off
REM RPV Bill OCR launcher. Double-click and pick an option.
cd /d "%~dp0"
set PYTHON=venv\Scripts\python.exe
set PYTHONUTF8=1

if not exist "%PYTHON%" (
    echo.
    echo [ERROR] Not set up yet. Run setup_windows.bat first.
    echo.
    pause
    exit /b 1
)

:menu
cls
echo ========================================================
echo                 RPV BILL CAPTURE
echo ========================================================
echo.
echo   1. Start capturing bills
echo   2. Calibrate screen (first time, or after changing
echo      screen resolution / RPV window position)
echo   3. Test reading the current RPV bill
echo   4. Practice capture (nothing is written to the sheet)
echo   5. Test Google Sheets connection
echo   6. Upload bills that are waiting (saved while offline)
echo   7. Check everything (health check)
echo   8. Exit
echo.
set "choice="
set /p choice="Enter a number (1-8): "

if "%choice%"=="1" ( "%PYTHON%" -m rpv_app & pause & goto menu )
if "%choice%"=="2" ( "%PYTHON%" -m rpv_app --calibrate & pause & goto menu )
if "%choice%"=="3" ( "%PYTHON%" -m rpv_app --test & pause & goto menu )
if "%choice%"=="4" ( "%PYTHON%" -m rpv_app --dry-run & pause & goto menu )
if "%choice%"=="5" ( "%PYTHON%" -m rpv_app --test-sheets & pause & goto menu )
if "%choice%"=="6" ( "%PYTHON%" -m rpv_app --upload & pause & goto menu )
if "%choice%"=="7" ( "%PYTHON%" -m rpv_app --doctor & pause & goto menu )
if "%choice%"=="8" exit /b 0
goto menu
