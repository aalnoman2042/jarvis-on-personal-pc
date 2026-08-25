@echo off
REM ============================================================
REM  Link this PC to your Jarvis cloud. Do this once.
REM
REM  It asks for your 4-digit PIN -- the same one you type on
REM  the phone. After this the PC has its own token and never
REM  needs the PIN again.
REM ============================================================
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m agent.login
) else (
    python -m agent.login
)
pause
