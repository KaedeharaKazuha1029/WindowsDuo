# CircuitPython 版角度读取（替代 ESP-IDF 固件）

同一块板子（**YD-ESP32-S3 N16R8**）的另一种实现：不烧 ESP-IDF 固件，而是刷 CircuitPython 后放一个 `code.py`。

## 与 ESP-IDF 版的取舍

这段固件要干的活很轻：**400kHz 读 I2C 14 字节 → 两次 `atan2` → 互补滤波 → 每秒 100 行 JSON**，CircuitPython 完全够用。

| | ESP-IDF 版 | CircuitPython 版 |
|---|---|---|
| 迭代速度 | 改代码要重编译重烧 | 改 `code.py` 存盘即生效（秒级） |
| 运行开销 | 低（原生 C） | 高一些（解释器 + 忙等节拍） |
| 依赖 | 需要 ESP-IDF 工具链 | **无**（不需要任何第三方库） |
| 异常处理 | 崩溃自动重启 | 异常会停在 REPL，需要看串口 |

选择建议：

- **想改滤波参数、调采样率、试不同引脚** → 用 CircuitPython，改文本即可，不用每次重新编译烧录。
- **要长期稳定跑、追求最低开销** → 用 ESP-IDF 版（`prebuilt/` 里有编好的固件，烧录不需要装工具链）。

两个版本的 JSON 格式、`a`/`b` 轴定义、角度符号完全一致，**Windows 端无需改动**。

> **`print` 的坑**：CircuitPython 的 USB CDC 输出在"主机没开串口"或"没人读"时可能写满缓冲并**阻塞主循环**。
> `code.py` 里已经用 `supervisor.runtime.serial_connected` 做了保护：没连主机就不打印 JSON，循环照跑。

## 上手三步

### 1. 刷 CircuitPython

