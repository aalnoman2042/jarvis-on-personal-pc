@echo off
setlocal
REM ============================================================
REM  INSTALL the local (offline) AI brain for Jarvis.
REM
REM  Puts Ollama AND the model inside the "local llm" folder next
REM  to this script - nothing goes on your C: drive, and the whole
REM  thing moves with the project folder.
REM
REM  Run this once per PC. Then pick "Ollama" in the Jarvis window.
REM ============================================================
cd /d "%~dp0"
set "BASE=%~dp0local llm"
set "MODEL=qwen2.5:3b"

echo.
echo   Installing the local AI brain into:
echo     %BASE%
echo.

if not exist "%BASE%" mkdir "%BASE%"
if not exist "%BASE%\models" mkdir "%BASE%\models"

REM Keep every downloaded model inside our folder, not in the user profile.
REM 'set' applies to this script (so the server we launch below inherits it),
REM 'setx' makes it stick for future logins.
set "OLLAMA_MODELS=%BASE%\models"
setx OLLAMA_MODELS "%BASE%\models" >nul

REM ---- 1. Install the Ollama runtime if it isn't there yet ----
set "OLLAMA_EXE=%BASE%\ollama\ollama.exe"
if exist "%OLLAMA_EXE%" goto :have_ollama

where ollama >nul 2>&1
if %errorlevel%==0 (
    echo   [1/3] Ollama already installed system-wide - using that.
    for /f "delims=" %%i in ('where ollama') do set "OLLAMA_EXE=%%i"
    goto :have_ollama
)

if not exist "%BASE%\OllamaSetup.exe" (
    echo   [1/3] Downloading Ollama ^(about 700 MB, one time^)...
    powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile '%BASE%\OllamaSetup.exe' -UseBasicParsing"
    if errorlevel 1 (
        echo   [ERROR] Download failed. Check your internet connection.
        pause
        exit /b 1
    )
)

echo   [1/3] Installing Ollama into the project folder...
"%BASE%\OllamaSetup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="%BASE%\ollama"
if not exist "%OLLAMA_EXE%" (
    echo   [ERROR] Install did not finish. Try running OllamaSetup.exe manually.
    pause
    exit /b 1
)

:have_ollama
echo   [2/3] Starting the local AI server...
tasklist /fi "imagename eq ollama.exe" 2>nul | find /i "ollama.exe" >nul
if errorlevel 1 start "" /b "%OLLAMA_EXE%" serve
REM Give the server a moment to come up before asking it for a model.
powershell -NoProfile -Command "Start-Sleep -Seconds 4" >nul

echo   [3/3] Downloading the %MODEL% model ^(about 2 GB, one time^)...
"%OLLAMA_EXE%" pull %MODEL%
if errorlevel 1 (
    echo.
    echo   [ERROR] Could not download the model. Is the internet up?
    pause
    exit /b 1
)

echo.
echo   ============================================================
echo    DONE. Jarvis can now think entirely offline on this PC.
echo.
echo    Open Jarvis and choose "Ollama" in the Brain dropdown.
echo    No API key, no internet, no limits.
echo   ============================================================
echo.
pause
