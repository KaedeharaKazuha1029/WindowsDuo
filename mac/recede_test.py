"""验证「向后模糊隐去」的空间性质 (离屏, 出数字也出图)。

iPhone Duo 的观感不是"全屏均匀模糊", 而是内容**贴在世界空间的平面上不动**,
屏幕像玻璃一样转开, 于是:

  1. 后退缩小: 内容整片被压向铰链, 越合越小 (scale < 1)
  2. 空间性模糊: 铰链处始终清晰, 越远越模糊 (不是全屏一个模糊值)
  3. 渐暗隐去: 越模糊越暗, 视线出界处纯黑

三条同时成立才叫 Duo 效果, 少一条就只是个模糊滤镜。本脚本用带定位条的合成图
逐角度量化这三条, 并可对比两种投影:

    python mac/recede_test.py                # 默认 recede (向后退去)
    python mac/recede_test.py --mode=duo     # win 原公式 (放大挤出顶边)
    python mac/recede_test.py --compare      # 两者并排对比关键指标
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from OpenGL import GL
from PIL import Image, ImageDraw
from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PyQt6.QtWidgets import QApplication

import gl_core
from depth_geometry import separation_params

W, H = 800, 500
SRC_W, SRC_H = 1600, 1000
DEG2RAD = 3.14159265358979 / 180.0

# 横向标记条 (源图坐标, top-first)。y 越小 = 离铰链(底边)越远
BARS = [
    ("红", 100, (255, 0, 0)),
    ("绿", 300, (0, 255, 0)),
    ("蓝", 500, (0, 128, 255)),
    ("黄", 700, (255, 255, 0)),
    ("品", 900, (255, 0, 255)),
]
BAR_H = 24
START_ANGLE = 90.0
SPAN = 60.0


def make_marked_texture():
    """深灰底 + 五条横向彩色标记条 + 竖向细网格。底色非纯黑, 便于区分"出界黑"。"""
    img = Image.new("RGB", (SRC_W, SRC_H), (40, 40, 40))
    dr = ImageDraw.Draw(img)
    for gx in range(0, SRC_W, 100):
        dr.line([(gx, 0), (gx, SRC_H)], fill=(90, 90, 90), width=2)
    for _n, y, color in BARS:
        dr.rectangle([0, y - BAR_H // 2, SRC_W - 1, y + BAR_H // 2], fill=color)
    return img


def render(angle, prog, vao, tex, mode, eye_h, recession, spread, dim):
    fbo = GL.glGenFramebuffers(1)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
    out_tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, out_tex)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, W, H, 0, GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE, None)
    GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                              GL.GL_TEXTURE_2D, out_tex, 0)
    GL.glViewport(0, 0, W, H)
    GL.glClearColor(0.0, 0.0, 0.0, 1.0)
    GL.glClear(GL.GL_COLOR_BUFFER_BIT)
    GL.glUseProgram(prog)
    GL.glActiveTexture(GL.GL_TEXTURE0)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)

    travel = max(START_ANGLE - angle, 0.0)
    progress = min(travel / SPAN, 1.0)
    if mode == "recede":
        sep, along, depth = separation_params(
            START_ANGLE, angle, eye_h, recession, 88.0, SRC_H)
        gl_core.set_recede_uniforms(
            prog, SRC_W, SRC_H, sep, along, depth, spread,
            progress, dim["max_dim"], dim["dim_floor"],
            dim["dim_reach"], dim["dim_curve"], 32)
    else:
        # win 原公式: 用 travel 比例映射到 tilt
        tilt = progress * 88.0 * DEG2RAD
        gl_core.set_uniforms(prog, SRC_W, SRC_H, tilt, eye_h * SRC_H,
                             spread, 0.001, 32)
    gl_core.draw_quad(vao)
    GL.glFlush()
    data = GL.glReadPixels(0, 0, W, H, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
    img = Image.frombytes("RGB", (W, H), data).transpose(Image.FLIP_TOP_BOTTOM)
    GL.glDeleteFramebuffers(1, [fbo])
    GL.glDeleteTextures(1, [out_tex])
    return img


def find_bar(img, color, tol=0.34):
    """标记条的垂直中心与横向宽度。返回 (y_center, width_px) 或 (None, None)。

    必须对**亮度不敏感**: 渐暗本身就是被测对象之一, 用绝对色距会把"变暗的红条"
    误判成"消失", 把正常的渐暗报成内容丢失。所以先归一化成色度比例
    (r/(r+g+b), ...) 再比较 —— 乘任意亮度系数不变。只有真的滑到黑 (sum 太小)
    才算丢失。
    """
    px = img.load()
    w, h = img.size
    tsum = sum(color) or 1
    tr, tg, tb = (c / tsum for c in color)
    num = den = 0
    per_row = {}
    for y in range(h):
        cnt = 0
        for x in range(0, w, 4):
            r, g, b = px[x, y]
            s = r + g + b
            if s < 24:            # 真的黑了, 没有色度信息
                continue
            if (abs(r / s - tr) + abs(g / s - tg) + abs(b / s - tb)) < tol:
                cnt += 1
        if cnt:
            per_row[y] = cnt
            num += y * cnt
            den += cnt
    if not den:
        return None, None
    y_center = num / den
    # 最亮那行的横向覆盖宽度 (采样步长 4 还原)
    best = max(per_row, key=per_row.get)
    return y_center, per_row[best] * 4


def sharpness_at_row(img, y, band=10):
    g = img.convert("L")
    px = g.load()
    w, h = g.size
    y0, y1 = max(0, int(y) - band), min(h, int(y) + band)
    tot = n = 0
    for yy in range(y0, y1):
        for x in range(0, w - 1):
            tot += abs(px[x, yy] - px[x + 1, yy])
            n += 1
    return tot / max(n, 1)


def brightness(img):
    g = img.convert("L")
    px = g.load()
    w, h = g.size
    s = n = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            s += px[x, y]
            n += 1
    return s / max(n, 1)


def black_ratio(img):
    """几乎全黑的像素占比。

    注意它把"被渐暗到极暗"和"视线出界"算在一起, 开强渐暗后不能再当作
    出界面积读。想看纯几何出界用 out_of_bounds_ratio()。
    """
    g = img.convert("L")
    px = g.load()
    w, h = g.size
    blk = n = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            n += 1
            if px[x, y] < 8:
                blk += 1
    return blk / max(n, 1)


def out_of_bounds_ratio(angle, eye_h, recession, spread):
    """纯几何算的"视线出界"面积占比, 不受渐暗影响。

    走与着色器同一套逆映射, 逐点判断采样点是否落在内容矩形之外。
    """
    import math

    from depth_geometry import unproject
    sep, along, depth = separation_params(
        START_ANGLE, angle, eye_h, recession, 88.0, SRC_H)
    s = math.sin(sep)
    out = tot = 0
    for iy in range(0, H, 4):
        py = (H - 1 - iy) / H * SRC_H      # 屏幕行 -> 源图 y (自铰链向上)
        for ix in range(0, W, 4):
            tot += 1
            got = unproject(ix / W * SRC_W, py, sep, along, depth, SRC_W)
            if got is None:
                out += 1
                continue
            x, y, _sc = got
            radius = spread * y * s
            if (x < -radius or x > SRC_W + radius
                    or y < -radius or y > SRC_H + radius):
                out += 1
    return out / max(tot, 1)


# GL 上下文必须一直被引用着。QOffscreenSurface / QOpenGLContext 一旦被 GC,
# 上下文就不再 current, 后续 glGetString 会返回 None、glCompileShader 静默失败。
_GL_KEEP = {}


def setup_gl():
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication.instance() or QApplication(sys.argv)
    surf = QOffscreenSurface()
    surf.create()
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    assert ctx.create(), "GL 上下文创建失败"
    assert ctx.makeCurrent(surf), "makeCurrent 失败"
    _GL_KEEP.update(app=app, surf=surf, ctx=ctx)
    return app, surf, ctx


def run(mode, angles, eye_h, recession, spread, dim, save=True, verbose=True):
    prog = gl_core.compile_program(mode)
    vao, _ = gl_core.make_quad()
    tex = gl_core.make_texture()
    src = make_marked_texture()
    gl_core.upload_bgra(tex, src.convert("RGBA").tobytes("raw", "BGRA"),
                        SRC_W, SRC_H)
    here = os.path.dirname(os.path.abspath(__file__))
    results = {}
    for a in angles:
        img = render(a, prog, vao, tex, mode, eye_h, recession, spread, dim)
        if save:
            img.save(os.path.join(here, f"recede_{mode}_{int(a):02d}.png"))
        bars = [find_bar(img, c) for _n, _y, c in BARS]
        results[a] = (img, bars)

    if verbose:
        print(f"\n=== [{mode}] 1) 后退缩小: 标记条中心位置 (px, 0=顶 / "
              f"铰链在底部 y={H}) 与宽度 ===")
        header = ("  角度 |" + "".join(f"{n:>14}" for n, _y, _c in BARS)
                  + " | 亮度 几何出界% 极暗%")
        print(header)
        print("  " + "-" * (len(header) - 2))
        for a in angles:
            img, bars = results[a]
            cells = ""
            for y, wd in bars:
                cells += f"{(f'{y:5.0f}/{wd:4d}' if y is not None else '     ---  '):>14}"
            oob = (f"{out_of_bounds_ratio(a, eye_h, recession, spread) * 100:9.1f}"
                   if mode == "recede" else "      n/a")
            print(f"  {a:4.0f}° |{cells} | {brightness(img):5.1f} "
                  f"{oob} {black_ratio(img) * 100:5.1f}")

        print(f"\n=== [{mode}] 2) 空间性模糊: 各标记条处局部清晰度 (越小越模糊) ===")
        header2 = "  角度 |" + "".join(f"{n:>9}" for n, _y, _c in BARS) + " | 远/近比"
        print(header2)
        print("  " + "-" * (len(header2) - 2))
        for a in angles:
            img, bars = results[a]
            sh = [sharpness_at_row(img, y) if y is not None else None
                  for y, _w in bars]
            cells = "".join(f"{(f'{s:8.2f}' if s is not None else '     ---'):>9}" for s in sh)
            far, near = sh[0], sh[-1]
            ratio = f"{far / near:7.3f}" if (far and near) else "    ---"
            print(f"  {a:4.0f}° |{cells} | {ratio}")
    return results


def main():
    eye_h, recession, spread = 6.0, 1.0, 0.42
    dim = {"max_dim": 1.0, "dim_floor": 0.2, "dim_reach": 0.5, "dim_curve": 1.6}
    mode = "recede"
    compare = "--compare" in sys.argv
    for a in sys.argv[1:]:
        if a.startswith("--mode="):
            mode = a.split("=", 1)[1]
        elif a.startswith("--eye="):
            eye_h = float(a.split("=", 1)[1])
        elif a.startswith("--recession="):
            recession = float(a.split("=", 1)[1])
        elif a.startswith("--spread="):
            spread = float(a.split("=", 1)[1])
        elif a.startswith("--maxdim="):
            dim["max_dim"] = float(a.split("=", 1)[1])
        elif a.startswith("--dimfloor="):
            dim["dim_floor"] = float(a.split("=", 1)[1])
        elif a.startswith("--dimreach="):
            dim["dim_reach"] = float(a.split("=", 1)[1])
        elif a.startswith("--dimcurve="):
            dim["dim_curve"] = float(a.split("=", 1)[1])

    setup_gl()
    ver = GL.glGetString(GL.GL_VERSION)
    print(f"[GL] {ver.decode() if ver else '(无法取得版本, 上下文可能已失效)'}")
    print(f"[参数] eye_dist_h={eye_h} recession={recession} spread={spread} "
          f"max_dim={dim['max_dim']} dim_floor={dim['dim_floor']} "
          f"dim_reach={dim['dim_reach']} dim_curve={dim['dim_curve']}  "
          f"起效角={START_ANGLE}° 跳度={SPAN}°")
    angles = [90, 80, 70, 60, 45, 30]

    modes = ["recede", "duo"] if compare else [mode]
    all_res = {}
    for m in modes:
        all_res[m] = run(m, angles, eye_h, recession, spread, dim)

    print("\n" + "=" * 66)
    print("判定 (最远标记 = 红条; 铰链在画面底部)")
    print("=" * 66)
    for m in modes:
        res = all_res[m]
        print(f"\n[{m}]")
        # 1) 后退缩小: 宽度单调变小。
        #    注意不能用"y 变大(压向铰链)"做判据 —— 后退模型里内容是朝消隐点
        #    (眼睛的 along 位置, 在屏幕上方) 整片收缩, 所以它会一边变小一边向上移。
        #    真正要求的是"变小"而不是"往下跑"。
        widths = [(a, res[a][1][0][1]) for a in angles]
        vis_w = [(a, w) for a, w in widths if w is not None]
        if len(vis_w) >= 2:
            mono = all(vis_w[i + 1][1] <= vis_w[i][1] for i in range(len(vis_w) - 1))
            (a_f, w_f), (a_l, w_l) = vis_w[0], vis_w[-1]
            print(f"  后退缩小: 最远标记宽 {w_f}→{w_l}px "
                  f"({a_f:.0f}°→{a_l:.0f}°)  "
                  f"{'单调缩小 ✔' if mono and w_l < w_f else '缩小不单调 ✘'}")
        # 2) 是否靠几何出界来"消失" —— recede 应当全程 0%
        if m == "recede":
            oobs = [out_of_bounds_ratio(a, eye_h, recession, spread) for a in angles]
            print(f"  几何出界: 最大 {max(oobs) * 100:.1f}%  "
                  f"{'内容不被挤出屏幕, 消失全靠渐暗 ✔' if max(oobs) < 0.02 else '有内容被挤出界 ✘'}")
        # 3) 渐暗隐去 + 空间性
        b_open = brightness(res[angles[0]][0])
        b_closed = brightness(res[angles[-1]][0])
        print(f"  渐暗隐去: 亮度 {b_open:.1f} → {b_closed:.1f} "
              f"({'✔' if b_closed < b_open * 0.5 else '变暗不足 ✘'})")
        # 起步不能太猛: 刚合 1/6 时应当还看得清
        b_early = brightness(res[angles[1]][0])
        print(f"  起步温和: 80° 亮度 {b_early:.1f} "
              f"({'✔' if b_early > b_open * 0.75 else '一合就暗得太快 ✘'})")
        img_mid, bars_mid = res[60]
        sh = [sharpness_at_row(img_mid, y) if y is not None else None
              for y, _w in bars_mid]
        if sh[0] and sh[-1]:
            print(f"  空间模糊: 60° 远/近清晰度比 {sh[0] / sh[-1]:.3f} "
                  f"({'铰链侧显著更清晰 ✔' if sh[0] < sh[-1] * 0.7 else '空间性不足 ✘'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
