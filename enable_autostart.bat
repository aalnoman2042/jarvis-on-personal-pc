@echo off
REM ============================================================
REM  ENABLE: Jarvis starts automatically every time your PC boots
REM  AND remembers whether you left it on.
REM   - Left it running last time  -> it starts with your PC.
REM   - Powered it off last time   -> it stays off until you start it.
REM  On boot it launches hidden and says "Welcome back, Rohan. System booting."
REM  Double-click this file once. To turn it off: disable_autostart.bat
REM ============================================================
cd /d "%~dp0"
python -c "import actions; print(actions.set_autostart('enable'))"
if errorlevel 1 (
    echo.
    echo   [ERROR] Could not set up auto-start with Python.
    echo   Make sure "python vondo.py" runs first, then try again.
    echo.
    pause
    exit /b 1
)
echo.
echo   [ENABLED] Jarvis will start with your PC unless you powered it off.
echo   On boot it says: "Welcome back, Rohan. System booting."
echo.
echo   Power Off (button / closing the window) makes it stay off next boot.
echo   To remove auto-start entirely, double-click: disable_autostart.bat
echo.
pause
