@echo off
REM ============================================================
REM  Start the Jarvis PC agent -- the small process that lets
REM  your phone open apps and see this PC's CPU.
REM
REM  It uses almost nothing: no AI, no models, no microphone.
REM  Close this window to stop it.
REM ============================================================
setlocal
cd /d "%~dp0"
title Jarvis PC agent

REM Pick an interpreter. A .venv is preferred -- but only if it can actually
REM import what the agent needs. An empty venv used to win this race and the
REM agent died on "No module named psutil" with no hint about which Python
REM was even being used.
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" -c "import psutil, websockets" 2>nul
if errorlevel 1 (
    echo.
    echo   Installing what the agent needs, once...
    "%PY%" -m pip install -r requirements/agent.txt
    if errorlevel 1 (
        echo.
        echo   [X] Could not install. Check your internet, then try again.
        pause
        exit /b 1
    )
    echo.
)

"%PY%" -m agent.agent

echo.
echo   The agent stopped. Press any key to close.
pause >nul
