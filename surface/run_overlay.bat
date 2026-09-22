@echo off
REM Duo glass overlay (Windows gyrometer). Live angle is printed in this window.
"%~dp0..\.venv\Scripts\python.exe" -u "%~dp0glass_overlay.py"
pause
