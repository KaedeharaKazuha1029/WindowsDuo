"""IDF 环境包装器：在 Python 进程内设置 PATH/IDF_PATH，再执行 idf.py。
用法: python run_build.py [idf.py 参数...]  例如: python run_build.py build
"""
import os
import runpy
import sys

TOOLS = [
    r"D:\Espressif\python_env\idf5.4_py3.11_env\Scripts",
    r"D:\Espressif\tools\xtensa-esp-elf\esp-14.2.0_20260121\xtensa-esp-elf\bin",
    r"D:\Espressif\tools\cmake\3.30.2\bin",
    r"D:\Espressif\tools\ninja\1.12.1",
    r"D:\Espressif\tools\idf-exe\1.0.3",
    r"D:\Espressif\tools\idf-git\2.44.0\cmd",
    r"D:\Espressif\tools\ccache\4.12.1",
]

os.environ["IDF_PATH"] = r"D:\Espressif\frameworks\esp-idf-v5.4.4"
os.environ["ESP_ROM_ELF_DIR"] = r"D:\Espressif\tools\esp-rom-elfs\20241011" + os.sep
os.environ["PATH"] = ";".join(TOOLS) + ";" + os.environ.get("PATH", "")
os.chdir(r"D:\KaiFa\find\duo\esp32\mpu6050_angle")

sys.argv = ["idf.py"] + sys.argv[1:]
sys.path.insert(0, os.path.join(os.environ["IDF_PATH"], "tools"))  # idf.py 同目录模块
runpy.run_path(os.path.join(os.environ["IDF_PATH"], "tools", "idf.py"), run_name="__main__")
