# MPU6050 角度读取固件（iPhone Duo 悬浮玻璃 · Stage 1）

ESP32 / ESP32-S3 · ESP-IDF v5.x · 100Hz 串口输出 `{"a":主角度,"b":副轴角度}`

> **验证状态（重要）**
> - ✅ 固件已在**本机 ESP-IDF v5.3.1** 下编译通过：`esp32s3` 目标、`mpu6050_angle.bin` 约 223 KB（app 分区 79% 空闲）。
> - ✅ **已在 YD-ESP32-S3 (N16R8) 实机烧录并启动成功**（2026-09-27）：Flash 内三个镜像 `verify_flash` 全部 digest matched；
>   硬件复位后应用正常启动，日志经内置 USB-Serial-JTAG 输出到 **COM3 @115200**；未接传感器时按 **精确 2 秒**间隔重试：
>   ```
>   E (28162) i2c.master: I2C transaction unexpected nack detected
>   E (28162) mpu6050: mpu_init(122): read WHO_AM_I fail
>   E (28162) mpu6050: MPU6050 未就绪 (err=0x103) [ESP32-S3 (YD-ESP32-S3 N16R8)]。
>            检查接线: VCC->3V3 GND->GND SCL->GPIO9 SDA->GPIO8, 且 AD0 接 GND(地址 0x68), 2 秒后重试...
>   ```
>   这条日志同时证实了：目标芯片、Flash 内容、启动流程、USB 日志通路、I2C 出错分支全部正常。
> - ❌ **传感器本体仍未验证**：MPU6050 还没到货，接线、`WHO_AM_I=0x68`、零漂校准、100Hz 输出稳定性、角度标定都没实测。
> - 原 README 里"已编译并烧录至 COM3 ✅、实测 100Hz 稳定输出"是**原作者在他自己机器 + 掌控板**上的结果。

> 注：本机实测的芯片信息为 `ESP32-S3 (QFN56) (revision v0.2)`、`Embedded PSRAM 8MB`、Flash 16MB（quad，3.3V）。

## 一、支持的板子与 I2C 引脚

固件按 `idf.py set-target` 的目标芯片自动选引脚，换板子不用改代码（见 `main/mpu6050_angle_main.c` 顶部）。

| 板子 | 目标 | SDA | SCL | 说明 |
|---|---|---|---|---|
| **YD-ESP32-S3 (N16R8)** | `esp32s3` | **GPIO8** | **GPIO9** | 都在左侧排针；控制台走内置 USB-Serial-JTAG |
| 盛思乐动掌控1.0 / 掌控板 | `esp32` | GPIO23 | GPIO22 | 专用 I2C 口 = 金手指 P19(SCL)/P20(SDA) |

**ESP32-S3 选 GPIO8/9 的理由**：非 strapping、非 USB、非 UART 控制台、非板载 RGB。
要避开的脚：GPIO0(BOOT 键)、GPIO3/45/46(strapping)、GPIO19/20(USB)、GPIO43/44(UART0)、
GPIO48(板载 RGB)、GPIO35~37(N16R8 的 8MB PSRAM 可能占用)、GPIO26~34(内部 Flash/PSRAM，未引出)。
备选组合：GPIO4/5、GPIO17/18、GPIO47/21。

## 二、接线（MPU6050 GY-521 ↔ 板子）

| MPU6050 引脚 | 接到 | 说明 |
|---|---|---|
| VCC | **3V3** | GY-521 板载 LDO，3.3V/5V 都能供；**裸 MPU6050 模块必须 3.3V** |
| GND | GND | 必须共地 |
| SCL | 上表的 SCL | I2C 时钟 |
| SDA | 上表的 SDA | I2C 数据 |
| AD0 | **GND 或悬空** | 决定地址 **0x68**（固件写死 0x68；接 3V3 会变 0x69） |
| INT / XDA / XCL | 不接 | 固件用轮询 |

