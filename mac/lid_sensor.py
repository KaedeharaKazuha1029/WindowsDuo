"""macOS 开合角传感器 — ESP32 + MPU6050 的原生替代品。

MacBook 自带一个上报屏幕开合角的 Apple HID 设备，所以 mac 端**不需要外接硬件**。
设备匹配三元组: VendorID 0x05AC (Apple) / DeviceUsagePage 0x20 / DeviceUsage 0x8A。
角度通过 kIOHIDReportTypeFeature (=2) 的 feature report 读出, 有两种:

  report 7: 5 字节 [0x07, b0, b1, b2, b3]  小端, 单位 0.01°  (优先)
  report 1: 3 字节 [0x01, lo, hi]          小端, 单位 1°     (兜底)

不是所有机型都声明 report 7, 所以开机时依次试探, 谁先读出合法值就用谁。
读取无需任何权限 (与屏幕捕获不同), 传感器约每 100ms 刷新一次。
0° = 合盖, MacBook 大约能开到 130°。

协议细节参考 sumimakito/Mac-Duo 的 LidAngleSensor.swift (Apache-2.0);
此处为 Python/ctypes 独立实现, 未复制其代码。

坑: 外接显示器可能声明同样的 usage 但恒读 0, 所以必须用 BuiltIn 属性筛掉;
    个别机型 BuiltIn 属性缺失 (返回 None), 此时退化为"能读出合法角度就认"。
"""
import ctypes
import threading
import time

import objc
from Foundation import NSDictionary

_IOKIT = "/System/Library/Frameworks/IOKit.framework/IOKit"
_CF = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"

kIOHIDReportTypeFeature = 2
kIOReturnSuccess = 0

# report id -> (最小字节数, 除数)
_FORMATS = ((7, 5, 100.0), (1, 3, 1.0))


