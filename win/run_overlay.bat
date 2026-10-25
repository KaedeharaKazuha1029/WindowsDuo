@echo off
REM Duo glass overlay, angle driven by the ESP32 over serial.
REM Picks the newest Python 3 that has all required packages, then runs the overlay.
REM Live angle/status is printed in this window. Ctrl+C or Esc to quit.
REM (Probes stdout instead of errorlevel: the py launcher returns a negative exit
REM  code for a missing version, which "if not errorlevel 1" would misread as success.)
cd /d "%~dp0"

set "PY="
set "DEPS=import PyQt6, OpenGL, mss, serial; print(1)"
for /f "delims=" %%i in ('py -3.14 -c "%DEPS%" 2^>nul') do set "PY=py -3.14"
if not defined PY for /f "delims=" %%i in ('py -3.13 -c "%DEPS%" 2^>nul') do set "PY=py -3.13"
if not defined PY for /f "delims=" %%i in ('py -3.12 -c "%DEPS%" 2^>nul') do set "PY=py -3.12"
if not defined PY for /f "delims=" %%i in ('py -3.11 -c "%DEPS%" 2^>nul') do set "PY=py -3.11"
if not defined PY for /f "delims=" %%i in ('py -3 -c "%DEPS%" 2^>nul') do set "PY=py -3"
if not defined PY for /f "delims=" %%i in ('python -c "%DEPS%" 2^>nul') do set "PY=python"

if not defined PY (
  echo [ERROR] No Python 3 found that has PyQt6 / PyOpenGL / mss / pyserial.
  echo         Install Python 3.9+ from python.org, then run:
  echo             python -m pip install PyQt6 PyOpenGL mss pyserial Pillow
  echo         Optional, for smoother capture ^(DXGI^):  python -m pip install dxcam numpy
  pause
  exit /b 1
)

echo Using interpreter: %PY%
%PY% -u glass_overlay.py %*
pause
