@echo off
REM ============================================================
REM  START the Jarvis UI (a window, no black console).
REM  Double-click this to turn Jarvis on.
REM ============================================================
cd /d "%~dp0"

if not exist ".env" (
    echo First run detected. Please run setup.bat once.
    pause
    exit /b 1
)

REM Prefer the private environment built by setup.bat; fall back to system Python.
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0jarvis_gui.py" %*
) else (
    start "" pythonw "%~dp0jarvis_gui.py" %*
)
