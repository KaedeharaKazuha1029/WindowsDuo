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

if not defined ESP_ROOT set "ESP_ROOT=D:\Espressif"
set "PYEXE="
if defined IDF_PYTHON_ENV_PATH if exist "%IDF_PYTHON_ENV_PATH%\Scripts\python.exe" set "PYEXE=%IDF_PYTHON_ENV_PATH%\Scripts\python.exe"
if not defined PYEXE for /f "delims=" %%D in ('dir /b /ad /o-n "%ESP_ROOT%\python_env\idf*_env" 2^>nul') do (
    if not defined PYEXE if exist "%ESP_ROOT%\python_env\%%D\Scripts\python.exe" set "PYEXE=%ESP_ROOT%\python_env\%%D\Scripts\python.exe"
)

if not defined PYEXE (
    echo [ERROR] ESP-IDF Python environment not found under "%ESP_ROOT%".
    echo         Set ESP_ROOT or open the ESP-IDF command prompt.
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
