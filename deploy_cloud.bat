@echo off
REM ============================================================
REM  Put Jarvis in the cloud.
REM
REM  Run ONCE to create everything, then again any time to push
REM  new code. Safe to re-run: each step skips if already done.
REM
REM  Before the first run you must be signed in:
REM      flyctl auth login
REM ============================================================
setlocal
cd /d "%~dp0"

set "APP=%VONDO_APP%"
if "%APP%"=="" set "APP=vondo-jarvis"
set "REGION=sin"

echo.
echo   Jarvis cloud deploy  --  app: %APP%  region: %REGION%
echo.

flyctl auth whoami >nul 2>&1
if errorlevel 1 (
    echo   [X] Not signed in to Fly.
    echo       Run this first:   flyctl auth login
    echo.
    pause
    exit /b 1
)

REM --- 1. the app -------------------------------------------------------
flyctl apps list 2>nul | findstr /C:"%APP%" >nul
if errorlevel 1 (
    echo   [1/4] Creating the app...
    flyctl apps create "%APP%"
    if errorlevel 1 (
        echo.
        echo   That name is probably taken -- app names are global.
        echo   Pick another:   set VONDO_APP=vondo-rohan  ^&^&  deploy_cloud.bat
        echo.
        pause
        exit /b 1
    )
) else (
    echo   [1/4] App already exists.
)

REM --- 2. the disk the database lives on --------------------------------
flyctl volumes list -a "%APP%" 2>nul | findstr /C:"vondo_data" >nul
if errorlevel 1 (
    echo   [2/4] Creating the 1 GB volume for vondo.db...
    flyctl volumes create vondo_data -a "%APP%" -r %REGION% -n 1 -s 1 --yes
) else (
    echo   [2/4] Volume already exists.
)

REM --- 3. keys ----------------------------------------------------------
REM  Read out of .env and pushed as Fly secrets, so they live in Fly's
REM  vault rather than in the image or in git.
echo   [3/4] Pushing secrets...
python scripts\push_secrets.py
if errorlevel 1 (
    echo   Could not set secrets. Is flyctl on PATH?
    pause
    exit /b 1
)

REM --- 4. ship it -------------------------------------------------------
echo   [4/4] Building and deploying...
flyctl deploy -a "%APP%" --ha=false

if errorlevel 1 (
    echo.
    echo   Deploy failed. See what happened with:   flyctl logs -a %APP%
    pause
    exit /b 1
)

echo.
echo   Done.  https://%APP%.fly.dev
echo.
echo   Next:
echo     1. Open that address on your phone and pair it with the secret above.
echo     2. On this PC:  set VONDO_URL=https://%APP%.fly.dev
echo        then run link_pc.bat and start_agent.bat
echo.
pause
