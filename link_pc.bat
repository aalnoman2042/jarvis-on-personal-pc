@echo off
REM ============================================================
REM  Link this PC to your Jarvis cloud. Do this once.
REM
REM  It asks for your 4-digit PIN -- the same one you type on
REM  the phone. After this the PC has its own token and never
REM  needs the PIN again.
REM ============================================================
setlocal
cd /d "%~dp0"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" -c "import psutil, websockets" 2>nul
if errorlevel 1 (
    echo.
    echo   Installing what the agent needs, once...
    "%PY%" -m pip install -r requirements/agent.txt
    if errorlevel 1 (
        echo   [X] Could not install. Check your internet, then try again.
        pause
        exit /b 1
    )
)

if "%VONDO_URL%"=="" set "VONDO_URL=https://vondo-core.onrender.com"
echo   Cloud: %VONDO_URL%

"%PY%" -m agent.login
pause
