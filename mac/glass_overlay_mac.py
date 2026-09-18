"""iPhone Duo「悬浮玻璃」· macOS 端

把 win/glass_overlay.py 的上层实现搬到 mac, 接口层换成原生实现:

  角度来源   ESP32 + MPU6050 串口   ->  MacBook 自带开合角传感器 (mac/lid_sensor.py)
  屏幕捕获   mss                    ->  CGWindowListCreateImage  (mac/capture.py)
  自排除     SetWindowDisplayAffinity -> BelowWindow 参照自身窗口
  GL 管线    330 compatibility      ->  330 core + VAO/VBO (mac/shaders.py, gl_core.py)
  角度映射   线性 ratio             ->  意图识别状态机 (mac/lid_policy.py)
  键盘       msvcrt                 ->  termios 裸终端读取

逆投影着色器的数学与 win 端逐行一致, 只改了 GL 写法。

线程:
  LidAngleReader : 30Hz 轮询开合角 (无需权限)
  CaptureWorker  : CGWindowListCreateImage 抓帧
  GL 主线程      : 上传纹理(带 mipmap) -> 单 pass Duo 折叠着色器

用法:
  python mac/glass_overlay_mac.py            开合角驱动
  python mac/glass_overlay_mac.py --manual   键盘手动 (↑↓←→ r Esc)
  python mac/glass_overlay_mac.py --selftest  无窗口自检
  python mac/glass_overlay_mac.py --smoke     4s 演示后自退, 抓帧存 PNG

需要「屏幕录制」权限。没授权时 macOS 不报错, 只会返回壁纸 —— 所以启动时显式检查。
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import Quartz
from OpenGL import GL
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication

import capture
import gl_core
from lid_policy import LidEffectPolicy
from lid_sensor import LidAngleReader

CFG_PATH = Path(__file__).with_name("config.json")
CFG = json.loads(CFG_PATH.read_text("utf-8"))

DEG2RAD = 3.14159265358979 / 180.0


# ---------------------------------------------------------------- 键盘 (mac)
class ManualControl(threading.Thread):
    """键盘控制玻璃浓度。win 端用 msvcrt, mac 用 termios 裸终端。

    ↑/w +3%   ↓/s -3%   →/d 拉满   ←/a 清零   r 切自动   Esc/q 退出
    方向键是 ANSI 转义序列 ESC[A/B/C/D, 所以 Esc 要靠"后面没有跟 [ "来区分:
    读到 ESC 后用 select 等 50ms, 没有后续字节就当退出键。
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.target = 0.0
        self.last_key = ""
        self.quit_flag = False
        self.auto = False          # False=键盘手动(默认) True=跟随开合角
        self.enabled = sys.stdin.isatty()

    def get(self):
        with self.lock:
            return self.target, self.last_key, self.auto

    def _apply(self, delta, key):
        with self.lock:
            self.auto = False      # 任何调节键都切回手动
            if abs(delta) < 0.5:
                self.target = max(0.0, min(1.0, self.target + delta))
            else:
                self.target = delta
            self.last_key = key

    def run(self):
        if not self.enabled:
            return
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        try:
            old = termios.tcgetattr(fd)
        except termios.error:
            return
        try:
            tty.setcbreak(fd)
            while not self.quit_flag:
                if not select.select([fd], [], [], 0.2)[0]:
                    continue
                ch = os.read(fd, 1).decode("utf-8", "ignore")
                if not ch:
                    continue
                if ch == "\x1b":
                    # 方向键 ESC[A.. 还是单独的 Esc?
                    if select.select([fd], [], [], 0.05)[0]:
                        rest = os.read(fd, 2).decode("utf-8", "ignore")
                        mapping = {"[A": 0.03, "[B": -0.03, "[C": 1.0, "[D": 0.0}
                        names = {"[A": "↑", "[B": "↓", "[C": "→", "[D": "←"}
                        if rest in mapping:
                            self._apply(mapping[rest], names[rest])
                        continue
                    self.quit_flag = True
                    break
                low = ch.lower()
                if low == "q":
                    self.quit_flag = True
                    break
                if low == "r":
                    with self.lock:
                        self.auto = not self.auto
                        self.last_key = "角度自动" if self.auto else "手动"
                    continue
                mapping = {"w": 0.03, "s": -0.03, "d": 1.0, "a": 0.0}
                if low in mapping:
                    self._apply(mapping[low], ch)
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except termios.error:
                pass


# ---------------------------------------------------------------- GL 窗口
class GlassGLWidget(QOpenGLWidget):
    """全屏置顶悬浮层。必须继承 QOpenGLWidget (AGENTS.md 坑 #1)。"""

    def __init__(self, screen, reader, capturer, manual=None, policy=None):
        super().__init__()
        self.reader = reader
        self.capturer = capturer
        self.manual = manual
        self.policy = policy
        self.g = 0.0
        self.shown = False
        self._uploaded_seq = -1
        self._last_kick = 0.0
        self._last_print = 0.0
        self._gl_ready = False
        self._no_exclude = False

        self.shader = str(CFG.get("shader", "recede"))
        self.refresh_hz = float(CFG.get("refresh_hz", 6))
        self.eye_h = float(CFG.get("eye_dist_h", 6.0))
        self.recession = float(CFG.get("recession", 1.0))
        self.max_sep_deg = float(CFG.get("max_sep_deg", 88.0))
        self.spread = float(CFG.get("blur_spread", 0.42))
        self.max_dim = float(CFG.get("max_dim", 1.0))
        self.dim_floor = float(CFG.get("dim_floor", 0.2))
        self.dim_reach = float(CFG.get("dim_reach", 0.5))
        self.dim_curve = float(CFG.get("dim_curve", 1.6))
        self.max_taps = int(CFG.get("max_taps", 32))
        self.smoothing = float(CFG.get("smoothing", 0.22))

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry(screen.geometry())
        self.setWindowTitle("duo-glass")

    # ---------- 窗口层级 / 自排除 ----------
    def showEvent(self, _ev):
        """置顶到屏保层 + 覆盖所有 Space, 并把自己的 CGWindowID 交给截图线程排除。

        win 端靠 SetWindowDisplayAffinity 排除自己; mac 上 sharingType=None 实测无效,
        改用 BelowWindow 以自身窗口为参照 (mac/capture.py)。
        
        窗口 ID 获取可能需要等待 AppKit 完全初始化，所以用 QTimer 延迟重试。
        """
        self._install_native_window_props()
        if not self._no_exclude:
            # 延迟 100ms 重试，给 AppKit 时间更新窗口列表
            QTimer.singleShot(100, self._setup_window_exclusion)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    def _setup_window_exclusion(self):
        """延迟获取窗口 ID 并设置截图排除。"""
        wid = self._cg_window_id()
        if wid:
            self.capturer.set_exclude_window(wid)
        else:
            print("[警告] 拿不到 CGWindowID, 截图可能包含自身 (会反馈成纯色)")

    def _native_window(self):
        try:
            import AppKit
            for nw in AppKit.NSApp.windows():
                if nw.contentView() is not None and nw.isVisible():
                    return nw
        except Exception as e:  # noqa: BLE001
            print("[警告] 取 NSWindow 失败:", e)
        return None

    def _cg_window_id(self):
        nw = self._native_window()
        return int(nw.windowNumber()) if nw is not None else None

    def _install_native_window_props(self):
        nw = self._native_window()
        if nw is None:
            return
        try:
            import AppKit
            # 盖住菜单栏和 Dock; 屏保层足够高但不会挡住系统弹窗
            nw.setLevel_(AppKit.NSScreenSaverWindowLevel)
            nw.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | AppKit.NSWindowCollectionBehaviorStationary
                | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
                | AppKit.NSWindowCollectionBehaviorIgnoresCycle
            )
            nw.setIgnoresMouseEvents_(True)
            nw.setHasShadow_(False)
        except Exception as e:  # noqa: BLE001
            print("[警告] 设置窗口层级失败:", e)

    # ---------- GL ----------
    def initializeGL(self):
        fmt = self.context().format()
        print(f"[GL] {GL.glGetString(GL.GL_VERSION).decode()} | "
              f"profile={fmt.profile().name} {fmt.majorVersion()}.{fmt.minorVersion()}")
        try:
            self.prog = gl_core.compile_program(self.shader)
        except (RuntimeError, ValueError) as e:
            print(f"[GL] 着色器编译失败: {e}")
            print("[GL] 退回 duo 模式")
            self.shader = "duo"
            self.prog = gl_core.compile_program("duo")
        self.vao, _ = gl_core.make_quad()
        self.cap_tex = gl_core.make_texture()
        self._gl_ready = True

    def paintGL(self):
        if not self._gl_ready:
            return
        dpr = self.devicePixelRatioF()
        w = max(1, int(self.width() * dpr))
        h = max(1, int(self.height() * dpr))

        frame = self.capturer.latest()
        if frame and frame[4] != self._uploaded_seq:
            bgra, fw, fh, row_px, seq = frame
            gl_core.upload_bgra(self.cap_tex, bgra, fw, fh, row_px)
            self._uploaded_seq = seq

        if self._uploaded_seq == -1 or frame is None:
            GL.glClearColor(0, 0, 0, 1)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            return

        GL.glViewport(0, 0, w, h)
        GL.glUseProgram(self.prog)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.cap_tex)

        if self.shader == "recede":
            from depth_geometry import angle_from_strength, separation_params
            angle = angle_from_strength(
                self.g, float(CFG["threshold_angle"]), float(CFG["span_angle"]))
            sep, along, depth = separation_params(
                float(CFG["threshold_angle"]), angle, self.eye_h,
                self.recession, self.max_sep_deg, frame[2])
            progress = max(0.0, min(1.0, self.g))
            gl_core.set_recede_uniforms(
                self.prog, frame[1], frame[2], sep, along, depth, self.spread,
                progress, self.max_dim, self.dim_floor, self.dim_reach,
                self.dim_curve, self.max_taps)
        else:
            gl_core.set_uniforms(
                self.prog, frame[1], frame[2],
                tilt=self.g * 88.0 * DEG2RAD,
                eye_z=self.eye_h * frame[2],
                spread=self.spread, dark=0.001, max_taps=self.max_taps)
        gl_core.draw_quad(self.vao)

    # ---------- 主循环 ----------
    def tick(self):
        if self.manual is not None:
            target_m, _key, auto = self.manual.get()
            if self.manual.quit_flag:
                QApplication.quit()
                return
        else:
            target_m, auto = 0.0, True

        angle = None
        hz, status = 0.0, "manual"
        if self.reader is not None:
            angle, _raw, hz, status = self.reader.get()

        if auto and angle is not None and self.policy is not None:
            target, active = self.policy.update(angle)
            mode = "自动"
        else:
            target, active = target_m, target_m > 0
            mode = "手动"
        self.g += (target - self.g) * self.smoothing

        if not self.shown:
            self.capturer.kick()
        else:
            now = time.time()
            # 效果可见时才需要新帧; 完全透明时省电
            want = self.g > 0.002 or target > 0.002
            if want and self.refresh_hz > 0 and now - self._last_kick >= 1.0 / self.refresh_hz:
                self._last_kick = now
                self.capturer.kick()
            self.update()

        if time.time() - self._last_print > 0.1:
            self._last_print = time.time()
            if self.reader is not None:
                a = angle if angle is not None else float("nan")
                v = self.policy.velocity if self.policy else 0.0
                print(f"\r[{mode}] 开合角={a:6.2f}° v={v:+7.1f}°/s "
                      f"浓度={self.g * 100:5.1f}% {'●' if active else '○'} "
                      f"[{status} {hz:3.0f}Hz] ↑↓调节 r=切自动 Esc退出   ",
                      end="", flush=True)
            else:
                print(f"\r[{mode}] 浓度={self.g * 100:5.1f}%  "
                      f"[↑↓调节 ←清空 →拉满 Esc退出]   ", end="", flush=True)


