@echo off
REM ============================================================
REM  Start the Jarvis PC agent -- the small process that lets
REM  your phone open apps and see this PC's CPU.
REM
REM  It uses almost nothing: no AI, no models, no microphone.
REM  Close this window to stop it.
REM ============================================================
cd /d "%~dp0"
title Jarvis PC agent
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m agent.agent
) else (
    python -m agent.agent
)
echo.
echo   The agent stopped. Press any key to close.
pause >nul
