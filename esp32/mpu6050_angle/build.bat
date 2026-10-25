@echo off
REM ============================================================
REM  WindowsDuo firmware: build / flash wrapper   (ASCII ONLY!)
REM  .bat must stay ASCII: cmd decodes it as GBK and would run
REM  mojibake as commands (see AGENTS.md rule 4).
REM
REM  Usage:
REM    build.bat                      -> build
REM    build.bat -p COM5 flash monitor
REM    build.bat set-target esp32s3
REM ============================================================
setlocal

set "PYEXE="
for /f "delims=" %%F in ('dir /b /s /o-n "D:\Espressif\python_env\idf*_env\Scripts\python.exe" 2^>nul') do (
    if not defined PYEXE set "PYEXE=%%F"
)

if not defined PYEXE (
    echo [ERROR] ESP-IDF python env not found:
    echo         D:\Espressif\python_env\idf*_env\Scripts\python.exe
    echo         Install ESP-IDF first: https://dl.espressif.com/dl/esp-idf/
    pause
    exit /b 1
)

echo [INFO] python : %PYEXE%
echo [INFO] args   : %*
echo.

"%PYEXE%" "%~dp0run_build.py" %*
if errorlevel 1 (
    echo.
    echo [ERROR] idf.py failed. See messages above.
    pause
    exit /b 1
)

echo.
echo [OK] done.
