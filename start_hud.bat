@echo off
REM ============================================================
REM  Open the Jarvis HUD in its own window (no address bar).
REM
REM  Needs the cloud core running. If it isn't, start it with:
REM     python -m uvicorn server.app:app --port 8000
REM ============================================================
cd /d "%~dp0"
set "URL=%VONDO_URL%"
if "%URL%"=="" set "URL=http://127.0.0.1:8000"

REM Chrome and Edge both support --app, which drops the browser chrome and
REM gives the HUD a real window with its own taskbar entry.
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"

if exist "%CHROME%" (
    start "" "%CHROME%" --app=%URL%
) else if exist "%EDGE%" (
    start "" "%EDGE%" --app=%URL%
) else (
    echo   Neither Chrome nor Edge was found -- opening your default browser.
    start "" %URL%
)
