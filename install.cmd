@echo off
setlocal
cd /d "%~dp0"
title HEVC 10-Bit Studio Setup

where python >nul 2>nul
if errorlevel 1 (
    where winget >nul 2>nul
    if errorlevel 1 (
        echo Python 3 was not found and winget is unavailable.
        echo Install Python 3 from python.org with "Add Python to PATH" enabled.
        pause
        exit /b 1
    )
    echo Installing Python 3...
    winget install --exact --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo Python installation failed. Install Python 3 manually, then run this script again.
        pause
        exit /b 1
    )
    echo Python was installed. Close this window, open a new terminal, and run install.cmd again.
    pause
    exit /b 0
)

python --version
if errorlevel 1 (
    echo Python could not be started. Check the Python installation and PATH.
    pause
    exit /b 1
)

echo Installing / updating Drag-and-Drop library (tkinterdnd2)...
python -m pip install --upgrade "tkinterdnd2>=0.4.2"
if errorlevel 1 (
    echo Note: Optional drag-and-drop install failed. The app will still function via buttons and Ctrl+V.
)

echo Starting HEVC 10-Bit Studio...
call "%~dp0run_windows.bat"
endlocal
