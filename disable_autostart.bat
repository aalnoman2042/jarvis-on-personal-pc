@echo off
REM DISABLE: stop Jarvis from starting automatically at boot.
set "LAUNCHER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Jarvis.vbs"
if exist "%LAUNCHER%" (
    del "%LAUNCHER%"
    echo   [DISABLED] Jarvis will NO LONGER start automatically at boot.
    echo   Re-enable anytime with: enable_autostart.bat
) else (
    echo   Auto-start was already off. Nothing to change.
)
pause