从 [circuitpython.org/board/yd_esp32_s3_n16r8](https://circuitpython.org/board/yd_esp32_s3_n16r8/) 下载 `.bin` 固件（本仓库不附带，请用官方或你自己的构建）。

先让板子进入下载模式：**按住 BOOT → 点一下 RESET → 松开 BOOT**（此时端口 PID 变为 `303A:1001`）。

```bash
esptool --chip esp32s3 --port COMx --before usb_reset --after no_reset write_flash 0x0 FIRMWARE.bin
```

把 `COMx` 换成你的端口、`FIRMWARE.bin` 换成刚下载的文件名（可直接把文件拖进终端）。
没装 esptool 的话先 `pip install esptool`。

刷完后**按一下 RESET** 启动。成功后系统会出现一个 `CIRCUITPY` U 盘和一个新串口（PID `303A:8166`，端口号可能和烧录前不同）。

### 2. 把 `code.py` 拷到 CIRCUITPY 盘根目录

```bash
# Windows
copy /Y esp32\circuitpython\code.py X:\code.py
# macOS / Linux
cp esp32/circuitpython/code.py /Volumes/CIRCUITPY/code.py
```

（`X:` 换成 CIRCUITPY 的盘符。**不需要 `lib` 目录**，代码只用 `board / busio / math / time / supervisor` 这几个内置模块。）

### 3. 验证

```bash
python esp32/debug_view.py            # 自动挑串口
python esp32/debug_view.py --port COMx  # 或手动指定
```

期望输出（JSON 格式与 ESP-IDF 版一致）：

```
[mpu] WHO_AM_I = 0x70 (MPU6500)
[mpu] MPU6050 初始化 OK [ESP32-S3 (YD-ESP32-S3 N16R8)] (I2C: SDA=GPIO8 SCL=GPIO9 @400kHz)
>>> 陀螺仪校准中... 请保持模块完全静止 3 秒 <<<
[mpu] 校准完成! 零漂偏移: gx=.. gy=.. gz=..
[mpu] 开始输出角度 @100Hz: {"a":主轴,"b":副轴}
{"a":-72.41,"b":4.65}
...
[mpu] 实测 100.0 Hz, a=-72.41 b=4.65     <- 每 5 秒一行，用来确认真的跑到 100Hz
```

## 移植时踩到的 5 个 CircuitPython 坑（代码里已处理）

这些是写这份 `code.py` 时会直接撞上的差异，供改动时参考：

1. **`busio.I2C` 没有 `readfrom_mem` / `writeto_mem`** —— 那是 Adafruit `I2CDevice` 的方法。
   裸用 busio 要用 `writeto(addr, bytes([reg, val]))` 和
   `writeto_then_readfrom(addr, bytes([reg]), buf)`。
2. **busio 的读写方法都要求先锁定总线**，否则 `RuntimeError: 函数需要锁定`。
   即 `while not i2c.try_lock(): pass` … `finally: i2c.unlock()`。
3. **`int.from_bytes(..., signed=True)` 抛 `NotImplementedError`** —— CircuitPython 只实现了 CPython 的子集。
   得手写补码：`v = (b[i] << 8) | b[i+1]; v - 65536 if v & 0x8000 else v`。
4. **Python 的 int 按值传递**：把节拍写成 `def _sleep_until(tick): tick += ...` 是无效的，
   调用方的 `tick` 永不前进 → 节拍完全失效（现象是采样率远超设定值，互补滤波的 `dt` 也跟着错）。
   必须 `tick = _sleep_until(tick)` 这样接收返回值。
5. **REPL 交互**：`Ctrl-C` 之后**回显的第一个字符会被吃掉**，直接发 `import ...` 会变成 `mport ...` 报
   `SyntaxError`。先发一个空行垫掉再发命令。

## 关于 WHO_AM_I（重要）

市面上标着 "MPU6050" 的模块，很多实际是 **MPU6500 系**（`WHO_AM_I = 0x70`）而非 `0x68` 的 MPU6050，尤其廉价克隆模块。常见值：

| 值 | 芯片 |
|---|---|
| `0x68` | MPU6050 |
| `0x70` | MPU6500 |
| `0x71` | MPU9250 / MPU6515 |
| `0x73` | MPU9255 |

MPU6500/6050/9250 的**寄存器映射与量程换算一致**（`ACCEL_XOUT_H=0x3B`、`PWR_MGMT_1=0x6B`、
±2g→16384 LSB/g、±250dps→131 LSB/(°/s)），所以同一套代码都能用，**不要因为 WHO_AM_I 不是 0x68 就拒绝启动**。

> `code.py` 只打印型号、不做校验，就是为了避免"明明是好的模块，却卡在'未就绪'重试循环里"。
> ESP-IDF 版同样是只打印不校验。

## Windows 端要不要改？

**不用改**：

- JSON 格式、`a`/`b` 的轴定义、角度符号与 ESP-IDF 版一致；同一安装方式从 ESP-IDF 切换过来时，
  可以沿用原来测好的轴与端点。原掌控板默认用 `a`；沿 X 轴安装的 `b` 轴配置见[标定示例](../../win/calibration-yd-esp32s3.example.json)。

- JSON 格式、`a`/`b` 的轴定义、角度符号与 ESP-IDF 版一致；
- 标定值（`axis` / `angle_open` / `angle_closed`）取决于**你的模块怎么贴**，两个固件都通用，不用因为换固件而重测；
- CircuitPython 仍走原生 USB，`win/config.json` 的 `port: "auto"` 会自动识别，无需手填端口。

一个小差异：CircuitPython 版**对两个轴都做了互补滤波**（ESP-IDF 版只有主轴滤波、副轴是原始加速度角），
所以副轴曲线更平滑（静止漂移约 0.1° 量级，对比 ESP-IDF 版副轴 ±0.6°）。静止时的角度值不变，**标定无需重测**。

## 如果 100Hz 达不到

`code.py` 顶部把 `SAMPLE_HZ` 调到 `50` 即可（Windows 端有 EMA 平滑，50Hz 观感差别很小）。
也可以把 `I2C_FREQ` 从 `400000` 降到 `100000` 提高长线稳定性。

## 想回到 ESP-IDF 版

```bash
esp32/mpu6050_angle/prebuilt/flash_prebuilt.bat COMx
```

同样是先 BOOT+RST 进下载模式，烧完按一下 RESET。
