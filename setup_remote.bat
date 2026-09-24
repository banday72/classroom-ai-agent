@echo off
REM ============================================================
REM  Classroom AI Assistant - one-click setup & launch on Windows
REM  Run this on the REMOTE computer after extracting the zip.
REM ============================================================
cd /d "%~dp0"

REM 1) Check Python is installed
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo  Python is NOT installed on this machine.
    echo  Install it from:  https://www.python.org/downloads/
    echo  During installation, TICK the box:  "Add python.exe to PATH"
    echo  Then close this window and run this file again.
    echo.
    pause
    exit /b 1
)

REM 2) Create the virtual environment (only the first time)
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

REM 3) Install dependencies
echo Installing dependencies (first run takes a few minutes)...
venv\Scripts\python.exe -m pip install --upgrade pip >nul
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency install FAILED. Check you have internet access.
    pause
    exit /b 1
)

REM 4) Launch the app
echo.
echo Starting the app... choose option [1] to sign in with Google.
venv\Scripts\python.exe -m app.main

pause