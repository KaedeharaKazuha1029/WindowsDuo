@echo off
REM Live viewer for MPU6050 angle stream (COM3 115200)
REM Press Ctrl+C to stop.
"D:\Espressif\python_env\idf5.4_py3.11_env\Scripts\python.exe" "%~dp0debug_view.py"
pause