class LidAngleSensor:
    """读 MacBook 屏幕开合角。用法: s = LidAngleSensor(); s.angle() -> float | None"""

    def __init__(self):
        self._iokit = ctypes.cdll.LoadLibrary(_IOKIT)
        self._cf = ctypes.cdll.LoadLibrary(_CF)
        self._bind()
        self._buf = (ctypes.c_uint8 * 64)()
        self._device = None
        self._report_id = None
        self._divisor = None
        self._min_len = None
        self.last_error = None
        self._open()

    # ---------------------------------------------------------------- ctypes
    def _bind(self):
        k, c = self._iokit, self._cf
        k.IOHIDManagerCreate.restype = ctypes.c_void_p
        k.IOHIDManagerCreate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.IOHIDManagerSetDeviceMatching.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k.IOHIDManagerOpen.restype = ctypes.c_int
        k.IOHIDManagerOpen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.IOHIDManagerClose.restype = ctypes.c_int
        k.IOHIDManagerClose.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.IOHIDManagerCopyDevices.restype = ctypes.c_void_p
        k.IOHIDManagerCopyDevices.argtypes = [ctypes.c_void_p]
        k.IOHIDDeviceGetReport.restype = ctypes.c_int
        k.IOHIDDeviceGetReport.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_long,
            ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_long),
        ]
        c.CFSetGetCount.restype = ctypes.c_long
        c.CFSetGetCount.argtypes = [ctypes.c_void_p]
        c.CFSetGetValues.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        c.CFRelease.argtypes = [ctypes.c_void_p]

    @property
    def available(self):
        return self._device is not None and self._report_id is not None

    @property
    def resolution_name(self):
        if not self.available:
            return "unavailable"
        return f"report {self._report_id} ({1.0 / self._divisor:g}°)"

    # ---------------------------------------------------------------- 打开设备
    def _open(self):
        mgr = self._iokit.IOHIDManagerCreate(None, 0)
        if not mgr:
            self.last_error = "IOHIDManagerCreate 失败"
            return
        match = NSDictionary.dictionaryWithDictionary_(
            {"VendorID": 0x05AC, "DeviceUsagePage": 0x20, "DeviceUsage": 0x8A}
        )
        self._iokit.IOHIDManagerSetDeviceMatching(
            mgr, ctypes.c_void_p(objc.pyobjc_id(match))
        )
        if self._iokit.IOHIDManagerOpen(mgr, 0) != kIOReturnSuccess:
            self.last_error = "IOHIDManagerOpen 失败"
            return
        self._manager = mgr

        devices = self._iokit.IOHIDManagerCopyDevices(mgr)
        if not devices:
            self.last_error = "没有匹配的 HID 设备 (本机可能没有开合角传感器)"
            return
        try:
            n = self._cf.CFSetGetCount(devices)
            arr = (ctypes.c_void_p * max(n, 1))()
            self._cf.CFSetGetValues(devices, arr)
            builtin, others = [], []
            for i in range(n):
                dev = arr[i]
                if self._is_builtin(dev):
                    builtin.append(dev)
                else:
                    others.append(dev)
            # 优先内置设备; BuiltIn 缺失的机型退化到"能读出合法值就认"
            for dev in builtin + others:
                for rid, min_len, div in _FORMATS:
                    self._device, self._report_id = dev, rid
                    self._min_len, self._divisor = min_len, div
                    if self.angle() is not None:
                        return
            self._device = self._report_id = None
            self.last_error = "找到设备但没有一个 report 能读出合法角度"
        finally:
            self._cf.CFRelease(devices)

    def _is_builtin(self, dev):
        try:
            obj = objc.objc_object(c_void_p=dev)
            val = obj.propertyForKey_("BuiltIn")
            return bool(val) if val is not None else False
        except Exception:
            return False

    # ---------------------------------------------------------------- 读角度
    def angle(self):
        """当前开合角 (度)。读失败返回 None, 原因在 last_error。"""
        if self._device is None or self._report_id is None:
            return None
        length = ctypes.c_long(len(self._buf))
        rc = self._iokit.IOHIDDeviceGetReport(
            self._device, kIOHIDReportTypeFeature, self._report_id,
            self._buf, ctypes.byref(length),
        )
        if rc != kIOReturnSuccess or length.value < self._min_len:
            self.last_error = f"IOHIDDeviceGetReport status={rc} len={length.value}"
            return None
        raw = self._buf[: length.value]
        if raw[0] != self._report_id:
            self.last_error = f"report id 不匹配: {raw[0]}"
            return None
        if self._report_id == 7:
            v = raw[1] | raw[2] << 8 | raw[3] << 16 | raw[4] << 24
        else:
            v = raw[1] | raw[2] << 8
        deg = v / self._divisor
        if not (0.0 <= deg <= 360.0):
            self.last_error = f"角度越界: {deg}"
            return None
        self.last_error = None
        return deg

    def close(self):
        mgr = getattr(self, "_manager", None)
        if mgr:
            self._iokit.IOHIDManagerClose(mgr, 0)
            self._manager = None


class LidAngleReader(threading.Thread):
    """后台轮询开合角, 接口与 win 端 AngleReader.get() 对齐: (angle, other, hz, status)。

    传感器约 100ms 刷新, 但硬件读数有 ±0.3° 抖动, 所以做一次轻量 EMA;
    浓度侧还有一层平滑 (glass_overlay_mac 里的 self.g), 两层叠加足够稳。
    """

    def __init__(self, poll_hz=30.0, ema=0.35):
        super().__init__(daemon=True)
        self.interval = 1.0 / max(poll_hz, 1.0)
        self.ema = ema
        self.lock = threading.Lock()
        self.angle = None
        self.raw = None
        self.hz = 0.0
        self.status = "starting"
        self._stop = False
        self.sensor = None

    def get(self):
        with self.lock:
            return self.angle, self.raw, self.hz, self.status

    def stop(self):
        self._stop = True

    def run(self):
        try:
            self.sensor = LidAngleSensor()
        except Exception as e:  # noqa: BLE001
            with self.lock:
                self.status = f"sensor init failed: {e}"
            return
        if not self.sensor.available:
            with self.lock:
                self.status = f"no sensor ({self.sensor.last_error})"
            return
        with self.lock:
            self.status = self.sensor.resolution_name

        n, t0, smoothed = 0, time.time(), None
        while not self._stop:
            deg = self.sensor.angle()
            if deg is not None:
                smoothed = deg if smoothed is None else smoothed + (deg - smoothed) * self.ema
                n += 1
                with self.lock:
                    self.angle, self.raw = smoothed, deg
            now = time.time()
            if now - t0 >= 1.0:
                with self.lock:
                    self.hz = n / (now - t0)
                n, t0 = 0, now
            time.sleep(self.interval)
        self.sensor.close()
