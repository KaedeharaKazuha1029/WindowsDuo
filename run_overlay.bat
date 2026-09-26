@echo off
REM Duo glass overlay: 自动挑选串口(ESP32 原生USB > CH340 > CP210x)。
REM 实时角度与状态打印在本窗口。Ctrl+C 或 Esc 退出。
cd /d "%~dp0"
where py >nul 2>nul && (set "PY=py -3.14") || (set "PY=python")
%PY% -u glass_overlay.py %*
pause
