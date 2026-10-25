# -*- coding: utf-8 -*-
"""
MPU6050 角度读取 · CircuitPython 版（YD-ESP32-S3 N16R8）
=========================================================
功能与 ESP-IDF 版 (esp32/mpu6050_angle) 完全等价：
  1. I2C 初始化 + WHO_AM_I 校验（未接线时每 2 秒重试，不中断）
  2. 陀螺仪零漂校准：3 秒采样 + 静止检测，晃动就自动重来
  3. 100Hz 输出 JSON 行: {"a":Y轴角度,"b":X轴角度}
     —— 两个轴都做了互补滤波（ESP-IDF 版只对 a 做滤波、b 是原始加速度角）

不需要任何第三方库：直接读写 MPU6050 寄存器，只用到 board / busio / math / time。

接线（与 ESP-IDF 版相同）：
  MPU6050 VCC->3V3  GND->GND  SCL->GPIO9  SDA->GPIO8  AD0->GND或悬空(0x68)
  INT/XDA/XCL 不接

放到板子的 CIRCUITPY 盘根目录，文件名必须是 code.py（或 main.py）。
Windows 端无需改动：JSON 格式、a/b 轴含义、标定值（axis=b / angle_open / angle_closed）都沿用。
"""
import math
import time

import board
import busio
import supervisor

# ---------------- 配置 ----------------
SDA_PIN = board.GPIO8
SCL_PIN = board.GPIO9
I2C_FREQ = 400000          # 读失败多/线太长时降到 100000

MPU_ADDR = 0x68            # AD0 接地或悬空 = 0x68（接 3V3 会变 0x69）
SAMPLE_HZ = 100            # 想省电/降负载可降到 50（Windows 端照样能用）
SAMPLE_DT = 1.0 / SAMPLE_HZ
PERIOD_NS = int(1_000_000_000 / SAMPLE_HZ)

CF_GYRO = 0.98             # 互补滤波权重
CF_ACC = 0.02
OUT_ALPHA = 0.3            # 输出 EMA 平滑
ACC_LP_ALPHA = 0.2         # 加速度计角度低通

REG_SMPLRT_DIV = 0x19
REG_CONFIG = 0x1A
REG_GYRO_CFG = 0x1B
REG_ACCEL_CFG = 0x1C
REG_PWR_MGMT1 = 0x6B
REG_WHO_AM_I = 0x75
REG_ACCEL_XOUT = 0x3B
# --------------------------------------

# busio.I2C 的参数顺序是 (scl, sda)，别写反
i2c = busio.I2C(SCL_PIN, SDA_PIN, frequency=I2C_FREQ)


def _connected():
    """主机是否开着串口。用于给 100Hz 的 JSON 输出做开关：
    USB CDC 缓冲写满时 print 会阻塞主循环，没人读的时候就别打。"""
    try:
        return bool(supervisor.runtime.serial_connected)
    except Exception:
        return True


def log(*args):
    """状态行（WHO_AM_I / 校准 / 报错）：无条件打印，量很少，不会拖慢循环。"""
    print(*args)


def log_periodic(*args):
    """周期性状态行：只在主机连着时打印。"""
    if _connected():
        print(*args)


def _lock():
    """busio.I2C 的 writeto / writeto_then_readfrom 都要求先锁定总线
    （Adafruit 的 I2CDevice 会内部帮你锁，裸用 busio 就得自己来）。"""
    while not i2c.try_lock():
        pass


def _w(reg, val):
    """写一个寄存器：一次发 [寄存器号, 数据]。"""
    _lock()
    try:
        i2c.writeto(MPU_ADDR, bytes([reg, val]))
    finally:
        i2c.unlock()


def _r(reg, n):
    """读 n 字节：先发寄存器号，再读（repeated start）。"""
    buf = bytearray(n)
    _lock()
    try:
        i2c.writeto_then_readfrom(MPU_ADDR, bytes([reg]), buf)
    finally:
        i2c.unlock()
    return buf


def _s16(buf, i):
    """大端有符号 16 位。注意：CircuitPython 的 int.from_bytes 不支持 signed= 关键字
    （会抛 NotImplementedError），所以手动做补码转换。"""
    v = (buf[i] << 8) | buf[i + 1]
    return v - 65536 if v & 0x8000 else v


def read_sample():
    """返回 (ax, ay, az [g], gx, gy, gz [deg/s])。"""
    d = _r(REG_ACCEL_XOUT, 14)
    return (_s16(d, 0) / 16384.0,      # ±2g
            _s16(d, 2) / 16384.0,
            _s16(d, 4) / 16384.0,
            _s16(d, 8) / 131.0,        # ±250dps
            _s16(d, 10) / 131.0,
            _s16(d, 12) / 131.0)


def acc_angle_y(ax, ay, az):
    """绕 Y 轴（= 主轴 a）"""
    return math.atan2(-ax, math.sqrt(ay * ay + az * az)) * 57.29578


def acc_angle_x(ax, ay, az):
    """绕 X 轴（= 副轴 b）"""
    return math.atan2(ay, math.sqrt(ax * ax + az * az)) * 57.29578


