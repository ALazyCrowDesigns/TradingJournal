@echo off
REM Trading Journal GUI Launcher
REM This script launches the Trading Journal application using Python 3.13

echo Starting Trading Journal...
echo.

REM Change to the project directory
cd /d "%~dp0"

REM Run the application using Python 3.13
py -3.13 app.py

REM Keep the window open if there's an error
if errorlevel 1 (
    echo.
    echo An error occurred. Press any key to close...
    pause >nul
)
