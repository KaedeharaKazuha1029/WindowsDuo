"""离屏验证 Duo 折叠着色器: 合成测试纹理 → 渲染 → 输出 PNG (无需窗口)
用法: python offscreen_test.py [tilt_deg=60]
着色器为 GLSL 330 core, 因此这里也用 core 上下文 + VAO/VBO (无立即模式)。
"""
import ctypes
import struct
import sys

from PIL import Image, ImageDraw
from PyQt6.QtGui import QSurfaceFormat, QOffscreenSurface, QOpenGLContext
from PyQt6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram
from PyQt6.QtWidgets import QApplication
from OpenGL import GL

import glass_overlay as go

TILT_DEG = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
W, H = 960, 600


def make_test_texture():
    """合成测试图: 渐变底 + 网格 + 色块, 方便判断模糊/翻转/取样方向"""
    img = Image.new("RGB", (1920, 1200))
    dr = ImageDraw.Draw(img)
    for x in range(0, 1920, 4):
        c = (int(255 * x / 1920), 40, int(255 - 255 * x / 1920))
        dr.line([(x, 0), (x, 1200)], fill=c)
    for gx in range(0, 1920, 120):
        dr.line([(gx, 0), (gx, 1200)], fill=(255, 255, 255), width=3)
    for gy in range(0, 1200, 120):
        dr.line([(0, gy), (1920, gy)], fill=(255, 255, 255), width=3)
    dr.rectangle([100, 100, 300, 250], fill=(0, 200, 0))
    dr.rectangle([1600, 900, 1850, 1100], fill=(255, 255, 0))
    return img


def main():
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)

    surface = QOffscreenSurface()
    surface.create()
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    assert ctx.create(), "context create failed"
    assert ctx.makeCurrent(surface), "makeCurrent failed"

    prog = QOpenGLShaderProgram()
    assert prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, go.VS), prog.log()
    assert prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, go.FS_DUO), prog.log()
    assert prog.link(), prog.log()
    prog.bind()

    # 测试纹理 + mipmap
    img = make_test_texture()
    tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, img.width, img.height, 0,
                    GL.GL_RGB, GL.GL_UNSIGNED_BYTE, img.tobytes())
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
    GL.glGenerateMipmap(GL.GL_TEXTURE_2D)

    # FBO
    fbo = GL.glGenFramebuffers(1)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
    out_tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, out_tex)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, W, H, 0, GL.GL_RGBA,
                    GL.GL_UNSIGNED_BYTE, None)
    GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                              GL.GL_TEXTURE_2D, out_tex, 0)
    assert GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER) == GL.GL_FRAMEBUFFER_COMPLETE

    GL.glViewport(0, 0, W, H)
    GL.glActiveTexture(GL.GL_TEXTURE0)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glUniform1i(prog.uniformLocation("uTex"), 0)
    GL.glUniform2f(prog.uniformLocation("uRes"), 1920.0, 1200.0)
    GL.glUniform1f(prog.uniformLocation("uTilt"), TILT_DEG * 3.14159265 / 180.0)
    GL.glUniform1f(prog.uniformLocation("uEyeZ"), 2.0 * 1200.0)
    GL.glUniform1f(prog.uniformLocation("uSpread"), 0.55)
    GL.glUniform1f(prog.uniformLocation("uDark"), 0.001)
    GL.glUniform1i(prog.uniformLocation("uMaxTaps"), 32)

    # 全屏四边形 VAO/VBO (core profile 不能用立即模式)
    verts = (-1.0, -1.0, 0.0, 0.0,
              1.0, -1.0, 1.0, 0.0,
              1.0,  1.0, 1.0, 1.0,
             -1.0,  1.0, 0.0, 1.0)
    vao = GL.glGenVertexArrays(1)
    GL.glBindVertexArray(vao)
    vbo = GL.glGenBuffers(1)
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
    GL.glBufferData(GL.GL_ARRAY_BUFFER, 4 * len(verts),
                    struct.pack(f"{len(verts)}f", *verts), GL.GL_STATIC_DRAW)
    GL.glEnableVertexAttribArray(0)
    GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 16, ctypes.c_void_p(0))
    GL.glEnableVertexAttribArray(1)
    GL.glVertexAttribPointer(1, 2, GL.GL_FLOAT, GL.GL_FALSE, 16, ctypes.c_void_p(8))

    GL.glDrawArrays(GL.GL_TRIANGLE_FAN, 0, 4)
    GL.glBindVertexArray(0)
    GL.glFlush()

    data = GL.glReadPixels(0, 0, W, H, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
    out = Image.frombytes("RGB", (W, H), data).transpose(Image.FLIP_TOP_BOTTOM)
    out_path = "offscreen_result.png"
    out.save(out_path)
    print(f"[offscreen] tilt={TILT_DEG}° -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
