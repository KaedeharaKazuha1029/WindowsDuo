@echo off
REM ESP-IDF v5.4.4 环境加载 + 编译 + 烧录 (COM3)
call D:\Espressif\idf_cmd_init.bat esp32
if errorlevel 1 exit /b 1
cd /d D:\KaiFa\find\duo\esp32\mpu6050_angle
python %IDF_PATH%\tools\idf.py set-target esp32
if errorlevel 1 exit /b 1
python %IDF_PATH%\tools\idf.py build
if errorlevel 1 exit /b 1
echo BUILD_OK