- 杜邦线尽量短（<20cm）；400kHz 下长线/劣质线容易读失败。
- SCL/SDA **接反是最常见的错误**，现象是 `WHO_AM_I` 读不到、固件一直打印"未就绪…重试"。
- 启动日志里会回显它期望的引脚，接线时照着日志接：
  `MPU6050 未就绪 (err=0x103) [ESP32-S3 (YD-ESP32-S3 N16R8)]。检查接线: VCC->3V3 GND->GND SCL->GPIO9 SDA->GPIO8 …`

## 三、安装位置

模块**平贴在笔记本屏幕背盖上盖内侧**（芯片正面朝外），3M 胶固定，USB 线从转轴缝隙引出。
让模块的 **Y 轴（丝印 Y 方向）平行于笔记本转轴**——固件默认按绕 Y 轴算角度（`HINGE_AXIS = AXIS_Y`）。
若掰动模块时 `a` 不变而 `b` 变，把 `HINGE_AXIS` 改成 `AXIS_X` 重新烧录。

## 四、本机构建/烧录

本机装的是 **ESP-IDF v5.3.1**（`D:\Espressif\frameworks\esp-idf-v5.3.1`，python 环境 `idf5.3_py3.11_env`）。

两种用法，二选一：

**A. 用 `build.bat`（会自动找到 IDF 的 python 解释器，最省事）**

```bat
cd /d <本仓库>\esp32\mpu6050_angle
build.bat                       :: 只编译
build.bat -p COM5 flash monitor :: 烧录 + 看日志
build.bat set-target esp32s3    :: 换目标芯片
```

**B. 直接调 `run_build.py`**（内部会设好 IDF_PATH/PATH 再执行 idf.py，规避本机 shell 不透传 IDF 环境的问题）

```bat
D:\Espressif\python_env\idf5.3_py3.11_env\Scripts\python.exe run_build.py build
D:\Espressif\python_env\idf5.3_py3.11_env\Scripts\python.exe run_build.py -p COM5 flash monitor
```

> `run_build.py` 会自动探测 `D:\Espressif` 下的 IDF 版本、python 环境与各工具目录，
> 也会把工作目录切到自己所在的工程（不再写死原作者的 IDF 5.4.4 与 `D:\KaiFa\find\duo\esp32`）。

### 进下载模式（烧录前必须）

芯片必须处于 ROM 下载模式才能烧录。**本机实测有效的完整流程**（YD-ESP32-S3）：

1. **按住板上 BOOT 键** → 点一下 **RESET/EN**（或重新插拔 USB）→ **松开 BOOT**；
2. 松手后会出现一个**新的串口**，它是 ROM 的 USB Serial/JTAG：本机实测 PID 从 `303A:8166`（CircuitPython）变成
   **`303A:1001`**，端口号也可能变（实测是 **COM3**，而原来是 COM5）。用 `idf.py -p COMx` 指定它；
3. 烧录：`idf.py -p COM3 flash`，或直接用 esptool（`build\flash_args` 里已经写好参数）：
   ```
   esptool --chip esp32s3 --port COM3 --before usb_reset --after no_reset write_flash @flash_args
   ```
   （在 `build` 目录下执行。注意用 `--before usb_reset`：USB-JTAG 口的 DTR/RTS 是虚拟线，`no_reset`/`default_reset` 那条路会中途掉线报 `Cannot configure port`。）
4. **烧完必须手动按一下 RESET/EN（或拔插一次 USB）**，芯片才会从 Flash 启动应用。
   ⚠️ 这一步不能省：USB-JTAG 板子上 `--after hard_reset` 只是拉 RTS 虚拟线、对芯片无效，
   `esptool run` 也只会回一句 `Staying in bootloader`，芯片会一直停在下载模式（表现为"烧录成功但串口一行日志都没有"）。
5. 启动后再 `idf.py -p COM3 monitor` 看日志。

