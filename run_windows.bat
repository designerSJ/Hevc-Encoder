@echo off
setlocal
cd /d "%~dp0"
title HEVC 10-Bit Studio

where python >nul 2>nul
if errorlevel 1 (
    echo Python 3 was not found. Install Python 3 and enable "Add Python to PATH", then run this launcher again.
    pause
    exit /b 1
)

python --version
if errorlevel 1 (
    echo Python could not be started. Check the Python installation and PATH.
    pause
    exit /b 1
)

REM Run the GUI with the same interpreter used by the app's dependency bootstrap.
REM Keep the console open so startup and dependency errors remain visible.
python "%~dp0hevc_encoder_gui.py" %*
if errorlevel 1 pause
endlocal
