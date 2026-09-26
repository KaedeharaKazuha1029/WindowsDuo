@echo off
REM Manual mode: no ESP needed. Up/Down = glass +/-  Right = 100%  Left = clear  Esc = quit.
cd /d "%~dp0"
where py >nul 2>nul && (set "PY=py -3.14") || (set "PY=python")
%PY% -u glass_overlay.py --manual %*
pause
