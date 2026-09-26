@echo off
REM Duo glass overlay: auto-picks the serial port (ESP32 native USB > CH340 > CP210x).
REM Live angle/status is printed in this window. Ctrl+C or Esc to quit.
cd /d "%~dp0"
where py >nul 2>nul && (set "PY=py -3.14") || (set "PY=python")
%PY% -u glass_overlay.py %*
pause
