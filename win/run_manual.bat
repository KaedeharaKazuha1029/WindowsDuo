@echo off
REM Manual mode: no ESP needed. Up/Down = glass +/-, Right = 100%, Left = clear, Esc = quit.
"%~dp0..\.venv\Scripts\python.exe" -u "%~dp0glass_overlay.py" --manual
pause
