"""
iPhone Duo「悬浮玻璃」· Windows 端 v3 (复刻着色器版)
================================================================
融合四个开源复刻的精华 (均为 MIT / 可移植):
  - elijah-semyonov/DuoLikeAnimation : 逆投影模型 + Vogel 盘模糊 (主体公式)
  - chuspeeism/iphone-duo            : mip LOD 分级采样 + 边缘覆盖率平滑
  - DhananjayBhosale/MacDuo          : 笔记本场景 (铰链 = 屏幕底边, 盖角度驱动)
  - askmaddyy/FrostFold              : 磨砂玻璃观感参数

模型: 界面固定在世界空间的平面上不动; 屏幕是一块玻璃, 绕"铰链"(屏幕底边)
向观察者方向转开。每个像素: 眼睛 → 玻璃像素 → 延长交到界面平面 = 采样点。
间隙越大 → 模糊半径越大、越暗; 视线完全出界 → 纯黑。这是空间效果:
靠近铰链处始终清晰, 远离铰链处(屏幕上部)先模糊、先消失。

线程:
  - AngleReader   : 串口 100Hz 读 {"a":..,"b":..}   (--manual 可脱离串口)
  - CaptureWorker : mss 截屏原始帧
  - GL 主线程     : 上传纹理(带 mipmap) → 单 pass Duo 折叠着色器
用法:
  run_overlay.bat   串口驱动 | run_manual.bat   键盘手动 (↑↓←→)
  --selftest 无窗口自检 | --smoke 4s 全屏演示自退
"""
import json
import sys
import threading
import time
from pathlib import Path

import mss
import serial
from OpenGL import GL
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication

CFG_PATH = Path(__file__).with_name("config.json")
CFG = json.loads(CFG_PATH.read_text("utf-8"))

VS = """#version 330 compatibility
varying vec2 vUV;
void main() {
    vUV = gl_MultiTexCoord0.xy;
    gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
}
"""

# Duo 折叠着色器: 逆投影 + Vogel 盘模糊 + mip LOD + 边缘覆盖率
FS_DUO = """#version 330 compatibility
uniform sampler2D uTex;
uniform vec2  uRes;      // 截图尺寸 px
uniform float uTilt;     // 玻璃转角 (弧度), 0 = 贴合界面
uniform float uEyeZ;     // 眼睛到界面平面距离 px
uniform float uSpread;   // 单位间隙 → 模糊半径 (散射半角正切)
uniform float uDark;     // 单位模糊半径损失的光量
uniform int   uMaxTaps;
varying vec2 vUV;

const float GOLDEN = 2.39996322972865332;
const float TWO_PI = 6.28318530717958648;

float hash21(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

void main() {
    // vUV: (0,0)=左下 (GL 约定)。铰链 = 屏幕底边。
    vec2 p = vUV * uRes;                 // y 自底向上, y=0 在铰链
    float tilt = uTilt;
    vec2 uvFlat = vec2(vUV.x, 1.0 - vUV.y);   // 平视采样 (截图行序 top-first)

    if (tilt < 1e-5) {
        gl_FragColor = vec4(texture(uTex, uvFlat).rgb, 1.0);
        return;
    }

    // 玻璃像素放到 3D: 绕底边铰链旋转 tilt, 上部向观察者抬升
    float d = p.y;                                    // 该像素到铰链的距离
    vec3 glass = vec3(p.x, d * cos(tilt), d * sin(tilt));
    vec3 eye   = vec3(uRes * 0.5, uEyeZ);             // 眼睛: 屏幕中心正前上方

    // 光线 eye -> glass 像素, 延长交到界面平面 z=0
    float depth = eye.z - glass.z;
    if (depth <= 1e-3) { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }
    float t   = eye.z / depth;
    vec2 hit  = eye.xy + (glass.xy - eye.xy) * t;     // 界面平面上的落点 (px, y 向上)

    // 玻璃与界面的间隙 → 模糊半径
    float gap    = glass.z;
    float radius = uSpread * gap;

    // 整个模糊核都在界面之外 → 黑
    if (hit.x < -radius || hit.x > uRes.x + radius ||
        hit.y < -radius || hit.y > uRes.y + radius) {
        gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); return;
    }

    // 磨砂玻璃吸光: 与散射成正比地变暗 (iphone-duo / DuoLike 同款)
    float att = max(1.0 - uDark * radius, 0.0);

    vec2 uvHit = vec2(hit.x / uRes.x, 1.0 - hit.y / uRes.y);

    if (radius < 0.5) {
        gl_FragColor = vec4(textureLod(uTex, uvHit, 0.0).rgb * att, 1.0);
        return;
    }

    // mip LOD (iphone-duo): 大半径先降到低分辨率 mip 再盘式采样
    float lod  = clamp(log2(max(radius, 1.0) / 16.0), 0.0, 6.0);
    float effR = radius / exp2(lod);

    // Vogel 盘 (DuoLike): sqrt 均匀面密度 + 黄金角 + 每像素随机旋转 → 磨砂颗粒
    int taps = int(clamp(effR * 2.0, 6.0, float(uMaxTaps)));
    float rot = hash21(gl_FragCoord.xy) * TWO_PI;

    // 边缘覆盖率 (iphone-duo): 采样核出界部分按比例衰减, 不出现硬边
    float footX = (radius + 1.0) / uRes.x;
    float footY = (radius + 1.0) / uRes.y;

    vec3 sum = vec3(0.0);
    for (int i = 0; i < taps; ++i) {
        float r = effR * sqrt((float(i) + 0.5) / float(taps));
        float a = float(i) * GOLDEN + rot;
        vec2 off = r * vec2(cos(a), sin(a));          // px, 界面平面坐标
        vec2 uv  = uvHit + vec2(off.x / uRes.x, -off.y / uRes.y);
        float cx = smoothstep(0.0, footX, uv.x) * (1.0 - smoothstep(1.0 - footX, 1.0, uv.x));
        float cy = smoothstep(0.0, footY, 1.0 - uv.y) * (1.0 - smoothstep(1.0 - footY, 1.0, 1.0 - uv.y));
        sum += textureLod(uTex, uv, lod).rgb * cx * cy;
    }
    vec3 c = sum / float(taps) * att;
    gl_FragColor = vec4(c, 1.0);
}
"""