**排障**：如果按 BOOT+RESET 后**没有**出现新串口：
- 打开设备管理器看有没有带感叹号的"未知 USB 设备"；ESP32-S3 的 USB-Serial-JTAG 靠 Windows 的 CDC 驱动，必要时装 ESP-IDF 自带的驱动（`D:\Espressif\tools\idf-driver\...`）；
- 或者退到最经典的路子：用 USB-TTL 串口模块接 **UART0（GPIO43=TX / GPIO44=RX，共地）**，烧录时 GPIO0 拉低，`idf.py -p COMx flash`（此时要记得把控制台改回 UART0，见下）。

> 另外：**CircuitPython 的软复位进下载模式在本板无效**。用
> `microcontroller.on_next_reset = RunMode.BOOTLOADER; microcontroller.reset()`
> 只会让串口消失 0.4s，然后 8.6s 后以 CircuitPython（`303A:8166`）回来，ROM 的 USB-JTAG 从不出现，
> esptool 报 `No serial data received`。只能走硬件 BOOT 键。
>
> 还有：本机 `erase_flash` 在擦到一半时 USB 掉线过（`Cannot configure port ... PermissionError(13)`），
> 之后用 `--before usb_reset` 重新 `write_flash` 就成功了，三个镜像 `verify_flash` 全部 matched。
> 所以中途报错不必慌，重新进下载模式再写一次、然后用 `verify_flash` 校验即可。

### 给另一块相同的板子刷（不用装 ESP-IDF）

`prebuilt/` 里是编好的成品。换板子时**不需要重新编译、也不需要 ESP-IDF**，只要 esptool：

| 文件 | 说明 |
|---|---|
| `prebuilt/WindowsDuo-esp32s3-n16r8.bin` | **合并镜像**：bootloader@0x0 + 分区表@0x8000 + 应用@0x10000，288,944 字节，烧到 **0x0** 即可 |
| `prebuilt/flash_prebuilt.bat` | 一键烧录脚本（自动找带 esptool 的解释器；纯 ASCII + CRLF） |
| `prebuilt/raw/*.bin` | 分开的三个镜像，排障或只想重烧某一段时用（地址 0x0 / 0x8000 / 0x10000） |

步骤（**两步按键都不能少**）：

1. 按住 **BOOT** → 点一下 **RESET** → 松开 **BOOT**（进下载模式，端口 PID 变 `303A:1001`）
2. `esp32\mpu6050_angle\prebuilt\flash_prebuilt.bat COM3`
   （不带端口号直接运行会列出当前串口；换板子后串口号可能不是 COM3，先看设备管理器）
3. **按一下 RESET**，芯片才会从 Flash 启动应用

没装 esptool 的话：`python -m pip install esptool`。要彻底清空再写：`flash_prebuilt.bat COM3 erase`（擦 16MB 约 30s）。

**改了固件代码后要重新生成合并镜像**：

```bat
cd esp32\mpu6050_angle
build.bat
cd build
esptool --chip esp32s3 merge_bin -o WindowsDuo-esp32s3-n16r8.bin --flash_mode dio --flash_freq 80m --flash_size 16MB ^
        0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin 0x10000 mpu6050_angle.bin
```

（合并镜像的三个切片与源镜像逐字节一致，已用 SHA256 校验过。）

**换板子要注意的三件事**：

- **传感器标定跟"模块怎么贴"有关，跟板子无关**：同一台笔记本、同一种贴法 → `win/config.json` 的 `angle_closed / angle_open` 直接沿用；换笔记本或换贴法 → 重新做两点标定。
- **陀螺仪零漂校准是每次上电自动做的**（3 秒静止），换板子不用改任何参数。
- **两块相同的板子同时插在电脑上时**，Windows 端的 `port: "auto"` 无法区分（两块都排第一优先级），要在 `win/config.json` 里显式写 `"port": "COM4"` 这类具体端口。



