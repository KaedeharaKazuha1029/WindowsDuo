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

着色器为 GLSL 330 **core** (显式属性 + VAO/VBO)。旧的 330 compatibility 写法
(varying / gl_Vertex / fragColor) 在 Intel Windows 驱动上会被拒
("not available in current GLSL version"), 因为 Intel 的兼容模式只到 GLSL 1.20。

用法:
  run_overlay.bat   串口驱动 | run_manual.bat   键盘手动 (↑↓←→)
  --port COM5       手动指定串口 (默认 auto: 自动挑选 Espressif/CH340/CP210x)
  --selftest 无窗口自检 | --smoke 4s 全屏演示自退
"""
import ctypes
import json
import struct
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

# 中文控制台多为 GBK(cp936): 遇到编码不了的字符只替换, 不要让 print 抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:  # noqa
        pass

# 顶点着色器: GLSL 330 core, 属性位置与 _draw_quad 的 VAO 布局一致
VS = """#version 330 core
layout(location = 0) in vec2 aPos;
layout(location = 1) in vec2 aUV;
out vec2 vUV;
void main() {
    vUV = aUV;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

# Duo 折叠着色器: 逆投影 + Vogel 盘模糊 + mip LOD + 边缘覆盖率
FS_DUO = """#version 330 core
uniform sampler2D uTex;
uniform vec2  uRes;      // 截图尺寸 px
uniform float uTilt;     // 玻璃转角 (弧度), 0 = 贴合界面
uniform float uEyeZ;     // 眼睛到界面平面距离 px
uniform float uSpread;   // 单位间隙 → 模糊半径 (散射半角正切)
uniform float uDark;     // 单位模糊半径损失的光量
uniform int   uMaxTaps;
in vec2 vUV;
out vec4 fragColor;

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
        fragColor = vec4(texture(uTex, uvFlat).rgb, 1.0);
        return;
    }

    // 玻璃像素放到 3D: 绕底边铰链旋转 tilt, 上部向观察者抬升
    float d = p.y;                                    // 该像素到铰链的距离
    vec3 glass = vec3(p.x, d * cos(tilt), d * sin(tilt));
    vec3 eye   = vec3(uRes * 0.5, uEyeZ);             // 眼睛: 屏幕中心正前上方

    // 光线 eye -> glass 像素, 延长交到界面平面 z=0
    float depth = eye.z - glass.z;
    if (depth <= 1e-3) { fragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }
    float t   = eye.z / depth;
    vec2 hit  = eye.xy + (glass.xy - eye.xy) * t;     // 界面平面上的落点 (px, y 向上)

    // 玻璃与界面的间隙 → 模糊半径
    float gap    = glass.z;
    float radius = uSpread * gap;

    // 整个模糊核都在界面之外 → 黑
    if (hit.x < -radius || hit.x > uRes.x + radius ||
        hit.y < -radius || hit.y > uRes.y + radius) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0); return;
    }

    // 磨砂玻璃吸光: 与散射成正比地变暗 (iphone-duo / DuoLike 同款)
    float att = max(1.0 - uDark * radius, 0.0);

    vec2 uvHit = vec2(hit.x / uRes.x, 1.0 - hit.y / uRes.y);

    if (radius < 0.5) {
        fragColor = vec4(textureLod(uTex, uvHit, 0.0).rgb * att, 1.0);
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
    fragColor = vec4(c, 1.0);
}
"""


# ---------------------------------------------------------------- 串口线程
def candidate_ports():
    """按"最可能是本项目那块板"排序的可用串口列表。
    优先级: Espressif 原生 USB(303A) > CH340(1A86) > CP210x(10C4) > 其它。"""
    from serial.tools import list_ports
    try:
        ports = list(list_ports.comports())
    except Exception:  # noqa
        return []

    def rank(p):
        hw = (p.hwid or "").upper()
        if "303A" in hw:
            return 0
        if "1A86" in hw:
            return 1
        if "10C4" in hw:
            return 2
        return 3

    return [p.device for p in sorted(ports, key=rank)]


def is_auto(port):
    return port is None or str(port).strip().lower() in ("", "auto")


class AngleReader(threading.Thread):
    """串口读角度。port='auto' 时自动枚举候选端口, 端口被占用/拔插都能自愈。"""

    def __init__(self, port, baud):
        super().__init__(daemon=True)
        self.port, self.baud = port, baud
        self.active = None            # 当前实际连接的端口
        self.lock = threading.Lock()
        self.angle = None
        self.other = None
        self.fps = 0.0
        self.status = "connecting"
        self._stop = False

    def get(self):
        with self.lock:
            return self.angle, self.other, self.fps, self.status

    def _ports(self):
        """本次尝试要依次打开的端口列表。"""
        if not is_auto(self.port):
            return [str(self.port)]
        return candidate_ports()

    def run(self):
        import re
        pat = re.compile(r"\{[^}]*\}")
        while not self._stop:
            ports = self._ports()
            if not ports:
                self._set("未发现串口")
                time.sleep(2)
                continue

            for p in ports:
                if self._stop:
                    break
                try:
                    self._read_loop(p, pat)
                except (serial.SerialException, OSError) as e:
                    self.active = None
                    if is_auto(self.port):
                        self._set(f"{p} 不可用")
                    else:
                        self._set(f"打不开 {p} ({type(e).__name__})")
                    time.sleep(0.6 if is_auto(self.port) else 2)
            if not self._stop and is_auto(self.port):
                self._set("等待串口")
                time.sleep(0.5)

    def _read_loop(self, port, pat):
        """打开 port 持续读角度; 直到停止或被拔出(抛 SerialException)。"""
        with serial.Serial(port, self.baud, timeout=1) as ser:
            self.active = port
            self._set("connected " + port)
            buf = b""
            n, t0 = 0, time.time()
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


class HoldControl:
    """固定浓度 (--smoke 无头演示用): 不读键盘, 浓度保持不变, 否则会被键盘目标值拉回 0。"""

    quit_flag = False

    def __init__(self, value):
        self.value = float(value)

    def get(self):
        return self.value, "hold", False


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
        MSS = getattr(mss, "MSS", None) or mss.mss      # mss>=10 弃用了 mss.mss()
        with MSS() as sct:
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
        ctx = self.context()
        f = ctx.format()
        prof = f.profile()
        prof_i = getattr(prof, "value", prof)      # PyQt6 枚举要取 .value
        prof_name = {0: "NoProfile", 1: "CoreProfile",
                     2: "CompatibilityProfile"}.get(prof_i, prof)
        print("[GL] initializeGL, context =", ctx.isValid(),
              f.majorVersion(), f.minorVersion(), prof_name)

        self._gl_linked = False
        self.prog = QOpenGLShaderProgram(self)
        ok_v = self.prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VS)
        ok_f = self.prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, FS_DUO)
        linked = bool(ok_v and ok_f and self.prog.link())
        self._gl_linked = linked
        if not linked:
            # 不再让 paintGL 抛 GLError 直接把程序打死: 只打印并保持黑屏
            print("[GL] 着色器编译/链接失败:\n" + self.prog.log())
            print("[GL] 本项目着色器需要 OpenGL 3.3 core。若显卡驱动不支持, "
                  "请更新显卡驱动或换一台支持 GL 3.3 的机器。")
            self._gl_ready = True
            return
        self.prog.bind()

        # VAO/VBO (core profile 没有立即模式, 必须显式上传顶点)
        self.vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self.vao)
        self.vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        # 两个三角形组成全屏四边形: xy(位置) + uv, 与 VS 的 location 0/1 对应
        verts = (-1.0, -1.0, 0.0, 0.0,
                  1.0, -1.0, 1.0, 0.0,
                  1.0,  1.0, 1.0, 1.0,
                 -1.0,  1.0, 0.0, 1.0)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, 4 * len(verts),
                        struct.pack(f"{len(verts)}f", *verts), GL.GL_STATIC_DRAW)
        stride = 4 * 4
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(0))
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(8))
        GL.glBindVertexArray(0)

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
        if not getattr(self, "_gl_linked", False):
            # 着色器没链上: 画黑, 不调 uniform (否则 GLError 1282 会终止程序)
            GL.glClearColor(0, 0, 0, 1)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
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
        GL.glBindVertexArray(self.vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_FAN, 0, 4)
        GL.glBindVertexArray(0)

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
def arg_value(name, default=None):
    """取 `--name value` 形式的命令行参数。"""
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    smoke = "--smoke" in sys.argv
    selftest = "--selftest" in sys.argv
    manual = "--manual" in sys.argv

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    # core profile: Intel Windows 驱动的兼容模式只到 GLSL 1.20,
    # 330 compatibility 着色器会被拒, 因此统一走 core。
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    screen = app.primaryScreen()
    dpr = screen.devicePixelRatio()
    geom = screen.geometry()
    region = {"left": geom.x(), "top": geom.y(),
              "width": int(geom.width() * dpr), "height": int(geom.height() * dpr)}

    port_cfg = arg_value("--port", CFG.get("port", "auto"))
    baud = int(CFG.get("baud", 115200))

    kb = ManualControl()
    kb.start()
    if manual:
        reader = None
        print("[手动模式] 不连接 ESP")
    else:
        reader = AngleReader(port_cfg, baud)
        reader.start()

    capturer = CaptureWorker(region)
    capturer.start()

    print("=" * 60)
    print("iPhone Duo 悬浮玻璃 · Windows 端 v3.1 (OpenGL 3.3 core)")
    print(f"  铰链=屏幕底边  最大转角 {CFG.get('max_tilt_deg')}°  眼距 {CFG.get('eye_dist_h')}x屏高")
    print(f"  blur_spread={CFG.get('blur_spread')}  darkening={CFG.get('darkening')}  "
          f"taps<={CFG.get('max_taps')}")
    if reader is not None:
        if is_auto(port_cfg):
            cands = candidate_ports()
            print(f"  串口: 自动  (当前候选: {', '.join(cands) if cands else '无'})")
        else:
            print(f"  串口: {port_cfg} @{baud}")
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
        ser_ok = manual or angle is not None
        ok = (frame is not None) and ser_ok
        print(f"[自检] 串口: {st} angle={angle} fps={fps:.0f} | "
              f"截屏: {'OK %dx%d' % (frame[1], frame[2]) if frame else 'FAIL'}"
              f"  => {'PASS' if ok else 'FAIL'}")
        if not ser_ok and not manual:
            print("      串口没有角度数据: 确认板子已烧本项目固件, 且端口未被")
            print("      其它程序(Thonny/Arduino 串口监视器)占用; 也可用 --port COMx 指定。")
        return 0 if ok else 1

    g_smoke = float(arg_value("--g", 0.85))
    widget = GlassGLWidget(screen, reader, capturer,
                           manual=HoldControl(g_smoke) if smoke else kb)

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
                MSS = getattr(_mss, "MSS", None) or _mss.mss
                with MSS() as sct2:
                    shot = sct2.grab(region)
                    out2 = str(Path(__file__).with_name("smoke_frame.png"))
                    _Image.frombytes("RGB", shot.size, shot.rgb).save(out2)
                print(f"[smoke] 整屏帧: {out2}")
            except Exception as e:
                print("[smoke] dump fail:", e)
            app.quit()

        # 调试: 关闭后台重截(截图里会包含 Overlay 自身, 多次重截会反馈污染成纯色)
        widget.refresh_hz = 0.0
        widget.g = g_smoke
        QTimer.singleShot(2000, dump_and_quit)
        widget.show()
        widget.shown = True
        capturer.kick()
    else:
        widget.show()
        widget.shown = True
        capturer.kick()

    # 着色器没链上就别留着全屏黑屏窗口让人莫名其妙
    if not smoke:
        def check_gl():
            if not getattr(widget, "_gl_linked", False):
                print("\n[致命] 着色器未链接, 无法渲染。请更新显卡驱动。")
                app.exit(2)

        QTimer.singleShot(1500, check_gl)

    rc = app.exec()
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
