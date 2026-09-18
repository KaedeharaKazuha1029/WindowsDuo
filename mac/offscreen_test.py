"""离屏验证 Core profile 版 Duo 折叠着色器 → PNG (不开窗口)。

对应 win/offscreen_test.py。按 AGENTS.md 坑 #6: 调着色器先离屏出图验证, 再上真窗口。

用法:
    python mac/offscreen_test.py [tilt_deg=60]
    python mac/offscreen_test.py --sweep      # 0/20/40/60/80° 一次出全套

判读要点 (合成图是等距白网格 + 左上绿块 + 右下黄块):
  - 底边 (铰链) 附近必须清晰, 越往上越模糊 —— 这是空间效果, 不是全屏均匀模糊
  - 网格线间距自下而上逐渐变密 (逆投影透视压缩)
  - 上部越模糊越暗; 视线出界处纯黑
  - 绿块在左上、黄块在右下, 位置不能左右或上下翻转
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from OpenGL import GL
from PIL import Image, ImageDraw
from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PyQt6.QtWidgets import QApplication

import gl_core

W, H = 960, 600
SRC_W, SRC_H = 1920, 1200


def make_test_texture():
    """合成测试图: 渐变底 + 白网格 + 角落色块, 方便判断模糊/翻转/取样方向。"""
    img = Image.new("RGB", (SRC_W, SRC_H))
    dr = ImageDraw.Draw(img)
    # 注意: 步长必须是 1。win 版用的是 range(0, W, 4), 于是每 4 列里有 3 列
    # 未绘制的纯黑 (源图 68.8% 是黑的)。这种条纹图做目测无妨, 但会让
    # "黑区占比"这类自动指标彻底失效 —— 量到的是纹路缝隙而不是视线出界,
    # 而且渲染后周期变成 2px, 抽样步长一旦跟它共振就会得出互相矛盾的数字。
    for x in range(SRC_W):
        c = (int(255 * x / SRC_W), 40, int(255 - 255 * x / SRC_W))
        dr.line([(x, 0), (x, SRC_H)], fill=c)
    for gx in range(0, SRC_W, 120):
        dr.line([(gx, 0), (gx, SRC_H)], fill=(255, 255, 255), width=3)
    for gy in range(0, SRC_H, 120):
        dr.line([(0, gy), (SRC_W, gy)], fill=(255, 255, 255), width=3)
    dr.rectangle([100, 100, 300, 250], fill=(0, 200, 0))          # 左上 绿
    dr.rectangle([1600, 900, 1850, 1100], fill=(255, 255, 0))     # 右下 黄
    return img


def render(tilt_deg, prog, vao, tex, eye_h=2.0):
    fbo = GL.glGenFramebuffers(1)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
    out_tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, out_tex)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, W, H, 0, GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE, None)
    GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                              GL.GL_TEXTURE_2D, out_tex, 0)
    assert (GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER)
            == GL.GL_FRAMEBUFFER_COMPLETE), "FBO 不完整"

    GL.glViewport(0, 0, W, H)
    GL.glClearColor(0.0, 0.0, 0.0, 1.0)
    GL.glClear(GL.GL_COLOR_BUFFER_BIT)
    GL.glUseProgram(prog)
    GL.glActiveTexture(GL.GL_TEXTURE0)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    gl_core.set_uniforms(
        prog, SRC_W, SRC_H,
        tilt=tilt_deg * 3.14159265358979 / 180.0,
        eye_z=eye_h * SRC_H, spread=0.42, dark=0.001, max_taps=32,
    )
    gl_core.draw_quad(vao)
    GL.glFlush()

    data = GL.glReadPixels(0, 0, W, H, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
    img = Image.frombytes("RGB", (W, H), data).transpose(Image.FLIP_TOP_BOTTOM)
    GL.glDeleteFramebuffers(1, [fbo])
    GL.glDeleteTextures(1, [out_tex])
    return img


def sharpness_by_row(img, bands=6):
    """按横条带算相邻像素差的均值 = 粗略"清晰度"。

    返回值**自上往下**: out[0] = 图像顶部 (远离铰链), out[-1] = 底部 (铰链处)。
    注意 glReadPixels 是下行优先, render() 里已经 FLIP_TOP_BOTTOM 转成了常规
    图像方向, 所以这里 row 0 确实是顶部。搞反过来会把正确的渲染误判为失败。
    """
    g = img.convert("L")
    w, h = g.size
    px = g.load()
    out = []
    for b in range(bands):
        y0, y1 = h * b // bands, h * (b + 1) // bands
        total, n = 0, 0
        for y in range(y0, y1, 3):
            for x in range(0, w - 1, 3):
                total += abs(px[x, y] - px[x + 1, y])
                n += 1
        out.append(total / max(n, 1))
    return out


def black_ratio(img):
    """全黑像素占比 —— 视线完全出界的部分。过高说明 eye_dist_h 太小。"""
    g = img.convert("L")
    px = g.load()
    w, h = g.size
    blk = cnt = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            cnt += 1
            if px[x, y] < 8:
                blk += 1
    return blk / max(cnt, 1)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    sweep = "--sweep" in sys.argv
    tilts = [0.0, 20.0, 40.0, 60.0, 80.0] if sweep else [
        float(args[0]) if args else 60.0
    ]
    # 眼距 (屏高倍数)。win 默认 2.0 在 mac 宽屏上会造成大面积出界黑边,
    # 用 --eye 扫不同值对比。
    eye_h = 2.0
    for a in sys.argv[1:]:
        if a.startswith("--eye="):
            eye_h = float(a.split("=", 1)[1])

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)  # noqa: F841

    surface = QOffscreenSurface()
    surface.create()
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    assert ctx.create(), "OpenGL 上下文创建失败"
    assert ctx.makeCurrent(surface), "makeCurrent 失败"
    got = ctx.format()
    print(f"[GL] {GL.glGetString(GL.GL_VERSION).decode()} | "
          f"profile={got.profile().name} {got.majorVersion()}.{got.minorVersion()}")

    prog = gl_core.compile_program()
    vao, _ = gl_core.make_quad()
    tex = gl_core.make_texture()
    src = make_test_texture()
    # PIL 给的是 RGB, 转成 BGRA 走同一条上传路径
    gl_core.upload_bgra(tex, src.convert("RGBA").tobytes("raw", "BGRA"),
                        SRC_W, SRC_H)

    here = os.path.dirname(os.path.abspath(__file__))
    print(f"[参数] eye_dist_h={eye_h}  spread=0.42  taps<=32")
    for t in tilts:
        img = render(t, prog, vao, tex, eye_h)
        name = f"offscreen_{int(t):02d}.png" if sweep else "offscreen_result.png"
        path = os.path.join(here, name)
        img.save(path)
        bands = sharpness_by_row(img)
        top, bottom = bands[0], bands[-1]      # out[0]=顶, out[-1]=底(铰链)
        blk = black_ratio(img)
        if t == 0:
            verdict = "tilt=0 应当均匀清晰" if blk < 0.01 else "tilt=0 不应有黑区 ✘"
        else:
            verdict = "铰链侧更清晰 ✔" if bottom > top * 1.2 else "铰链侧未更清晰 ✘"
        print(f"[offscreen] tilt={t:5.1f}° -> {name}  "
              f"清晰度 顶={top:6.2f} 底={bottom:6.2f}  黑区={blk * 100:5.1f}%  {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