## 五、验证角度输出

```bat
:: 板子烧好后（固件会先做 3 秒零漂校准，期间保持静止）
python esp32\debug_view.py --port COM3
```

> 端口号按实际情况填：本机实测烧了本项目固件后是 **COM3**（`303A:1001`）；换板子/换 USB 口可能变成 COM4、COM5。
> 不带 `--port` 时默认 COM3。**注意串口是独占的**——`debug_view.py` 开着时 Windows 端打不开串口，反之亦然。

`debug_view.py` 实时显示主轴角度 `a`、副轴 `b`、进度条与频率。

`esp32\read_serial.py` 里的端口**写死 COM3**，用之前先改成你的口（或直接用 debug_view.py）。

启动日志期望：

```
I (xxx) mpu6050: WHO_AM_I = 0x68 (期望 0x68)
I (xxx) mpu6050: >>> 陀螺仪校准中... 请保持模块完全静止 3 秒 <<<
I (xxx) mpu6050: 校准完成! 零漂偏移: gx=.. gy=.. gz=..
I (xxx) mpu6050: MPU6050 初始化 OK [ESP32-S3 (YD-ESP32-S3 N16R8)] (I2C: SDA=GPIO8 SCL=GPIO9 @400kHz)
I (xxx) mpu6050: 开始输出角度 @100Hz: {"a":主角度,"b":副轴角度}
```

## 六、调试参数（`main/mpu6050_angle_main.c` 顶部）

- `HINGE_AXIS`：默认 `AXIS_Y`（模块 Y 轴平行转轴）；a/b 反了就改 `AXIS_X`
- `HINGE_SIGN`：开盖时角度变大还是变小不符预期就改 `-1`
- `CF_GYRO=0.98 / CF_ACC=0.02`：互补滤波权重
- `OUT_ALPHA=0.3`：输出 EMA 平滑度
- `I2C_FREQ_HZ=400000`：读失败多可降到 100000

## 七、sdkconfig.defaults 的两个坑（踩过，别再踩）

1. **基文件 `sdkconfig.defaults` 必须存在**（哪怕只写注释）。ESP-IDF 只有在它存在时才会
   继续加载 `sdkconfig.defaults.<target>`（IDF v5.3.1 `tools/cmake/project.cmake` 630~636 行）。
   基文件不存在时，按目标的 defaults 会被**静默忽略**——表现为"改了 defaults 完全没生效"。
2. **这些文件必须纯 ASCII**。kconfgen 用系统 locale 编码读它们（本机是 GBK），
   UTF-8 的中文注释会让配置阶段直接 `UnicodeDecodeError` 中断。跟 `.bat` 的要求一样。

另外：`idf.py set-target` 只改变"尚未设置"的项——如果 `sdkconfig` 里已有旧值（例如从上一次
`esp32` 配置带过来的 `CONFIG_ESPTOOLPY_FLASHSIZE_2MB`），defaults 不会覆盖它。换板子时
稳妥做法是删掉 `sdkconfig` 再 `set-target`。

## 八、这个目标的 sdkconfig 设置（`sdkconfig.defaults.esp32s3`）

| 配置 | 值 | 为什么 |
|---|---|---|
| `CONFIG_ESPTOOLPY_FLASHSIZE_16MB` | 16MB | N16R8 模块是 16MB Flash |
| `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG` | y | 板子只有原生 USB 口，日志必须走内置 USB-Serial-JTAG；保持默认的 UART0 会在 USB 上什么都看不到 |

换回掌控板：`build.bat set-target esp32`（`sdkconfig.defaults.esp32` 里是 2MB + UART0）。

## 下一步（Stage 2 · Windows 端）

Windows 端已经完成（`win/glass_overlay.py`）。硬件到位后按
接线 → 烧录 → 零漂校准 → 两点标定 `angle_closed` / `angle_open` → 端到端联调 的顺序推进。
