# AGENTS.md — AI 协作指南

面向在本仓库工作的 AI 编码代理（与人类贡献者）。改动前请先读完本文件，避免踩已知的坑。

## 项目是什么

复刻 iPhone Duo 折叠屏的「悬浮玻璃」效果，运行在 Windows 笔记本上：

- **硬件侧**（`esp32/`）：ESP32 + MPU6050 测屏幕开合角度，100Hz 通过串口输出 `{"a":主轴角,"b":副轴角}` JSON。主轴 a 的约定：+10° ≈ 合盖，-90° ≈ 屏幕垂直于桌面。
- **Windows 侧**（`win/`）：PyQt6 QOpenGLWidget 全屏置顶悬浮层，GLSL 着色器实现逆投影 Duo 折叠效果（铰链=屏幕底边，间隙越大越模糊越暗，视线出界纯黑）。

## 目录结构

```
esp32/
  mpu6050_angle/          ESP-IDF v5.x 固件工程 (main/mpu6050_angle_main.c)
  debug_view.py|.bat      串口实时单行重绘调试查看器
win/
  glass_overlay.py        主程序: AngleReader + CaptureWorker + GlassGLWidget
  config.json             全部运行参数 (串口/角度映射/模糊/变暗等)
  offscreen_test.py       离屏渲染验证着色器(不出窗口, 出 PNG)
  run_overlay.bat         串口驱动启动  /  run_manual.bat  纯键盘启动
```

## 构建与运行

### ESP32 固件
- 本机用 ESP-IDF v5.4.4（`D:\Espressif`）。**不要**直接在 shell 里 `idf.py`（本机 PowerShell 不透传 `$env:PATH`），必须走包装器：
  ```
  python esp32/mpu6050_angle/run_build.py -p COM3 flash
  ```
- ESP32 = COM3 (CH9102)。烧录前确认串口没被 debug_view 等程序占用，否则报 PermissionError。
- I2C 引脚是掌控板（盛思乐动）专用口：P19=SCL→GPIO22，P20=SDA→GPIO23（**不是** 21/22）。

### Windows 端
- Python venv: `C:\Users\Kazuha\.workbuddy\binaries\python\envs\default\Scripts\python.exe`，依赖 PyQt6 / PyOpenGL / pyserial / mss / Pillow。
- 直接跑 `win/run_overlay.bat`（ESP 驱动）或 `win/run_manual.bat`（纯键盘）。
- 键盘（需先点控制台窗口获得焦点）：↑/↓ 浓度 ±3%，← 清零，→ 拉满，`r` 在 手动/角度自动 间切换，Esc 退出。默认启动为手动模式浓度 0（正常显示）。

## 已知坑（改代码前必读）

1. **GL 窗口必须继承 `QOpenGLWidget`**（`PyQt6.QtOpenGLWidgets`）。继承普通 `QWidget` 时 `initializeGL/paintGL` 永远不会被调用，窗口只会显示默认底色（白屏）——这是本项目最大的历史 bug。
2. PyQt6 6.11 枚举名：`QOpenGLShader.ShaderTypeBit.Vertex`（不是 `ShaderType.Vertex`）；`QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile`。
3. **截图反馈污染**：Overlay 是不透明置顶窗口，mss 截屏会抓到自己上一帧，几帧后收敛成纯色。靠 `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE=0x11)` 把自己排除出捕获（见 `showEvent`）。改截图逻辑时别动它。
4. **`.bat` 文件里禁止中文**：cmd 按 GBK 解码会乱码并把乱码当命令执行。bat 只写 ASCII。
5. GLSL 需要 `#version 330 compatibility` + Qt 请求 3.3 Compat profile（`textureLod` 依赖 3.3）。
6. 调着色器先用 `offscreen_test.py` 离屏出图验证，再上真窗口；`--smoke` 用 `grabFramebuffer()` 抓帧（不要用整屏截图验证 GL 内容）。
7. config.json 是唯一参数入口（`blur_spread` 模糊、`darkening` 变暗、`angle_closed/angle_open` 角度映射等），不要在代码里硬编码覆盖它。

## 提交约定

- 主分支 `main`，远端 `origin` = github.com/KaedeharaKazuha1029/WindowsDuo。
- `.gitignore` 排除 `esp32/mpu6050_angle/build/`（120MB）、`*.log`、`dbg*.txt`、`*_log.txt`、`*_exit.txt`、`win/smoke_frame.png`、`win/smoke_grab.png`、`.workbuddy/`。不要把这些加回来。
- 提交信息用中文、说明改动动机即可。

## 许可

MIT (见 LICENSE)。
