"""macOS 屏幕捕获 — mss 的替代品, 关键是把 Overlay 自己排除出捕获。

win 端靠 SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) 解决"截图抓到自己
上一帧 → 反馈几帧后收敛成纯色"(AGENTS.md 坑 #3)。mac 上实测:

  NSWindow.setSharingType_(NSWindowSharingNone)  ->  无效, 仍被截到
  CGWindowListCreateImage + BelowWindow          ->  有效, 自身像素为 0

所以这里用 kCGWindowListOptionOnScreenBelowWindow, 以 Overlay 自己的 CGWindowID
为参照点, 只捕获"在我下面"的窗口。因为 Overlay 是置顶窗口, "我下面" = 其它全部。

需要「屏幕录制」权限。没授权时 macOS 不报错, 而是只返回壁纸和自己的窗口 ——
看起来像一张纯色图。所以 permission_ok() 会显式 preflight, 让失败可见。
"""
import threading
import time

import Quartz


def permission_ok():
    """是否已获得屏幕录制权限。"""
    return bool(Quartz.CGPreflightScreenCaptureAccess())


def request_permission():
    """触发系统授权弹窗 (只在首次询问时弹, 之后需手动去系统设置)。"""
    return bool(Quartz.CGRequestScreenCaptureAccess())


def _cgimage_to_bgra(img):
    """CGImage -> (bgra_bytes, width, height, row_stride_px)

    CGImage 每行可能有 padding (bytesPerRow > width*4), 上传纹理时要用
    GL_UNPACK_ROW_LENGTH 告诉 GL 真实行宽, 否则画面会斜切。
    """
    w = Quartz.CGImageGetWidth(img)
    h = Quartz.CGImageGetHeight(img)
    bpr = Quartz.CGImageGetBytesPerRow(img)
    provider = Quartz.CGImageGetDataProvider(img)
    data = Quartz.CGDataProviderCopyData(provider)
    return bytes(data), w, h, bpr // 4


class ScreenGrabber:
    """同步单次截屏, 排除指定窗口 (以及它上面的一切)。"""

    def __init__(self, rect=None):
        self.rect = rect if rect is not None else Quartz.CGRectInfinite
        self.exclude_window_id = None

    def grab(self):
        """返回 (bgra, w, h, row_px) 或 None。"""
        if self.exclude_window_id:
            option = Quartz.kCGWindowListOptionOnScreenBelowWindow
            ref = self.exclude_window_id
        else:
            option = Quartz.kCGWindowListOptionAll
            ref = Quartz.kCGNullWindowID
        img = Quartz.CGWindowListCreateImage(
            self.rect, option, ref,
            Quartz.kCGWindowImageBestResolution
            | Quartz.kCGWindowImageBoundsIgnoreFraming,
        )
        if img is None:
            return None
        return _cgimage_to_bgra(img)


class CaptureWorker(threading.Thread):
    """后台按需截屏。接口与 win 端 CaptureWorker 对齐: kick() / latest() / done。

    帧格式比 win 多一个 row_px (CGImage 行 padding), 见 _cgimage_to_bgra。
    """

    def __init__(self, rect=None):
        super().__init__(daemon=True)
        self.grabber = ScreenGrabber(rect)
        self.request = threading.Event()
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.frame = None          # (bgra, w, h, row_px, seq)
        self.busy = False
        self.error = None
        self._stop = False

    def set_exclude_window(self, cg_window_id):
        self.grabber.exclude_window_id = int(cg_window_id) if cg_window_id else None

    def latest(self):
        with self.lock:
            return self.frame

    def kick(self):
        if not self.busy:
            self.request.set()

    def stop(self):
        self._stop = True
        self.request.set()

    def run(self):
        seq = 0
        while not self._stop:
            self.request.wait()
            self.request.clear()
            if self._stop:
                break
            self.done.clear()
            self.busy = True
            try:
                got = self.grabber.grab()
                if got is None:
                    self.error = "CGWindowListCreateImage 返回 None"
                else:
                    bgra, w, h, row_px = got
                    seq += 1
                    with self.lock:
                        self.frame = (bgra, w, h, row_px, seq)
                    self.error = None
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
                print("[capture] error:", e)
            finally:
                self.busy = False
                self.done.set()