# ---------------------------------------------------------------- 串口线程
class AngleReader(threading.Thread):
    def __init__(self, port, baud):
        super().__init__(daemon=True)
        self.port, self.baud = port, baud
        self.lock = threading.Lock()
        self.angle = None
        self.other = None
        self.fps = 0.0
        self.status = "connecting"
        self._stop = False

    def get(self):
        with self.lock:
            return self.angle, self.other, self.fps, self.status

    def run(self):
        import re
        pat = re.compile(r"\{[^}]*\}")
        n, t0 = 0, time.time()
        while not self._stop:
            try:
                with serial.Serial(self.port, self.baud, timeout=1) as ser:
                    self._set("connected")
                    buf = b""
                    while not self._stop:
                        buf += ser.readline()
                        if b"}" not in buf:
                            buf = buf[-64:] if len(buf) > 256 else buf
                            continue
                        line, buf = buf.rsplit(b"}", 1)
                        line = (line + b"}").decode("ascii", "ignore")
                        m = pat.search(line)
                        if not m:
                            continue
                        try:
                            d = json.loads(m.group(0))
                        except ValueError:
                            continue
                        with self.lock:
                            self.angle = float(d[CFG.get("axis", "a")])
                            self.other = float(d.get("b", 0.0))
                        n += 1
                        now = time.time()
                        if now - t0 >= 1:
                            with self.lock:
                                self.fps = n / (now - t0)
                            n, t0 = 0, now
            except (serial.SerialException, OSError):
                self._set("waiting " + self.port)
                time.sleep(2)

    def _set(self, s):
        with self.lock:
            self.status = s


