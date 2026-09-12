"""读取 ESP32 串口角度输出，验证固件。用法: python read_serial.py [秒数=8]"""
import sys
import time

import serial

PORT = "COM3"
BAUD = 115200
DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0

ok = err = 0
vmin, vmax, vlast = 1e9, -1e9, None
t0 = time.time()

with serial.Serial(PORT, BAUD, timeout=1) as ser:
    ser.reset_input_buffer()
    while time.time() - t0 < DURATION:
        line = ser.readline().decode("ascii", "ignore").strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                a = float(line.split(":")[1].rstrip("}"))
            except (ValueError, IndexError):
                continue
            ok += 1
            vmin, vmax = min(vmin, a), max(vmax, a)
            if vlast is not None and abs(a - vlast) > 0.01:
                print(f"angle = {a:7.2f}")
            vlast = a
        else:
            err += 1
            if err < 6:
                print("[other]", line[:100])

hz = ok / DURATION
print(f"\n=== 统计: 收到 {ok} 帧角度 / {err} 行其他, 约 {hz:.0f} Hz, 范围 [{vmin:.1f}, {vmax:.1f}] deg ===")
