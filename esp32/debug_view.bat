@echo off
REM Live viewer for the MPU6050 angle stream (115200 baud).
REM Usage:  debug_view.bat [COMx] [baud]
REM Press Ctrl+C to stop.

setlocal enabledelayedexpansion

set "PORT=%~1"
set "BAUD=%~2"

set "ARGS="
if not "%PORT%"=="" set "ARGS=--port %PORT%"
if not "%BAUD%"=="" set "ARGS=%ARGS% --baud %BAUD%"

REM Pick the first interpreter that actually has pyserial.
REM IDF interpreters are tried first (newest env first), but each one must
REM pass "import serial" -- otherwise we keep looking, ending with system Python.
set "PYCMD="

for /f "delims=" %%F in ('dir /b /s /o-n "D:\Espressif\python_env\idf*_env\Scripts\python.exe" 2^>nul') do (
    if not defined PYCMD (
        "%%F" -c "import serial" >nul 2>nul
        if not errorlevel 1 set PYCMD="%%F"
    )
)

if not defined PYCMD (
    py -3 -c "import serial" >nul 2>nul
    if not errorlevel 1 set PYCMD=py -3
)
if not defined PYCMD (
    python -c "import serial" >nul 2>nul
    if not errorlevel 1 set PYCMD=python
)

if not defined PYCMD (
    echo [ERROR] No Python found with pyserial installed.
    echo         Install it with:  python -m pip install pyserial
    pause
    exit /b 1
)

echo Using interpreter: !PYCMD!
!PYCMD! "%~dp0debug_view.py" %ARGS%
pause
