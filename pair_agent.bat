@echo off
REM ============================================================
REM  Pair this PC with your Jarvis cloud. Do this once.
REM
REM  On your phone: ask Jarvis to pair a new device -- it gives
REM  you a six-digit code. Type that code here when asked.
REM ============================================================
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m agent.pair
) else (
    python -m agent.pair
)
pause