# ---------------------------------------------------------------- 自检
def run_selftest(manual):
    print("=" * 62)
    print("自检: 传感器 / 屏幕录制权限 / 截图 / OpenGL Core profile")
    print("-" * 62)
    ok = True

    # 1. 开合角传感器
    reader = LidAngleReader(poll_hz=float(CFG.get("poll_hz", 30)))
    reader.start()
    time.sleep(1.2)
    angle, raw, hz, status = reader.get()
    if angle is None:
        print(f"  传感器 : FAIL  ({status})")
        print("           本机可能没有开合角传感器 (非 MacBook / 外接屏)。")
        print("           仍可用 --manual 键盘模式。")
        if not manual:
            ok = False
    else:
        print(f"  传感器 : OK    {angle:.2f}°  ({status}, {hz:.0f}Hz)")
    reader.stop()

    # 2. 权限
    if capture.permission_ok():
        print("  录屏权限: OK")
    else:
        print("  录屏权限: FAIL  未授予「屏幕录制」")
        print("           系统设置 → 隐私与安全性 → 屏幕录制, 勾选运行本程序的终端/App")
        ok = False

    # 3. 截图
    worker = capture.CaptureWorker()
    worker.start()
    worker.kick()
    worker.done.wait(timeout=5)
    frame = worker.latest()
    if frame is None:
        print(f"  截图   : FAIL  ({worker.error})")
        ok = False
    else:
        print(f"  截图   : OK    {frame[1]}x{frame[2]} (行宽 {frame[3]}px)")
    worker.stop()

    # 4. GL
    try:
        from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext
        surf = QOffscreenSurface()
        surf.create()
        ctx = QOpenGLContext()
        ctx.setFormat(QSurfaceFormat.defaultFormat())
        if not (ctx.create() and ctx.makeCurrent(surf)):
            raise RuntimeError("上下文创建失败")
        gl_core.compile_program()
        f = ctx.format()
        print(f"  OpenGL : OK    {GL.glGetString(GL.GL_VERSION).decode()} "
              f"({f.profile().name})")
    except Exception as e:  # noqa: BLE001
        print(f"  OpenGL : FAIL  {e}")
        ok = False

    print("-" * 62)
    print(f"  => {'PASS ✔' if ok else 'FAIL ✘'}")
    print("=" * 62)
    return 0 if ok else 1