# ---------------------------------------------------------------- 键盘控制
class ManualControl(threading.Thread):
    """键盘控制玻璃浓度: ↑/w +3%  ↓/s -3%  →/d 100%  ←/a 0%  r=角度自动  Esc 退出
    默认为手动覆盖模式 (target=0 即正常显示); 按 r 切换到跟随 ESP 角度。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.target = 0.0
        self.last_key = ""
        self.quit_flag = False
        self.auto = False          # False=键盘手动覆盖(默认) True=跟随角度

    def get(self):
        with self.lock:
            return self.target, self.last_key, self.auto

    def run(self):
        import msvcrt
        while not self.quit_flag:
            ch = msvcrt.getwch()
            if ch in ("\xe0", "\x00"):
                k = msvcrt.getwch()
                mapping = {"H": 0.03, "P": -0.03, "M": 1.0, "K": 0.0}
                delta = mapping.get(k)
                key = {"H": "↑", "P": "↓", "M": "→", "K": "←"}.get(k, k)
            else:
                if ch == "\x1b":
                    self.quit_flag = True
                    break
                if ch.lower() == "r":
                    with self.lock:
                        self.auto = not self.auto
                        self.last_key = "角度自动" if self.auto else "手动"
                    continue
                mapping = {"w": 0.03, "s": -0.03, "d": 1.0, "a": 0.0}
                delta = mapping.get(ch.lower())
                key = ch
            if delta is not None:
                with self.lock:
                    self.auto = False       # 任何调节键都切回手动覆盖
                    self.target = max(0.0, min(1.0, self.target + delta if abs(delta) < 0.5 else delta))
                    self.last_key = key


# ---------------------------------------------------------------- 截图线程
class CaptureWorker(threading.Thread):
    def __init__(self, region):
        super().__init__(daemon=True)
        self.region = region
        self.request = threading.Event()
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.frame = None          # (bytes, w, h, seq)
        self.busy = False

    def latest(self):
        with self.lock:
            return self.frame

    def kick(self):
        if not self.busy:
            self.request.set()

    def run(self):
        seq = 0
        with mss.mss() as sct:
            while True:
                self.request.wait()
                self.request.clear()
                self.done.clear()
                self.busy = True
                try:
                    shot = sct.grab(self.region)
                    raw = shot.raw                     # BGRA
                    seq += 1
                    with self.lock:
                        self.frame = (raw, shot.width, shot.height, seq)
                except Exception as e:  # noqa
                    print("[capture] error:", e)
                finally:
                    self.busy = False
                    self.done.set()


# ---------------------------------------------------------------- GL 窗口
class GlassGLWidget(QOpenGLWidget):
    def __init__(self, screen, reader, capturer, manual=None):
        super().__init__()
        self.reader = reader
        self.capturer = capturer
        self.manual = manual
        self.g = 0.0
        self.shown = False
        self._uploaded_seq = -1
        self._last_kick = 0.0
        self._last_print = 0.0
        self._locked = False
        self.angle_closed = float(CFG["angle_closed"])
        self.angle_open = float(CFG["angle_open"])
        self.glass_start = float(CFG.get("glass_start", 0.05))
        self.refresh_hz = float(CFG.get("refresh_hz", 3))
        self.max_tilt = float(CFG.get("max_tilt_deg", 88.0)) * 3.14159265 / 180.0
        self.eye_h = float(CFG.get("eye_dist_h", 2.0))       # 眼距 = 屏高倍数
        self.spread = float(CFG.get("blur_spread", 0.55))
        self.dark = float(CFG.get("darkening", 0.001))
        self.max_taps = int(CFG.get("max_taps", 32))

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry(screen.geometry())
        self.setWindowTitle("duo-glass")

    def showEvent(self, _ev):
        # 关键: 把自己从屏幕捕获中排除, 否则截图会抓到上一次的渲染结果,
        # 反馈几帧后收敛成一片纯色 ("白屏" 的根因之一)
        # --smoke 调试时设 _no_exclude=True, 便于抓屏验证渲染效果
        if getattr(self, "_no_exclude", False):
            return
        try:
            import ctypes
            WDA_EXCLUDEFROMCAPTURE = 0x11
            r = ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()),
                                                              WDA_EXCLUDEFROMCAPTURE)
            if not r:
                print("[警告] SetWindowDisplayAffinity 失败, 截图可能包含自身")
        except Exception as e:  # noqa
            print("[警告] 显示排除设置异常:", e)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    # ---------- GL ----------
    def initializeGL(self):
        print("[GL] initializeGL, context =", self.context().isValid(),
              self.context().format().majorVersion(), self.context().format().minorVersion())
        self.prog = QOpenGLShaderProgram(self)
        ok_v = self.prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VS)
        ok_f = self.prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, FS_DUO)
        if not (ok_v and ok_f and self.prog.link()):
            print("[GL] 着色器编译失败:\n", self.prog.log())
        self.prog.bind()

        self.cap_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.cap_tex)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER,
                           GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        self._gl_ready = True

    def paintGL(self):
        if not getattr(self, "_gl_ready", False):
            if not hasattr(self, "_warned_gl"):
                self._warned_gl = True
                print("[GL] paintGL 时 _gl_ready=False (initializeGL 未完成?)")
            return
        dpr = self.devicePixelRatioF()
        w = max(1, int(self.width() * dpr))
        h = max(1, int(self.height() * dpr))
        if not hasattr(self, "_painted_once"):
            self._painted_once = True
            frame0 = self.capturer.latest()
            print(f"[GL] paintGL 首帧: w={w} h={h} 截图帧={'有' if frame0 else '无'}")

        frame = self.capturer.latest()
        if frame and frame[3] != self._uploaded_seq:
            raw, fw, fh, seq = frame
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.cap_tex)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, fw, fh, 0,
                            GL.GL_BGRA, GL.GL_UNSIGNED_BYTE, raw)
            GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            self._uploaded_seq = seq

        if self._uploaded_seq == -1:
            GL.glClearColor(0, 0, 0, 1)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            return

        self.prog.bind()
        GL.glViewport(0, 0, w, h)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.cap_tex)
        GL.glUniform1i(self.prog.uniformLocation("uTex"), 0)
        GL.glUniform2f(self.prog.uniformLocation("uRes"), float(frame[1]), float(frame[2]))
        GL.glUniform1f(self.prog.uniformLocation("uTilt"), self.g * self.max_tilt)
        GL.glUniform1f(self.prog.uniformLocation("uEyeZ"), self.eye_h * frame[2])
        GL.glUniform1f(self.prog.uniformLocation("uSpread"), self.spread)
        GL.glUniform1f(self.prog.uniformLocation("uDark"), self.dark)
        GL.glUniform1i(self.prog.uniformLocation("uMaxTaps"), self.max_taps)
        self._draw_quad()

    def _draw_quad(self):
        GL.glBegin(GL.GL_QUADS)
        GL.glTexCoord2f(0.0, 0.0); GL.glVertex2f(-1.0, -1.0)
        GL.glTexCoord2f(1.0, 0.0); GL.glVertex2f(1.0, -1.0)
        GL.glTexCoord2f(1.0, 1.0); GL.glVertex2f(1.0, 1.0)
        GL.glTexCoord2f(0.0, 1.0); GL.glVertex2f(-1.0, 1.0)
        GL.glEnd()

    # ---------- 主循环 ----------
    def tick(self):
        if self.manual is not None:
            target_m, key, auto = self.manual.get()
            if self.manual.quit_flag:
                QApplication.quit()
        else:
            target_m, key, auto = 0.0, "", False

        angle = other = None
        fps, status = 0.0, "manual"
        if self.reader is not None:
            angle, other, fps, status = self.reader.get()

        if auto and angle is not None:
            lo, hi = self.angle_open, self.angle_closed
            ratio = (angle - lo) / (hi - lo) if hi != lo else 0.0
            target = 0.0 if ratio < self.glass_start else min(1.0, ratio)
            mode = "自动"
        else:
            target = target_m
            mode = "手动"
        self.g += (target - self.g) * 0.22

        # Overlay 常驻显示: 不再按浓度隐藏 (透明逻辑已按需求移除)
        if not self.shown:
            self.capturer.kick()
        else:
            now = time.time()
            if self.refresh_hz > 0 and now - self._last_kick >= 1.0 / self.refresh_hz:
                self._last_kick = now
                self.capturer.kick()
            self.update()
            if CFG.get("lock_at_close") and self.g > 0.985 and not self._locked:
                self._locked = True
                import ctypes
                ctypes.windll.user32.LockWorkStation()
            if self.g < 0.9:
                self._locked = False

        # 控制台实时单行重绘
        if time.time() - self._last_print > 0.1:
            self._last_print = time.time()
            if self.reader is not None:
                a = angle if angle is not None else float("nan")
                print(f"\r[{mode}] a={a:7.2f}° b={(other if other is not None else 0):7.2f}° "
                      f"浓度={self.g*100:5.1f}%  [{status} {fps:3.0f}Hz] "
                      f"↑↓调节 r=切自动 Esc退出 ", end="", flush=True)
            else:
                print(f"\r[{mode}] 玻璃={self.g*100:5.1f}%  "
                      f"[↑↓调节 ←清空 →拉满 r=切自动 Esc退出] ", end="", flush=True)


# ---------------------------------------------------------------- 入口
def main():
    smoke = "--smoke" in sys.argv
    selftest = "--selftest" in sys.argv
    manual = "--manual" in sys.argv

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    screen = app.primaryScreen()
    dpr = screen.devicePixelRatio()
    geom = screen.geometry()
    region = {"left": geom.x(), "top": geom.y(),
              "width": int(geom.width() * dpr), "height": int(geom.height() * dpr)}

    kb = ManualControl()
    kb.start()
    if manual:
        reader = None
        print("[手动模式] 不连接 ESP")
    else:
        reader = AngleReader(CFG["port"], int(CFG.get("baud", 115200)))
        reader.start()
    capturer = CaptureWorker(region)
    capturer.start()

    print("=" * 60)
    print("iPhone Duo 悬浮玻璃 · Windows 端 v3 (复刻着色器)")
    print(f"  铰链=屏幕底边  最大转角 {CFG.get('max_tilt_deg')}°  眼距 {CFG.get('eye_dist_h')}x屏高")
    print(f"  blur_spread={CFG.get('blur_spread')}  darkening={CFG.get('darkening')}  "
          f"taps<={CFG.get('max_taps')}")
    print("-" * 60)
    print("  默认=正常显示(浓度0)。先点一下本控制台窗口再按键!")
    print("  ↑/↓ 调浓度   ← 清空   → 拉满   r 切换角度自动跟随   Esc 退出")
    print("=" * 60)

    if selftest:
        time.sleep(4)
        angle, other, fps, st = reader.get() if reader else (None, None, 0.0, "manual")
        capturer.kick()
        capturer.done.wait(timeout=3)
        frame = capturer.latest()
        ok = (frame is not None) and (manual or angle is not None)
        print(f"[自检] 串口: {st} angle={angle} fps={fps:.0f} | "
              f"截屏: {'OK %dx%d' % (frame[1], frame[2]) if frame else 'FAIL'}"
              f"  => {'PASS ✔' if ok else 'FAIL ✘'}")
        return 0 if ok else 1

    widget = GlassGLWidget(screen, reader, capturer, manual=kb)

    print("[运行] Overlay 常驻显示。Ctrl+C 退出。")

    if smoke:
        def dump_and_quit():
            # 1) 直接抓 Overlay 自己的渲染内容 (不经过屏幕捕获, 无反馈污染)
            try:
                img = widget.grabFramebuffer()
                out1 = str(Path(__file__).with_name("smoke_widget.png"))
                img.save(out1)
                print(f"[smoke] grabFramebuffer: {out1} ({img.width()}x{img.height()})")
            except Exception as e:
                print("[smoke] grabFramebuffer fail:", e)
            try:
                img2 = widget.grab()
                out1b = str(Path(__file__).with_name("smoke_grab.png"))
                img2.save(out1b)
                print(f"[smoke] widget.grab: {out1b} ({img2.width()}x{img2.height()})")
            except Exception as e:
                print("[smoke] widget.grab fail:", e)
            # 2) 整屏参考帧
            try:
                import mss as _mss
                from PIL import Image as _Image
                with _mss.MSS() as sct2:
                    shot = sct2.grab(region)
                    out2 = str(Path(__file__).with_name("smoke_frame.png"))
                    _Image.frombytes("RGB", shot.size, shot.rgb).save(out2)
                print(f"[smoke] 整屏帧: {out2}")
            except Exception as e:
                print("[smoke] dump fail:", e)
            app.quit()

        # 调试: 关闭后台重截(截图里会包含 Overlay 自身, 多次重截会反馈污染成纯色)
        widget.refresh_hz = 0.0
        widget.g = 0.85
        QTimer.singleShot(2000, dump_and_quit)
        widget.show()
        widget.shown = True
        capturer.kick()
    else:
        widget.show()
        widget.shown = True
        capturer.kick()
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