def mpu_init():
    """WHO_AM_I 只做提示，不做拒绝：
    本机这块模块实测是 0x70（MPU6500 系），而 MPU6500/6050/9250 的寄存器映射与
    量程换算一致，所以照同一套寄存器继续跑就行（ESP-IDF 版也是只打印不校验）。"""
    who = _r(REG_WHO_AM_I, 1)[0]
    names = {0x68: "MPU6050", 0x70: "MPU6500", 0x71: "MPU9250/MPU6515", 0x73: "MPU9255"}
    if who in names:
        log("[mpu] WHO_AM_I = 0x%02X (%s)" % (who, names[who]))
    else:
        log("[mpu] WHO_AM_I = 0x%02X（不是常见型号，仍按同一套寄存器继续）" % who)
    _w(REG_PWR_MGMT1, 0x00)
    time.sleep(0.05)
    _w(REG_SMPLRT_DIV, 0x00)
    _w(REG_CONFIG, 0x03)       # DLPF ~44Hz
    _w(REG_GYRO_CFG, 0x00)     # ±250dps
    _w(REG_ACCEL_CFG, 0x00)    # ±2g
    return True


def gyro_calibrate():
    """3 秒采样求陀螺仪零漂；检测到晃动就重来。"""
    n = int(3 * SAMPLE_HZ)
    while True:
        log(">>> 陀螺仪校准中... 请保持模块完全静止 3 秒 <<<")
        sx = sy = sz = 0.0
        a_min, a_max = 1e9, -1e9
        ok = True
        tick = time.monotonic_ns()
        for _ in range(n):
            try:
                ax, ay, az, gx, gy, gz = read_sample()
            except OSError as e:
                log("[mpu] 校准期间 I2C 读取失败(%s)，重试" % e)
                ok = False
                break
            sx += gx
            sy += gy
            sz += gz
            mag = math.sqrt(ax * ax + ay * ay + az * az)
            a_min = min(a_min, mag)
            a_max = max(a_max, mag)
            tick += int(1_000_000_000 / SAMPLE_HZ)
            while time.monotonic_ns() < tick:
                pass
        if ok and (a_max - a_min) <= 0.05:
            log("[mpu] 校准完成! 零漂偏移: gx=%.2f gy=%.2f gz=%.2f (deg/s)"
                % (sx / n, sy / n, sz / n))
            return sx / n, sy / n, sz / n
        if ok:
            log("[mpu] 检测到晃动(幅值波动 %.3fg)，重新校准..." % (a_max - a_min))
        time.sleep(0.5)


def main():
    while True:
        try:
            if mpu_init():
                break
        except OSError as e:
            log("[mpu] I2C 无应答 (%s)" % e)
        log("[mpu] MPU6050 未就绪。检查接线: VCC->3V3 GND->GND "
            "SCL->GPIO9 SDA->GPIO8，AD0 接 GND(地址 0x68)，2 秒后重试...")
        time.sleep(2)

    log("[mpu] MPU6050 初始化 OK [ESP32-S3 (YD-ESP32-S3 N16R8)] "
        "(I2C: SDA=GPIO8 SCL=GPIO9 @%dkHz)" % (I2C_FREQ // 1000))

    off_gx, off_gy, _off_gz = gyro_calibrate()

    log('[mpu] 开始输出角度 @%dHz: {"a":主轴,"b":副轴}' % SAMPLE_HZ)

    fy = fx = 0.0            # 互补滤波状态
    ay_lp = ax_lp = 0.0      # 加速度计角度低通
    a_out = b_out = 0.0      # EMA 后的输出
    first = True
    tick = time.monotonic_ns()
    t_report = time.monotonic()
    count = 0

    while True:
        try:
            ax, ay, az, gx, gy, gz = read_sample()
        except OSError as e:
            if time.monotonic() - t_report > 1.0:
                log("[mpu] I2C 读取失败(%s)，检查接线" % e)
                t_report = time.monotonic()
            tick = _sleep_until(tick)
            continue

        ang_y = acc_angle_y(ax, ay, az)
        ang_x = acc_angle_x(ax, ay, az)
        ay_lp += ACC_LP_ALPHA * (ang_y - ay_lp)
        ax_lp += ACC_LP_ALPHA * (ang_x - ax_lp)

        if first:
            fy, fx = ang_y, ang_x
            a_out, b_out = ang_y, ang_x
            first = False
        else:
            fy = CF_GYRO * (fy + (gy - off_gy) * SAMPLE_DT) + CF_ACC * ay_lp
            if abs(fy - ay_lp) > 45.0:
                fy = ay_lp
            fx = CF_GYRO * (fx + (gx - off_gx) * SAMPLE_DT) + CF_ACC * ax_lp
            if abs(fx - ax_lp) > 45.0:
                fx = ax_lp
            a_out += OUT_ALPHA * (fy - a_out)
            b_out += OUT_ALPHA * (fx - b_out)

        if _connected():
            # 与 ESP-IDF 版同格式；Windows 端用正则挑 {...} 行，诊断行会被忽略
            print('{"a":%.2f,"b":%.2f}' % (a_out, b_out))

        count += 1
        now = time.monotonic()
        if now - t_report >= 5.0:
            log_periodic("[mpu] 实测 %.1f Hz, a=%.2f b=%.2f" % (count / (now - t_report), a_out, b_out))
            count = 0
            t_report = now

        tick = _sleep_until(tick)


def _sleep_until(tick_ns):
    """把循环节拍钉在 SAMPLE_HZ，返回下一个节拍时间。

    注意：必须返回新值——Python 的 int 是按值传递，在函数里 `tick += ...`
    改的是局部变量，调用方的 tick 永远不前进，节拍会完全失效（会跑到 400+Hz，
    互补滤波的 DT 也就跟着错了）。
    """
    tick_ns += PERIOD_NS
    while time.monotonic_ns() < tick_ns:
        pass
    return tick_ns


main()
