"""后退投影的几何参数: 开合角 → (separation, along, depth)。

## 模型

内容是一张**铰接在屏幕底边**的纸, 固定在世界空间里; 屏幕是玻璃, 随合盖转动。
眼睛不动, 玻璃在眼下转过去, 于是内容相对玻璃"向后倒", 倒的角度 = separation。

  travel     = 从起效角往下已经合了多少度
  separation = min(recession * travel, max_sep)   内容相对玻璃倒下的角度
  reach/rise = 眼睛在世界坐标里的位置 (铰链为原点)
  along      = 眼睛沿玻璃方向的分量
  depth      = 眼睛离玻璃的垂直距离 (夹一个下限, 防止贴到玻璃上除零)

正向映射 (内容点 → 屏幕点), Mac-Duo DepthOverlay.swift 的 project():

  scale = depth / (depth + y * sin(sep))          <- 关键: < 1, 所以是**缩小**
  sx    = half + (x - half) * scale
  sy    = along + (y * cos(sep) - along) * scale

sin(sep) > 0 时 scale < 1 且随 y 递减 —— 离铰链越远缩得越狠, 这就是"向后退去"。
WindowsDuo 原着色器的 t = eyeZ/(eyeZ - glass.z) > 1 是**放大**, 方向相反。

## 为什么这里要求逆映射

Mac-Duo 是把一个图层用 homography 正向贴过去; 本项目的着色器是逐屏幕像素反查
源内容 (逆投影采样)。所以需要把上面的正向式子解析求逆 —— 见 shaders.py 里的
FS_RECEDE_CORE。推导 (S=sin(sep), C=cos(sep), D=depth, A=along):

  sy = A + (yC - A) * D/(D + yS)
  (sy - A)(D + yS) = (yC - A)D
  sy*D + sy*y*S - A*D - A*y*S = yCD - AD
  sy*D + y*S*(sy - A) = yCD
  =>  y = sy * D / (C*D + S*(A - sy))
  =>  scale = D / (D + y*S),   x = half + (sx - half)/scale

sep=0 时 S=0, C=1: y=sy, scale=1, x=sx —— 退化成恒等映射, 正常显示。

几何模型取自 sumimakito/Mac-Duo (Apache-2.0), 此处为独立的 Python/GLSL 实现。
"""
import math


def separation_params(
    start_deg,
    current_deg,
    viewing_ratio,
    recession,
    max_sep_deg,
    height_px,
):
    """返回 (sep_rad, along_px, depth_px), 直接喂给 FS_RECEDE_CORE。"""
    start = math.radians(start_deg)
    current = math.radians(current_deg)
    travel = max(start_deg - current_deg, 0.0)
    sep = math.radians(min(recession * travel, max_sep_deg))

    # 眼睛在世界坐标 (铰链为原点, 沿桌面为 y, 垂直为 z)
    reach = height_px * viewing_ratio + height_px / 2.0 * math.cos(start)
    rise = height_px / 2.0 * math.sin(start)

    # 换算到"沿玻璃 / 离玻璃"两个方向
    along = reach * math.cos(current) + rise * math.sin(current)
    depth = max(reach * math.sin(current) - rise * math.cos(current),
                height_px / 10.0)
    return sep, along, depth


def angle_from_strength(strength, start_deg, span_deg):
    """浓度 0..1 → 等效开合角。手动模式和平滑后的 g 都走这里, 保证观感连续。"""
    return start_deg - max(0.0, min(1.0, strength)) * span_deg


def project(x, y, sep, along, depth, width):
    """正向映射 (内容点 → 屏幕点)。仅供测试/推导校验用, 着色器里用的是逆映射。"""
    half = width / 2.0
    scale = depth / (depth + y * math.sin(sep))
    return (half + (x - half) * scale,
            along + (y * math.cos(sep) - along) * scale)


def unproject(sx, sy, sep, along, depth, width):
    """逆映射 (屏幕点 → 内容点), 与 GLSL 里的实现一一对应。返回 (x, y, scale)。"""
    s, c = math.sin(sep), math.cos(sep)
    denom = c * depth + s * (along - sy)
    if abs(denom) < 1e-9:
        return None
    y = sy * depth / denom
    scale = depth / (depth + y * s)
    if abs(scale) < 1e-9:
        return None
    half = width / 2.0
    x = half + (sx - half) / scale
    return x, y, scale
