"""
角度流调试查看器 v2（115200）
实时显示: 主轴角度 a | 副轴角度 b(判断安装方向用) | 进度条 | 频率 | 波动范围
按 Ctrl+C 退出。

用法:
  python debug_view.py                       # 自动挑一个看起来像本项目的串口
  python debug_view.py --port COM3           # 指定串口
  python debug_view.py --port COM3 --baud 115200
Windows 上也可以直接双击 debug_view.bat（会自动挑选装了 pyserial 的解释器）。
"""
import argparse
import json
import re
import sys
import time

import serial

BAR_W = 40
ANGLE_MIN, ANGLE_MAX = -10.0, 140.0
JSON_RE = re.compile(r"\{[^}]*\}")


def candidate_ports():
    """按"最可能是本项目那块板"排序的串口列表。

    优先级: Espressif 原生 USB(303A) > CH340(1A86) > CP210x(10C4) > 其它。
    与 win/glass_overlay.py 里的同名函数保持一致。
    """
    from serial.tools import list_ports
    try:
        ports = list(list_ports.comports())
    except Exception:  # noqa: BLE001
        return []

    def rank(p):
        hwid = (p.hwid or "").upper()
        if "303A" in hwid:
            return 0
        if "1A86" in hwid:
            return 1
        if "10C4" in hwid:
            return 2
        return 3

    return [p.device for p in sorted(ports, key=rank)]


def resolve_port(requested):
    """--port 给了就用它；没给就从候选里自动挑第一个。"""
    if requested:
        return requested
    cands = candidate_ports()
    if not cands:
        print("[错误] 没发现任何串口。请插好板子，或用 --port COMx 指定。")
        sys.exit(2)
    chosen = cands[0]
    if len(cands) > 1:
        print(f"[提示] 自动选择 {chosen}（候选: {', '.join(cands)}）。"
              f"选错了请用 --port COMx 指定。")
    else:
        print(f"[提示] 自动选择 {chosen}")
    return chosen


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def pose(a):
    if a < 20: return "近乎合盖"
    if a < 70: return "半开    "
    if a < 120: return "正常使用"
    return "全开    "


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None,
                    help="串口，例如 COM3；不填则自动挑一个最像本项目的串口")
    ap.add_argument("--baud", default=115200, type=int)
    args = ap.parse_args()

    port = resolve_port(args.port)

    ser = serial.Serial(port, args.baud, timeout=1)
    ser.reset_input_buffer()

    print(f"连接 {port} @ {args.baud}，Ctrl+C 退出")
    print("提示: 上电固件会先做 3 秒陀螺仪校准(保持静止)，之后才输出角度\n")

    frames = 0
    vmin, vmax = 1e9, -1e9
    prev = None
    t0 = time.time()
    a = b = 0.0

    try:
        while True:
            line = ser.readline().decode("utf-8", "ignore").strip()
            if not line:
                continue
            m = JSON_RE.search(line)
            if not m:
                print(f"\n[固件] {line[:110]}")
                continue
            try:
                data = json.loads(m.group(0))
                a = float(data["a"])
                b = float(data.get("b", 0.0))
            except (ValueError, KeyError):
                continue

            frames += 1
            vmin, vmax = min(vmin, a), max(vmax, a)
            el = time.time() - t0
            hz = frames / el if el > 0 else 0

            pos = int(clamp((a - ANGLE_MIN) / (ANGLE_MAX - ANGLE_MIN), 0, 1) * BAR_W)
            bar = "#" * pos + "." * (BAR_W - pos)
            if prev is None:
                prev = a
            arrow = "-" if abs(a - prev) < 0.05 else ("开盖 ->" if a > prev else "<- 合盖")
            print(f"\ra {a:7.2f}° [{bar}] {pose(a)} {arrow} | 副轴b {b:7.2f}° | "
                  f"{hz:5.1f}Hz 帧:{frames:<6} 区间[{vmin:6.1f},{vmax:6.1f}] ",
                  end="", flush=True)
            if abs(a - prev) >= 0.05:
                prev = a
    except KeyboardInterrupt:
        el = time.time() - t0
        print(f"\n\n--- 结束 --- 共 {frames} 帧 / {el:.1f}s ({frames/el if el else 0:.0f}Hz)，"
              f"主轴角度范围 [{vmin:.1f}, {vmax:.1f}]°")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
