@echo off
REM Launch Jarvis in a console window (shows errors - good for troubleshooting).
cd /d "%~dp0"

if not exist ".env" (
    echo First run detected. Please run setup.bat once.
    pause
    exit /b 1
)

REM Prefer the private environment built by setup.bat; fall back to system Python.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" vondo.py %*
) else (
    python vondo.py %*
)
pause
