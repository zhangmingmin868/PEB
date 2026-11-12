@echo off
REM ------------------------------------------------------------------
REM  Build LabDream Version 3.1 for Windows  ->  dist\LabDream\LabDream.exe
REM  Requirements: Python 3.9+ (64-bit) from python.org, "Add to PATH" ticked
REM  Usage: double-click this file, or run it from a command prompt
REM ------------------------------------------------------------------
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.9+ from https://www.python.org and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist .venv-build (
    echo Creating build environment...
    python -m venv .venv-build || goto :fail
)

echo Installing dependencies...
.venv-build\Scripts\python -m pip install --upgrade pip >nul
.venv-build\Scripts\pip install -r requirements.txt pyinstaller || goto :fail

echo Building LabDream.exe ...
.venv-build\Scripts\pyinstaller --noconfirm --clean labdream.spec || goto :fail

echo.
echo ==============================================================
echo  Done:  %cd%\dist\LabDream\LabDream.exe
echo  Copy the whole dist\LabDream folder to the target computer.
echo ==============================================================
pause
exit /b 0

:fail
echo.
echo [ERROR] Build failed - see messages above.
pause
exit /b 1
