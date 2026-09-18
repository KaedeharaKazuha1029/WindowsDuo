"""Duo 折叠着色器 · Core profile 版。

与 win/glass_overlay.py 的 VS/FS_DUO **数学完全一致**, 只改 GL 管线写法:

  win (330 compatibility)          mac (330 core)
  ------------------------------   ---------------------------------
  gl_MultiTexCoord0                in vec2 aUV        (显式 attribute)
  gl_Vertex                        in vec2 aPos
  gl_ModelViewProjectionMatrix     直接用 NDC 坐标, 不需要矩阵
  varying                          in / out
  gl_FragColor                     out vec4 fragColor
  glBegin/glEnd 立即模式           VAO + VBO

为什么必须改: macOS 只提供 OpenGL 2.1 或 3.2+ **Core** profile, 没有
compatibility profile, 固定管线那套在 mac 上根本拿不到上下文。实测 M3 上
可拿到 4.1 Core (Metal 后端), `#version 330 core` 编译通过。

逆投影模型本身 (Vogel 盘 + mip LOD + 边缘覆盖率) 原样保留, 见原文件注释。
"""

VS_CORE = """#version 330 core
layout(location = 0) in vec2 aPos;
layout(location = 1) in vec2 aUV;
out vec2 vUV;
void main() {
    vUV = aUV;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

FS_DUO_CORE = """#version 330 core
uniform sampler2D uTex;
uniform vec2  uRes;      // 截图尺寸 px
uniform float uTilt;     // 玻璃转角 (弧度), 0 = 贴合界面
uniform float uEyeZ;     // 眼睛到界面平面距离 px
uniform float uSpread;   // 单位间隙 → 模糊半径 (散射半角正切)
uniform float uDark;     // 单位模糊半径损失的光量
uniform int   uMaxTaps;
in  vec2 vUV;
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

    // 磨砂玻璃吸光: 与散射成正比地变暗
    float att = max(1.0 - uDark * radius, 0.0);

    vec2 uvHit = vec2(hit.x / uRes.x, 1.0 - hit.y / uRes.y);

    if (radius < 0.5) {
        fragColor = vec4(textureLod(uTex, uvHit, 0.0).rgb * att, 1.0);
        return;
    }

    // mip LOD: 大半径先降到低分辨率 mip 再盘式采样
    float lod  = clamp(log2(max(radius, 1.0) / 16.0), 0.0, 6.0);
    float effR = radius / exp2(lod);

    // Vogel 盘: sqrt 均匀面密度 + 黄金角 + 每像素随机旋转 → 磨砂颗粒
    int taps = int(clamp(effR * 2.0, 6.0, float(uMaxTaps)));
    float rot = hash21(gl_FragCoord.xy) * TWO_PI;

    // 边缘覆盖率: 采样核出界部分按比例衰减, 不出现硬边
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

# 全屏四边形: NDC 位置 + UV, (0,0)=左下 与 win 端 glTexCoord 约定一致
QUAD_VERTS = (
    # aPos.x, aPos.y, aUV.x, aUV.y
    -1.0, -1.0, 0.0, 0.0,
     1.0, -1.0, 1.0, 0.0,
     1.0,  1.0, 1.0, 1.0,
    -1.0, -1.0, 0.0, 0.0,
     1.0,  1.0, 1.0, 1.0,
    -1.0,  1.0, 0.0, 1.0,
)


# ---------------------------------------------------------------------------