# ---------------------------------------------------------------- 入口
def main():
    smoke = "--smoke" in sys.argv
    selftest = "--selftest" in sys.argv
    manual = "--manual" in sys.argv

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    # 不进 Dock, 不抢焦点
    try:
        import AppKit
        AppKit.NSApp.setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory
        )
    except Exception:  # noqa: BLE001
        pass

    if selftest:
        return run_selftest(manual)

    if not capture.permission_ok():
        print("=" * 62)
        print("需要「屏幕录制」权限才能捕获屏幕内容。")
        print("正在请求授权; 若没有弹窗, 请手动到:")
        print("  系统设置 → 隐私与安全性 → 屏幕录制")
        print("勾选运行本程序的终端 (或 Duo Glass.app), 然后重新运行。")
        print("=" * 62)
        capture.request_permission()
        if not capture.permission_ok():
            print("[退出] 权限未授予。")
            return 2

    screen = app.primaryScreen()

    reader = None
    policy = None
    if manual:
        print("[手动模式] 不读传感器")
    else:
        reader = LidAngleReader(poll_hz=float(CFG.get("poll_hz", 30)))
        reader.start()
        time.sleep(0.4)
        _a, _r, _hz, status = reader.get()
        if _a is None:
            print(f"[警告] 开合角传感器不可用 ({status}), 退回键盘手动模式。")
            reader.stop()
            reader = None
            manual = True
        else:
            policy = LidEffectPolicy(
                threshold=float(CFG.get("threshold_angle", 90.0)),
                span=float(CFG.get("span_angle", 60.0)),
                hysteresis=float(CFG.get("hysteresis", 4.0)),
                closing_speed=float(CFG.get("closing_speed", 8.0)),
                opening_speed=float(CFG.get("opening_speed", 8.0)),
                intent_memory=float(CFG.get("intent_memory", 2.0)),
                dwell_duration=float(CFG.get("dwell_duration", 0.35)),
                min_duration=float(CFG.get("min_duration", 0.25)),
                predict_ahead=float(CFG.get("predict_ahead", 0.12)),
            )

    kb = ManualControl()
    kb.auto = not manual
    kb.start()

    # Pass screen bounds to capturer so multi-display setups don't capture
    # the entire virtual desktop (CGRectInfinite)
    geom = screen.geometry()
    dpr = screen.devicePixelRatio()
    rect = Quartz.CGRectMake(
        geom.x() * dpr, geom.y() * dpr,
        geom.width() * dpr, geom.height() * dpr
    )
    capturer = capture.CaptureWorker(rect=rect)
    capturer.start()

    print("=" * 62)
    print("iPhone Duo 悬浮玻璃 · macOS 端")
    print(f"  铰链=屏幕底边  最大转角 {CFG.get('max_sep_deg')}°  "
          f"眼距 {CFG.get('eye_dist_h')}x屏高")
    print(f"  起效角 {CFG.get('threshold_angle')}°  跨度 {CFG.get('span_angle')}°  "
          f"blur_spread={CFG.get('blur_spread')}")
    print("-" * 62)
    if not manual:
        print("  合盖到 90° 以下开始起效, 越合越朦胧。开回去自动解除。")
    print("  ↑/↓ 调浓度   ← 清空   → 拉满   r 切换角度自动   Esc 退出")
    print("=" * 62)

    widget = GlassGLWidget(screen, reader, capturer, manual=kb, policy=policy)

    if smoke:
        widget._no_exclude = True    # 抓帧验证时不排除自己
        widget.refresh_hz = 0.0
        widget.g = 0.85

        def dump_and_quit():
            try:
                img = widget.grabFramebuffer()
                out = str(Path(__file__).with_name("smoke_widget.png"))
                img.save(out)
                print(f"\n[smoke] grabFramebuffer -> {out} "
                      f"({img.width()}x{img.height()})")
            except Exception as e:  # noqa: BLE001
                print("\n[smoke] grabFramebuffer 失败:", e)
            app.quit()

        QTimer.singleShot(2500, dump_and_quit)

    widget.show()
    widget.shown = True
    capturer.kick()
    rc = app.exec()
    capturer.stop()
    if reader:
        reader.stop()
    print()
    return rc


if __name__ == "__main__":
    sys.exit(main())
