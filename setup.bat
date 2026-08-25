@echo off
setlocal
REM ============================================================
REM  JARVIS / VONDO - one-click setup for a NEW PC.
REM
REM  Double-click this once after copying or cloning the folder.
REM  It builds a private Python environment inside the folder, so
REM  nothing is installed system-wide and nothing can conflict.
REM ============================================================
cd /d "%~dp0"
title Jarvis Setup

echo.
echo   ============================================================
echo    JARVIS SETUP
echo    Folder: %~dp0
echo   ============================================================
echo.

REM ---- 1. Python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python is not installed, or not on your PATH.
    echo.
    echo   Install Python 3.10 or newer from https://python.org/downloads
    echo   IMPORTANT: tick "Add Python to PATH" in the installer.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo   [1/4] Found %%v

REM ---- 2. Private environment ----
if exist ".venv\Scripts\python.exe" (
    echo   [2/4] Environment already exists - reusing it.
) else (
    echo   [2/4] Creating a private Python environment ^(.venv^)...
    python -m venv .venv
    if errorlevel 1 (
        echo   [ERROR] Could not create the environment.
        pause
        exit /b 1
    )
)
set "PY=%~dp0.venv\Scripts\python.exe"

REM ---- 3. Dependencies ----
echo   [3/4] Installing dependencies ^(a few minutes the first time^)...
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install -r requirements/legacy.txt --quiet
if errorlevel 1 (
    echo.
    echo   [!] Something failed - most likely PyAudio, which needs a
    echo       prebuilt wheel on some PCs. Trying the fallback...
    "%PY%" -m pip install pipwin --quiet
    "%PY%" -m pipwin install pyaudio
    "%PY%" -m pip install -r requirements/legacy.txt --quiet
    if errorlevel 1 (
        echo.
        echo   [ERROR] Install still failed. Send me the message above.
        pause
        exit /b 1
    )
)

REM ---- 4. Settings file ----
if exist ".env" (
    echo   [4/4] Settings file already exists - keeping yours.
) else (
    echo   [4/4] Creating your settings file ^(.env^)...
    copy ".env.example" ".env" >nul
    echo.
    echo   ------------------------------------------------------------
    echo    Opening .env - paste ONE free API key, save, and close it.
    echo.
    echo      Gemini key ^(free^):  https://aistudio.google.com/app/apikey
    echo      Groq key   ^(free^):  https://console.groq.com/keys
    echo.
    echo    Prefer NO key at all? Run install_local_llm.bat instead and
    echo    pick "Ollama" in the app - it runs AI on this PC, offline.
    echo   ------------------------------------------------------------
    echo.
    pause
    notepad ".env"
)

echo.
echo   ============================================================
echo    SETUP COMPLETE
echo.
echo    Start Jarvis      ^-^>  start_jarvis.bat   ^(window, no console^)
echo                      ^-^>  run.bat            ^(console, shows errors^)
echo    Start with the PC ^-^>  enable_autostart.bat
echo    Offline AI brain  ^-^>  install_local_llm.bat
echo   ============================================================
echo.
pause
