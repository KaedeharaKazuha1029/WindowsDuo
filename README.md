# WindowsDuo

在 Windows / macOS 笔记本上复刻 **iPhone Duo 折叠屏的「悬浮玻璃」效果**：屏幕开合时，桌面内容像隔着一层绕铰链旋转的玻璃——开合角度越大，内容越模糊、越暗，视线出界处渐变为纯黑。

> **⚠️ 硬件通路尚未测试**
>
> 本副本目前只完成 **Windows 端软件**的调试与实测（着色器、抓屏、键盘、串口自适应等，见下方「[测试情况](#测试情况)」）。
> **ESP32 + MPU6050 这条硬件链路还没有验证过**：手头还没有对应的模块与接线，`esp32/` 固件没有在本机烧录运行，角度映射参数也没有用真实开合角度标定过。
> **计划**：等硬件到货后（预计几天内）补做 接线 → 烧录 → 陀螺仪零漂校准 → 串口验证 → 端到端联调，届时按实测结果继续修改固件与 `config.json`，并同步更新本文档。

## 效果原理

这不是简单的全屏高斯模糊，而是**空间化的逆投影**：

- 桌面内容固定在世界空间的平面上不动，屏幕则是一块绕底边铰链向观察者旋转的"玻璃"
- 每个像素从眼睛发射线穿过玻璃像素，交到界面平面上得到采样点
- 间隙越大 → 采样半径越大（模糊越强）、衰减越多（越暗）；靠近铰链处始终清晰
- 采样使用 Vogel 螺旋盘 + mip LOD 分级 + 边缘覆盖率平滑，单 pass GLSL 着色器完成

理论模型参考自多个开源复刻（DuoLikeAnimation / iphone-duo / MacDuo / FrostFold），按笔记本场景（铰链 = 屏幕底边）重新实现。

## 改了什么

**1. 着色器：兼容式 → GLSL 330 core（核心修复）**

- `VS` 改成 `layout(location=0/1) in` + `out`，`FS_DUO` 改成 `in/out vec4 fragColor`，6 处 `gl_FragColor` 全部替换。
- `_draw_quad` 从立即模式 `glBegin/glVertex` 改成 `initializeGL` 里建 **VAO+VBO**、`glDrawArrays(GL_TRIANGLE_FAN)`。

原因：Intel Windows 驱动的兼容模式只到 GLSL 1.20（本机实测 `#version 120` 通过、`130` 与 `330 compatibility` 均被拒，报 `'varying' : not available in current GLSL version`）。原写法在这类驱动上**必然编译失败**，而失败后程序会直接崩掉（见第 2 条），所以这是一个"跑不起来"级别的修复。

**2. 着色器失败不再"猝死"** 原来编译失败后仍去调 `glUniform1i` → `GLError 1282` → 进程直接挂掉。现在 `_gl_linked` 为假时只清黑屏并打印明确原因；非 smoke 模式下 1.5 s 后自动退出（exit 2），不会给你留一个全屏黑窗。同时修了 `int(f.profile())` 在 PyQt6 上抛 `TypeError`、以及 GBK 控制台下 `✔/✘` 抛 `UnicodeEncodeError` 导致自检崩溃这两个原有 bug。

**3. 串口自适应** 新增 `candidate_ports()`：按 Espressif 原生 USB(303A) > CH340(1A86) > CP210x(10C4) 排序自动挑口；`AngleReader` 逐个尝试、被占用/拔出后 0.6 s 自愈重扫；支持 `--port COMx` 手动指定。`config.json` 的 `port` 从写死的 COM3 改为 `"auto"`（COM3 是原作者机器的口）。

**4. 其它适配** `mss.mss()` → `mss.MSS()`（mss 10.2 已弃用）；`--smoke` 支持 `--g 0.35` 指定浓度并加了 `HoldControl`（原来浓度会被键盘线程拉回 0，演示帧等于没效果）；两个 `.bat` 不再写死 `C:\Users\Kazuha\...`；`offscreen_test.py` 同步 core 化。

**5. 浓度拉高不再整屏变黑**（`max_tilt_deg`: 88 → 60）

原版把浓度 100% 映射到 88° 倾角，而着色器的逆投影在 65°~75° 之间就会让视线全部射出界面平面。实测（同一张测试图）：85% 浓度时 95% 的像素已变黑，100% 时亮度 0.1/255、**99.9% 全黑**——也就是"浓度拉到一半以上屏幕就黑了"。改成 60° 后拉满仍是"强磨砂 + 四角压暗"：亮度 60.3/255、全黑像素 25%。想保留原版"折到底变黑"的手感，把该值调回 88 即可。

**6. 抓屏后端换成 DXGI，拖动时玻璃内画面更新快 6 倍**（`capture`: `auto`）

原版用 mss（GDI `BitBlt`）：整屏 1920×1080 单次中位 **33.3 ms**（≈30 Hz 封顶），实测程序里 72~84 ms，所以只能 3 Hz 刷新——拖动窗口时玻璃里就是一张 3 fps 的"冻屏"。现在 `auto` 优先走 **DXGI Desktop Duplication**（`dxcam`）：单次中位 **6.6 ms**、稳定拿到 60 fps 新帧。模拟拖动实测玻璃内画面更新 **3.0 fps → 18.6 fps**，进程 CPU 36% → 50%（单核百分比）。未安装 `dxcam`/`numpy`、或初始化失败时**自动回退 GDI**，行为与原来一致。

**7. 窗口比屏幕少几像素**（`win_shrink_px`: 2）

**这是让 DXGI 可用的前提**：恰好铺满物理屏幕的窗口会被 Windows 走"全屏直通"呈现，DXGI 抓屏会把整块抓成**纯黑**（GDI 则是完全看不到它）。窗口少几行后回到普通合成路径，抓屏才能拿到真实桌面。少掉的那几行在屏幕最底部（= 铰链处，本来就接近清晰），视觉上看不出来。

**为什么是 2 而不是 1**：这个值要经过 `round((物理高 − N) / dpr)` 换算成逻辑尺寸，dpr 不是整数时会被四舍五入。实测：dpr=1.25（125%）时 1 就够；但 **200% 缩放（4K 笔记本常见）下 `1` 会被算回满屏**，DXGI 又抓到纯黑（窗口物理高 1080/1080、抓到的中心 R=0）。改成 2 后，125% 与 200% 下都稳定少 2px、抓屏正常。

副作用需注意：窗口不再是"满屏"，抓屏就真的能看到它了，于是 `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` 的自我排除从"锦上添花"变成**必须生效**（代码里保留，设置失败会打印警告；别删这段）。

**8. 刷新率 3Hz → 30Hz**（`refresh_hz`）

DXGI 变便宜之后 30Hz 才有意义；实测 60Hz 与 30Hz 结果相同（瓶颈已不在本项目这侧）。嫌 CPU 高可调 15，想省电可调 3~5。

**9. 修复 `←` / `a` 清空键无反应**

原版把"清零"编码成 `delta = 0.0` 哨兵值，但判断条件是 `abs(delta) < 0.5`，于是走了"在当前值上累加"分支 → `target + 0.0` 等于原值不变（而 `→` 的 `1.0` 不满足条件、走 else 直接赋值，所以一直正常）。现已拆成"拉满 / 清零 / 微调"三个分支。

**10. 两个 `.bat` 换掉解释器写法**

- **纯 ASCII**：AGENTS.md 第 4 条要求 bat 只能是 ASCII——原先注释里的中文经 cmd 的 GBK 解码会把两行 `REM` 粘连在一起。
- **不再写死 `py -3.14`**：原来的 `where py && set PY=py -3.14` 在只装了 3.12/3.11 的机器上会直接报 `No runtime installed that matches 3.14` 然后 `pause`，**不会**回退。现在按 `py -3.14 → 3.13 → 3.12 → 3.11 → py -3 → python` 依次探测，且探测命令里直接 `import PyQt6, OpenGL, mss, serial`——即"挑一个依赖齐全的解释器"，全都不可用时打印 pip 安装命令。
  探测用**标准输出**而不是 `errorlevel`：实测 `py` 启动器在版本不存在时返回的是**负数退出码**，`if not errorlevel 1` 会把它误判成"成功"（这正是第一版回退逻辑没生效的原因）。
- 顺带统一为 CRLF 行尾（Windows 批处理的常规格式；仓库里原本是 LF）。

## 测试情况

测试环境：Windows 11（build 26200）笔记本，Intel HD Graphics 630（驱动 31.0.101.2140），Python 3.14。

### 已验证（Windows 端，均为本机实跑数据）

| 项目 | 结果 |
|---|---|
| 着色器 | GL 3.3 core 上下文下编译/链接通过；离屏渲染与真窗口渲染均正确 |
| 抓屏 DXGI | 单次中位 6.6 ms（最差 13.6 ms）、新帧 60/s |
| 抓屏 GDI 回退 | 单次中位 33.3 ms、新帧 30/s；缺 `dxcam` 时自动回退，功能正常 |
| 拖动场景（模拟） | 玻璃内画面更新 3.0 fps（GDI@3Hz）→ 18.6 fps（DXGI@30Hz） |
| 浓度映射 | 100% 时全黑像素 25%（原版 99.9%），画面不再整屏黑 |
| 抓屏安全性 | 玻璃显示期间抓到的画面亮度稳定（36~39/255），无自反馈回黑 |
| 键盘 | `↑/↓/←/→/w/s/a/d/r/Esc` 逐键注入验证通过 |
| 串口自适应 | 枚举与优先级排序正常；端口被占用时给出状态并自动重扫 |
| 自检 `--selftest` | PASS（截屏 OK 1920×1080，exit 0） |

### 未验证（等硬件到货后补做）

- **ESP32 + MPU6050 整条链路**：固件未在本机烧录运行，I2C 接线、陀螺仪零漂校准、100 Hz 输出稳定性均未实测。
- **角度映射**：`angle_closed` / `angle_open`（默认 10 / -90）仍是原作者的标定值，没有用真实开合角度校正过。
- **"角度自动"模式**：键盘 `r` 切换后的自动跟随路径只做了代码层检查，没有真实角度数据流跑过。
- **合盖锁屏** `lock_at_close`：未测。
- **固件目标平台**：`sdkconfig` 的 target 是 **ESP32 (D0WDQ6)**，I2C 引脚按掌控板写死为 `SCL=GPIO22 / SDA=GPIO23`。若换用 ESP32-S3 / ESP32-C3 等板子，需要改 target 与引脚定义后重新编译。

### 后续计划

硬件到货后依次进行：接线 → 烧录 `esp32/mpu6050_angle` → 串口验证 100 Hz 角度流 → 两点校准 → 用真实角度标定 `angle_closed` / `angle_open` → 端到端联调"开合盖子驱动玻璃层"。期间发现的固件或参数问题会继续在本仓库修改，并更新本文档与「测试情况」。

软件侧还留着一个已知可优化项：**玻璃目前是常显的**（启动后桌面即变成截图回放），若在浓度≈0 时把窗口 `hide()` 掉，则平时桌面是原生帧率、只在开合过渡时才出现玻璃。等硬件联调时一并评估是否加入。

## 两个版本

| 版本 | 平台 | 开合角度来源 | 硬件要求 |
|---|---|---|---|
| **Windows + ESP32** | Windows | 外接 ESP32 + MPU6050 陀螺仪 | 一块 ESP32 开发板 + MPU6050 |
| **纯手动** | Windows / macOS | 键盘调节 | 无 |

## 目录结构

```
esp32/                    ESP32 固件 + 串口调试工具 (Windows 版)
  mpu6050_angle/          ESP-IDF 工程: 零漂校准 + 互补滤波, 100Hz 输出角度 JSON
  debug_view.py|.bat      串口实时角度查看器
win/                      Windows 端主程序
  glass_overlay.py        PyQt6 + OpenGL 全屏悬浮层 (角度读取/截屏/着色器)
  config.json             运行参数
  offscreen_test.py       着色器离屏验证
  run_overlay.bat         ESP 驱动启动   /  run_manual.bat  纯键盘启动
```

## 快速开始

### Windows + ESP32

1. 接线（掌控板 / 通用 ESP32 + MPU6050，I2C）：`P19=SCL→GPIO22`，`P20=SDA→GPIO23`，MPU6050 接该 I2C 总线
2. 烧录固件（需 ESP-IDF v5.x）：
   ```
   python esp32/mpu6050_angle/run_build.py -p COM3 flash
   ```
3. 运行 Windows 端：
   - `win/run_overlay.bat` — ESP 角度驱动（键盘 `r` 切换手动/自动）
   - `win/run_manual.bat` — 纯键盘手动
4. 键盘操作（先点一下控制台窗口获得焦点）：`↑/↓` 浓度 ±3%，`←` 清零，`→` 拉满，`r` 切换控制方，`Esc` 退出
5. 依赖：`PyQt6 / PyOpenGL / mss / pyserial` 为必需（`Pillow` 只有 `--smoke` 用到，`dxcam + numpy` 可选——装了才走 DXGI 抓屏、拖动更跟手）：
   ```
   python -m pip install PyQt6 PyOpenGL mss pyserial Pillow
   python -m pip install dxcam numpy        # 可选
   ```
   两个 `.bat` 启动时会**自动挑选一个依赖齐全的 Python 解释器**，全都没有则打印上面这条安装命令。

> **注意 1**：硬件部分（接线 / 烧录 / 角度标定）**尚未验证**，见上文「[测试情况](#测试情况)」。当前手动模式（`run_manual.bat` + 键盘）是可用状态。
>
> **注意 2**：**必须从带控制台的窗口启动**（双击 `.bat` 或在 cmd 里运行），不要用 `pythonw`、图形化快捷方式等方式启动——那样键盘线程会失灵并把 CPU 跑满，详见「[在其它设备上运行](#在其它设备上运行纯手动模式)」。

## 在其它设备上运行（纯手动模式）

把这套东西拷到另一台 Windows 机器上、**不改任何代码**直接跑，需要满足以下几个前提（下表均为本机实测验证过的行为）：

| 前提 | 说明 | 不满足时 |
|---|---|---|
| **Windows** | 代码用到 `msvcrt` / `ctypes.windll` / `SetWindowDisplayAffinity` / DXGI | macOS / Linux 不行（仓库另有 `mac/` 实现） |
| **显卡驱动支持 OpenGL 3.3 core** | 远程桌面会话、纯虚拟机、刚装完系统还没装显卡驱动（微软基本显示适配器只有 GL 1.1）都不满足 | 启动约 1.5 s 后打印 `[致命] 着色器未链接, 无法渲染` 并以 exit code 2 退出（不会卡死黑屏，但用不了） |
| **依赖齐全** | `PyQt6` / `PyOpenGL` / `mss` / **`pyserial`**（手动模式并不用串口，但它是模块级 import）；`Pillow` 仅 `--smoke` 需要；`dxcam + numpy` 可选 | 启动即 ImportError；两个 `.bat` 会提前探测依赖并打印 pip 命令 |
| **Python ≥ 3.9** | 代码没有 3.10+ 专属语法 | `.bat` 会自动挑选可用的解释器 |
| **从带控制台的窗口启动** | 双击 `.bat`，或在 cmd 里 `python glass_overlay.py --manual`。**不要**用 `pythonw`、图形化快捷方式、或某些 IDE 的"无控制台运行" | 实测：`msvcrt.getwch()` 会立刻返回 `'\uffff'` 而不阻塞，键盘线程变成死循环——**所有按键失灵，且进程 CPU 由约 50% 升到 118%（单核）** |

参数上建议 `win_shrink_px` 保持 **2**：0 或 1 在部分 DPI 缩放比例下会让 DXGI 抓到纯黑（见「改了什么」第 7 条）。

### 拷过去之后先自检

```
cd win
python glass_overlay.py --smoke --manual --g 0.35     REM 跑 2 秒自动退出并抓帧
```

能正常退出（exit 0）就说明 GL 与抓屏都正常；若打印 `[致命] 着色器未链接` 则是显卡驱动不支持。
注意 `--selftest` **不覆盖着色器**（它不创建窗口，只测截屏与串口），别只用它判断能不能用。

### 只在特定环境才需要的降级（改 `config.json` 即可，无需改代码）

| 情况 | 建议配置 |
|---|---|
| Windows 10 低于 2004（不支持 `WDA_EXCLUDEFROMCAPTURE`） | `capture` 设 `"gdi"` + `win_shrink_px` 设 `0`（满屏窗口对 GDI 天然不可见，既不需要自我排除也不会反馈）。**不要**配成 `win_shrink_px: 0` + `capture: "auto"`，那样 DXGI 会抓到纯黑 |
| 多显示器 / 笔记本混合显卡 / HDR 显示器 / 播放受保护内容 | `capture` 设 `"gdi"`（DXGI 在混合显卡下可能选错输出，HDR 下返回浮点格式，受保护内容返回黑块） |
| 没装 `dxcam`（自动回退 GDI） | 依然可用：实测 GDI@30Hz 玻璃内画面 13.4 fps、CPU 44%（DXGI 为 18.6 fps / 50%）。想更省 CPU 可把 `refresh_hz` 调到 3~5 |

## 主要参数 (`config.json`)

| 参数 | 含义 |
|---|---|
| `angle_closed` / `angle_open` | 角度映射：合盖 / 全开对应的角度（默认 10 / -90，**尚未用真实角度标定**） |
| `blur_spread` | 模糊扩散系数（越小越通透） |
| `darkening` | 随间隙变暗的强度 |
| `eye_dist_h` | 视点距离（屏幕高度的倍数） |
| `max_tilt_deg` | 最大倾角（默认 60；**调大到 70 以上画面会开始整片变黑**，88 就是原版那种"折到底全黑"） |
| `capture` | 抓屏后端：`auto`（优先 DXGI，失败回退 GDI）/ `dxgi` / `gdi` |
| `win_shrink_px` | 窗口比屏幕少几像素（默认 2，**DXGI 抓屏的前提**；200% 缩放下必须 ≥2，见上文第 7 条） |
| `refresh_hz` | 抓屏刷新率（默认 30；DXGI 下建议 15~30，GDI 下建议 ≤3） |
| `lock_at_close` | 合盖到底自动锁屏（默认关） |

## 已知坑

详见 [AGENTS.md](AGENTS.md)（GL 窗口必须继承 `QOpenGLWidget`、截图反馈污染与自排除、bat 文件禁中文等）。

本副本调试过程中额外踩到、值得记一笔的：

- **满屏窗口是"抓屏黑洞"**：恰好铺满物理屏幕的窗口会被 Windows 走"全屏直通"呈现——GDI 抓屏完全看不到它，DXGI 抓屏则把它整块抓成纯黑。所以 `win_shrink_px` 必须 ≥ 1，且 `SetWindowDisplayAffinity` 的自我排除必须真正生效。
- **`#version 330 compatibility` 在 Intel Windows 驱动上会被直接拒绝**：该驱动的兼容模式只到 GLSL 1.20，报 `'varying' : not available in current GLSL version`，程序启动即崩。本项目改用 `330 core` + VAO/VBO，`textureLod` 在 core 下同样可用，**不要**改回 compatibility。
- **抓屏成本决定了效果上限**：只要玻璃处于显示状态，它显示的就是一张截图，帧率上限由抓屏速度决定（GDI ≈30 Hz 封顶、程序内实测 72~84 ms/次；DXGI 单次 6.6 ms）。想更跟手只能换更快的抓屏后端，或改用不做截屏的方案。
- **浓度映射的"黑洞区"**：`max_tilt_deg` 超过约 70° 后，逆投影会让视线大面积射出界面平面，画面成片变黑（88° 时拉满即全黑）。

## License

[MIT](LICENSE)

## Credits

- elijah-semyonov/DuoLikeAnimation — 逆投影模型与 Vogel 盘模糊公式
- chuspeeism/iphone-duo — mip LOD 分级采样与边缘覆盖率平滑
- DhananjayBhosale/MacDuo — 笔记本场景（铰链=屏幕底边，盖角度驱动）
- askmaddyy/FrostFold — 磨砂玻璃观感参数
- macOS 端传感器协议参考 [Mac-Duo by sumimakito](https://github.com/sumimakito/MacDuo) (Apache-2.0)
