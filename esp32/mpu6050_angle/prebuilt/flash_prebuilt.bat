@echo off
REM ============================================================
REM  Flash the PREBUILT firmware to another identical board.
REM  Target: YD-ESP32-S3 (N16R8) - 16MB flash, USB-Serial-JTAG
REM  No ESP-IDF needed: only esptool (pip install esptool).
REM
REM  ASCII ONLY (cmd decodes .bat as GBK; see AGENTS.md rule 4)
REM
REM  Usage:
REM    flash_prebuilt.bat COM3          write firmware (~2s)
REM    flash_prebuilt.bat COM3 erase    erase whole flash first (~30s)
REM
REM  STEP 1 (before running): put the board in ROM download mode
REM      hold BOOT, tap RESET, release BOOT
REM      the port CHANGES: PID becomes 303A:1001 (often still COM3,
REM      but a second board may get COM4/COM5 - check Device Manager)
REM  STEP 2 (after running): tap RESET once so the chip boots the app
REM ============================================================
setlocal
set "PORT=%~1"
set "DO_ERASE=%~2"
set "IMG=%~dp0WindowsDuo-esp32s3-n16r8.bin"

if not exist "%IMG%" (
    echo [ERROR] image not found: %IMG%
    pause
    exit /b 1
)

if "%PORT%"=="" (
    echo [ERROR] no COM port given.
    echo         Example:  flash_prebuilt.bat COM3
    echo.
    echo Current serial ports:
    powershell -NoProfile -Command "[System.IO.Ports.SerialPort]::GetPortNames()"
    pause
    exit /b 1
)

REM --- pick an interpreter that has esptool ---
set "PYCMD="
for /f "delims=" %%F in ('dir /b /s /o-n "D:\Espressif\python_env\idf*_env\Scripts\python.exe" 2^>nul') do (
    if not defined PYCMD set PYCMD="%%F"
)
if not defined PYCMD for /f "delims=" %%i in ('py -3 -c "import esptool; print(1)" 2^>nul') do set PYCMD=py -3
if not defined PYCMD for /f "delims=" %%i in ('python -c "import esptool; print(1)" 2^>nul') do set PYCMD=python
if not defined PYCMD (
    echo [ERROR] esptool not found. Install it with:
    echo             python -m pip install esptool
    pause
    exit /b 1
)

echo [INFO] image    : %IMG%
echo [INFO] port     : %PORT%
echo [INFO] python   : %PYCMD%
echo.

if /i "%DO_ERASE%"=="erase" (
    echo [1/2] erasing whole flash ...
    %PYCMD% -m esptool --chip esp32s3 --port %PORT% --before usb_reset --after no_reset erase_flash
    if errorlevel 1 goto fail
)

echo [1/1] writing firmware at 0x0 ...
%PYCMD% -m esptool --chip esp32s3 --port %PORT% --before usb_reset --after no_reset write_flash --flash_mode dio --flash_freq 80m --flash_size 16MB 0x0 "%IMG%"
if errorlevel 1 goto fail

echo.
echo [OK] flashed.
echo      Now TAP RESET on the board to boot the app.
echo      Then check the log with:
echo          python "%~dp0..\..\debug_view.py" --port %PORT%
echo.
pause
exit /b 0

:fail
echo.
echo [ERROR] flashing failed.
echo   - Is the board really in download mode? (hold BOOT, tap RESET, release BOOT)
echo   - Is the port correct / not held by another program (Thonny, monitor)?
echo   - Try again with erase:  flash_prebuilt.bat %PORT% erase
echo.
pause
exit /b 1
