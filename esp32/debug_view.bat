@echo off
REM Live viewer for the MPU6050 angle stream (115200 baud).
REM Usage:  debug_view.bat [COMx] [baud]
REM Press Ctrl+C to stop.

set "PORT=%~1"
set "BAUD=%~2"

set "ARGS="
if not "%PORT%"=="" set "ARGS=--port %PORT%"
if not "%BAUD%"=="" set "ARGS=%ARGS% --baud %BAUD%"

set "PYCMD="
for /f "delims=" %%F in ('dir /b /s /o-n "D:\Espressif\python_env\idf*_env\Scripts\python.exe" 2^>nul') do (
    if not defined PYCMD set PYCMD="%%F"
)
if not defined PYCMD for /f "delims=" %%i in ('py -3 -c "import serial; print(1)" 2^>nul') do set PYCMD=py -3
if not defined PYCMD for /f "delims=" %%i in ('python -c "import serial; print(1)" 2^>nul') do set PYCMD=python

if not defined PYCMD (
    echo [ERROR] No Python found with pyserial installed.
    echo         Install it with:  python -m pip install pyserial
    pause
    exit /b 1
)

%PYCMD% "%~dp0debug_view.py" %ARGS%
pause
