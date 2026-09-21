# WindowsDuo

在 Windows 二合一设备上复刻 iPhone Duo 风格的「悬浮玻璃」效果。项目通过全屏置顶的 PyQt6/OpenGL Overlay 截取桌面画面，再使用 GLSL 逆投影、模糊和变暗效果模拟折叠屏玻璃。

本仓库是 [KaedeharaKazuha1029/WindowsDuo](https://github.com/KaedeharaKazuha1029/WindowsDuo) 的 Surface 定制实现分支。它同时保留了原仓库的 ESP32 硬件版本和 macOS 版本。

## 目录结构

- `surface/`：Surface Pro 等 Windows 二合一设备的内置姿态传感器版本（本仓库主要贡献）
- `win/`：原 Windows + ESP32 实现（保留，未修改）
- `esp32/`：ESP32 硬件版本（保留，未修改）
- `mac/`：macOS 版本（保留，未修改）

## Surface Pro 版本

`surface/` 目录下的实现默认读取设备内置的 Windows Sensor Platform 姿态传感器，不需要 ESP32、MPU6050、串口或其他外接硬件。

当前角度约定：

- 合上：`-90°`
- 打开：`0°`
- 中间姿态按 Inclinometer 的绝对 `pitch` 线性映射

程序优先读取 `Inclinometer` 的绝对姿态；陀螺仪仅用于显示实时角速度，不把累计变化量当作绝对开合角。

## 环境

- Windows 10/11
- 支持 Windows Sensor Platform 的二合一设备，例如 Surface Pro
- Python 3.8+
- 支持 OpenGL 3.3 Compatibility Profile 的显卡驱动

安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install PyQt6 PyOpenGL winsdk mss Pillow
```

如果还没有虚拟环境：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install PyQt6 PyOpenGL winsdk mss Pillow
```

## 运行 Surface 版本

直接双击 `surface/run_overlay.bat`，或在终端执行：

```powershell
.\.venv\Scripts\python.exe surface/glass_overlay.py
```

启动后按 `r` 切换到角度自动模式。`--manual` 可在没有传感器或调试渲染时使用键盘控制：

```powershell
.\.venv\Scripts\python.exe surface/glass_overlay.py --manual
```

## 配置

所有 Surface 版本参数位于 [surface/config.json](surface/config.json)：

- `inclinometer_axis`：使用 `pitch` 或 `roll`
- `inclinometer_closed` / `inclinometer_open`：设备合上和打开时的实际传感器读数
- `angle_closed` / `angle_open`：映射后的项目角度，默认分别为 `-90` 和 `0`
- `inclinometer_smoothing`：绝对姿态平滑系数
- `blur_spread`、`darkening`、`max_taps`：玻璃效果参数

如果设备在完全合上或打开时的 Inclinometer 读数不是默认的 `90°` 和 `0°`，先测量两个端点，再修改配置中的传感器端点。

## 测试

离屏验证 GLSL：

```powershell
.\.venv\Scripts\python.exe surface/offscreen_test.py 60
```

完整窗口 smoke 测试：

```powershell
.\.venv\Scripts\python.exe surface/glass_overlay.py --manual --smoke
```

## ESP32 / 外部传感器版本

本仓库保留原仓库的 ESP32 + MPU6050 外部传感器实现，位于 `esp32/` 和 `win/` 目录。需要外部传感器方案时，可查看这些目录，或前往原始仓库：
[KaedeharaKazuha1029/WindowsDuo](https://github.com/KaedeharaKazuha1029/WindowsDuo)

## 贡献

本仓库当前目标是将 `surface/` 实现贡献到上游 `KaedeharaKazuha1029/WindowsDuo` 的 `surface` 分支。发起 PR 时请确保不修改 `esp32/`、`mac/` 和 `win/` 目录，只新增或修改 `surface/` 下的文件。详细约定见 [AGENTS.md](AGENTS.md)。

## License

MIT
