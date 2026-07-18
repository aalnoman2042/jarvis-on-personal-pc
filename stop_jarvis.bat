@echo off
REM ============================================================
REM  POWER OFF Jarvis right now.
REM  Works even when Jarvis is running hidden in the background.
REM  (This does NOT disable auto-start; it just stops the running one.
REM   To stop it starting at boot too, run disable_autostart.bat.)
REM ============================================================
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*jarvis_gui.py*' -or $_.CommandLine -like '*vondo.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo.
echo   Jarvis has been powered off.
echo   Start it again with: start_jarvis.bat   (or reboot if auto-start is on)
echo.
timeout /t 2 >nul
