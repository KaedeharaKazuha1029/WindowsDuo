"""IDF 环境包装器：在 Python 进程内设置 PATH/IDF_PATH，再执行 idf.py。

为什么需要它：ESP-IDF 的 export 脚本靠 PATH 传环境，而本机 shell 不透传 IDF 环境，
所以在 Python 里直接把环境设好再调 idf.py 最省事（原作者也是这么做的）。

本机适配：自动探测 D:\\Espressif 下的 IDF 版本、python 环境与各工具目录，
不再写死版本号与工程路径（原来写的是 IDF 5.4.4 + D:\\KaiFa\\find\\duo\\esp32）。

用法（必须用 IDF 自带的解释器，build.bat 会自动找）:
  D:\\Espressif\\python_env\\idf5.3_py3.11_env\\Scripts\\python.exe run_build.py build
  ... -p COM5 flash monitor | set-target esp32s3 | fullclean | menuconfig
"""
import glob
import os
import runpy
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:  # noqa
        pass

ESP_ROOT = os.environ.get("ESP_ROOT", r"D:\Espressif")
PROJ = os.path.dirname(os.path.abspath(__file__))


def pick(pattern, *sub, newest=True):
    """在 glob 结果里挑一个真实存在的目录（默认取版本号最大的那个）。"""
    hits = sorted(glob.glob(pattern))
    if newest:
        hits = list(reversed(hits))
    for h in hits:
        p = os.path.join(h, *sub)
        if os.path.isdir(p):
            return p
    return None


def main():
    if not os.path.isdir(ESP_ROOT):
        print(f"[ERROR] 没找到 ESP-IDF 安装目录: {ESP_ROOT}")
        print("        先装 ESP-IDF (Windows 安装器)，或用 ESP_ROOT 环境变量指定位置。")
        return 2

    idf_path = pick(os.path.join(ESP_ROOT, "frameworks", "esp-idf-v*"))
    if not idf_path:
        print(f"[ERROR] {ESP_ROOT}\\frameworks 下没有 esp-idf-v*，请先安装 ESP-IDF。")
        return 2

    py_env = pick(os.path.join(ESP_ROOT, "python_env", "idf*_env"))
    if not py_env:
        print(f"[WARN] 没找到 {ESP_ROOT}\\python_env\\idf*_env，"
              f"idf.py 可能缺少依赖（建议用 IDF 自带解释器运行本脚本）。")

    tools = [
        os.path.join(py_env, "Scripts") if py_env else None,
        pick(os.path.join(ESP_ROOT, r"tools\xtensa-esp-elf\*\xtensa-esp-elf\bin")),
        pick(os.path.join(ESP_ROOT, r"tools\riscv32-esp-elf\*\riscv32-esp-elf\bin")),
        pick(os.path.join(ESP_ROOT, r"tools\cmake\*\bin")),
        pick(os.path.join(ESP_ROOT, r"tools\ninja\*")),
        pick(os.path.join(ESP_ROOT, r"tools\idf-exe\*")),
        pick(os.path.join(ESP_ROOT, r"tools\idf-git\*\cmd")),
        pick(os.path.join(ESP_ROOT, r"tools\ccache\*")),
        pick(os.path.join(ESP_ROOT, r"tools\esp32ulp-elf\*\esp32ulp-elf\bin")),
    ]

    os.environ["IDF_PATH"] = idf_path
    if py_env:
        os.environ["IDF_PYTHON_ENV_PATH"] = py_env

    rom_elf = pick(os.path.join(ESP_ROOT, r"tools\esp-rom-elfs\*"))
    if rom_elf:
        os.environ["ESP_ROM_ELF_DIR"] = rom_elf + os.sep

    ocd = pick(os.path.join(ESP_ROOT,
                            r"tools\openocd-esp32\*\openocd-esp32\share\openocd\scripts"))
    if ocd:
        os.environ["OPENOCD_SCRIPTS"] = ocd

    os.environ["PATH"] = ";".join(t for t in tools if t) + ";" + os.environ.get("PATH", "")

    print(f"[env] IDF      : {idf_path}")
    print(f"[env] python   : {py_env or '(当前解释器)'}")
    print(f"[env] project  : {PROJ}")
    os.chdir(PROJ)

    sys.argv = ["idf.py"] + sys.argv[1:]
    sys.path.insert(0, os.path.join(idf_path, "tools"))
    runpy.run_path(os.path.join(idf_path, "tools", "idf.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
