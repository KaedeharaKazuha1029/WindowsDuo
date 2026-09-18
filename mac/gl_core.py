"""Core profile 的 GL 辅助: 全屏四边形 VAO/VBO + 截图纹理上传。

win 端用 glBegin/glEnd 立即模式和 gl_ModelViewProjectionMatrix, Core profile 里
这些全部不存在, 所以画一个全屏四边形也要 VAO + VBO + 显式 attribute。这里把这套
样板封装掉, 让 offscreen_test 和真窗口共用同一份, 避免两处不一致。

纹理上传有个 mac 特有的坑: CGImage 每行可能有 padding (bytesPerRow > width*4),
必须用 GL_UNPACK_ROW_LENGTH 告诉 GL 真实行宽, 否则画面斜切。
"""
import ctypes

from OpenGL import GL

from shaders import FS_DUO_CORE, QUAD_VERTS, VS_CORE


def compile_program():
    """编译 Duo 折叠着色器, 返回 program id。失败抛 RuntimeError。"""
    prog = GL.glCreateProgram()
    shaders = []
    for kind, src, name in (
        (GL.GL_VERTEX_SHADER, VS_CORE, "vertex"),
        (GL.GL_FRAGMENT_SHADER, FS_DUO_CORE, "fragment"),
    ):
        sh = GL.glCreateShader(kind)
        GL.glShaderSource(sh, src)
        GL.glCompileShader(sh)
        if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
            log = GL.glGetShaderInfoLog(sh)
            raise RuntimeError(f"{name} 着色器编译失败: {log}")
        GL.glAttachShader(prog, sh)
        shaders.append(sh)
    GL.glLinkProgram(prog)
    if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
        raise RuntimeError(f"着色器链接失败: {GL.glGetProgramInfoLog(prog)}")
    for sh in shaders:
        GL.glDeleteShader(sh)
    return prog


def make_quad():
    """全屏四边形 VAO (2 个三角形, 6 顶点; 每顶点 vec2 pos + vec2 uv)。"""
    verts = (ctypes.c_float * len(QUAD_VERTS))(*QUAD_VERTS)
    vao = GL.glGenVertexArrays(1)
    vbo = GL.glGenBuffers(1)
    GL.glBindVertexArray(vao)
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
    GL.glBufferData(GL.GL_ARRAY_BUFFER, ctypes.sizeof(verts), verts, GL.GL_STATIC_DRAW)
    stride = 4 * ctypes.sizeof(ctypes.c_float)
    GL.glEnableVertexAttribArray(0)   # aPos
    GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, stride, ctypes.c_void_p(0))
    GL.glEnableVertexAttribArray(1)   # aUV
    GL.glVertexAttribPointer(
        1, 2, GL.GL_FLOAT, GL.GL_FALSE, stride,
        ctypes.c_void_p(2 * ctypes.sizeof(ctypes.c_float)),
    )
    GL.glBindVertexArray(0)
    return vao, vbo


def make_texture():
    tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER,
                       GL.GL_LINEAR_MIPMAP_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
    GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
    return tex


def upload_bgra(tex, data, width, height, row_px=None):
    """上传 BGRA 数据并生成 mipmap。row_px = 每行实际像素数 (CGImage padding)。"""
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
    if row_px and row_px != width:
        GL.glPixelStorei(GL.GL_UNPACK_ROW_LENGTH, row_px)
    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, width, height, 0,
                    GL.GL_BGRA, GL.GL_UNSIGNED_BYTE, data)
    if row_px and row_px != width:
        GL.glPixelStorei(GL.GL_UNPACK_ROW_LENGTH, 0)
    GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
    GL.glBindTexture(GL.GL_TEXTURE_2D, 0)


def set_uniforms(prog, res_w, res_h, tilt, eye_z, spread, dark, max_taps):
    GL.glUniform1i(GL.glGetUniformLocation(prog, "uTex"), 0)
    GL.glUniform2f(GL.glGetUniformLocation(prog, "uRes"), float(res_w), float(res_h))
    GL.glUniform1f(GL.glGetUniformLocation(prog, "uTilt"), float(tilt))
    GL.glUniform1f(GL.glGetUniformLocation(prog, "uEyeZ"), float(eye_z))
    GL.glUniform1f(GL.glGetUniformLocation(prog, "uSpread"), float(spread))
    GL.glUniform1f(GL.glGetUniformLocation(prog, "uDark"), float(dark))
    GL.glUniform1i(GL.glGetUniformLocation(prog, "uMaxTaps"), int(max_taps))


def draw_quad(vao):
    GL.glBindVertexArray(vao)
    GL.glDrawArrays(GL.GL_TRIANGLES, 0, 6)
    GL.glBindVertexArray(0)
