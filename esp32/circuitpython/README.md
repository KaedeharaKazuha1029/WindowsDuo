# CircuitPython 版角度读取（替代 ESP-IDF 固件）

同一块板子（**YD-ESP32-S3 N16R8**）的另一种实现：不烧 ESP-IDF 固件，而是刷 CircuitPython 后放一个 `code.py`。

## 结论：能，而且难度不大

这段固件要干的活很轻：**400kHz 读 I2C 14 字节 → 两次 `atan2` → 互补滤波 → 每秒 100 行 JSON**。
CircuitPython 完全够用，而且——

- **不需要任何第三方库**：直接读写 MPU6050 寄存器（`i2c.readfrom_mem / writeto_mem`），不用装 Adafruit 库包；
- **不用编译**：改 `code.py` 存回 `CIRCUITPY` 盘就生效（调滤波参数、改引脚、改采样率都是改文本）；
- **不用装 ESP-IDF**：只在这台电脑上拷文件。

代价与风险：

| | ESP-IDF 版（当前在跑） | CircuitPython 版 |
|---|---|---|
| 迭代速度 | 改代码要重编译重烧（1~3 分钟） | 改 `code.py` 存盘即生效（秒级） |
| 运行开销 | 低（原生 C） | 高一些（解释器 + 忙等节拍） |
| 100Hz 稳定性 | 实测稳（`fps=100`） | 应该没问题，但要实测；脚本会每 5 秒打印实测 Hz |
| 掉电/异常 | 崩溃会重启 | 异常会停在 REPL，需要看串口 |
| 依赖 | ESP-IDF 工具链 | 无 |
| 刷回去 | `prebuilt\flash_prebuilt.bat COMX` | 同一套 BOOT+RST 流程 |

> **`print` 的坑**：CircuitPython 的 USB CDC 输出在"主机没开串口"或"没人读"时可能写满缓冲并**阻塞主循环**。
> `code.py` 里已经用 `supervisor.runtime.serial_connected` 做了保护：没连主机就不打印，循环照跑。

## 上手三步

### 1. 刷 CircuitPython（用你放在工作区的那个官方固件）

```
:: 按住 BOOT + 点一下 RESET + 松开 BOOT（进下载模式，端口 PID 变成 303A:1001）
esptool --chip esp32s3 --port COM3 --before usb_reset --after no_reset write_flash 0x0 ^
        "C:\Users\L\Desktop\DeepSeek\adafruit-circuitpython-yd_esp32_s3_n16r8-zh_Latn_pinyin-10.3.1.bin"
:: 再按一下 RESET 启动
```

刷成功后 Windows 会出现一个 `CIRCUITPY` U 盘和一个新的串口（之前实测是 **COM5**，PID `303A:8166`）。

### 2. 把 `code.py` 拷到 CIRCUITPY 盘根目录

```bat
copy /Y "C:\Users\L\Desktop\DeepSeek\WindowsDuo-bugfix\esp32\circuitpython\code.py" X:\code.py
```

（`X:` 换成 CIRCUITPY 盘符。**不需要 lib 目录**。）

### 3. 验证

```bat
python esp32\debug_view.py --port COM5
```

期望输出（和 ESP-IDF 版一致的 JSON）：

```
[mpu] WHO_AM_I = 0x68 (期望 0x68)
[mpu] MPU6050 初始化 OK [ESP32-S3 (YD-ESP32-S3 N16R8)] (I2C: SDA=GPIO8 SCL=GPIO9 @400kHz)
>>> 陀螺仪校准中... 请保持模块完全静止 3 秒 <<<
[mpu] 校准完成! 零漂偏移: gx=.. gy=.. gz=..
[mpu] 开始输出角度 @100Hz: {"a":主轴,"b":副轴}
{"a":-82.41,"b":4.65}
...
[mpu] 实测 100.0 Hz, a=-82.41 b=4.65     <- 每 5 秒一行，用来确认真的跑到 100Hz
```

## 实测结果（2026-09-27，YD-ESP32-S3 + 手上的模块）

| 项目 | 结果 |
|---|---|
| 板子自报 | `boot_out.txt`: CircuitPython 10.3.1 / Board ID `yd_esp32_s3_n16r8` / MAC `84:C7:BB:70:63:2C` |
| 芯片识别 | **`WHO_AM_I = 0x70`，是 MPU6500 系（不是 0x68 的 MPU6050）** —— 见下方"关于 WHO_AM_I" |
| I2C | `SDA=GPIO8 / SCL=GPIO9 @400kHz`，读写正常 |
| 采样率 | **实测 100.0 ~ 100.2 Hz**（脚本每 5 秒打印一次） |
| 零漂校准 | 3 秒静止通过，偏移 `gx=8.11 gy=14.20 gz=3.02 dps`（这颗廉价克隆芯片偏置较大，但被正常扣掉了） |
| 角度噪声 | 静止 15 秒内漂移约 **0.05°**（ESP-IDF 版的 `b` 是原始加速度角，噪声 ±0.6°）——CP 版两轴都做了互补滤波，明显更平滑 |
| 原始寄存器校验 | REPL 直读: `ax=+0.863 ay=-0.140 az=-0.261 g`，`|a|=0.912 g`（克隆芯片灵敏度偏差约 9%，对 atan2 角度无影响） |

## 移植时踩到的 5 个 CircuitPython 坑（都已修好）

1. **`busio.I2C` 没有 `readfrom_mem` / `writeto_mem`** —— 那是 Adafruit `I2CDevice` 的方法。
   裸用 busio 要用 `writeto(addr, bytes([reg, val]))` 和
   `writeto_then_readfrom(addr, bytes([reg]), buf)`。
2. **busio 的读写方法都要求先锁定总线**，否则 `RuntimeError: 函数需要锁定`。
   即 `while not i2c.try_lock(): pass` … `finally: i2c.unlock()`。
3. **`int.from_bytes(..., signed=True)` 抛 `NotImplementedError`** —— CircuitPython 只实现了子集，
   得手写补码：`v = (b[i] << 8) | b[i+1]; v - 65536 if v & 0x8000 else v`。
4. **Python 的 int 传值**：把"下一个节拍"写成 `def _sleep_until(tick): tick += ...` 是无效的，
   调用方的 `tick` 永不前进 → 节拍失效（实测跑到 **406 Hz**，互补滤波的 DT 也跟着错 4 倍）。
   必须 `tick = _sleep_until(tick)` 这样接收返回值。
5. **REPL 交互**：`Ctrl-C` 之后**回显的第一个字符会被吃掉**，直接发 `import ...` 会变成 `mport ...` 报
   `SyntaxError`。先发一个空行垫掉再发命令。

## 关于 WHO_AM_I（重要）

本机这块模块实测 **`0x70` = MPU6500 系**，不是 MPU6050。常见值：

| 值 | 芯片 |
|---|---|
| `0x68` | MPU6050 |
| `0x70` | MPU6500 |
| `0x71` | MPU9250 / MPU6515 |
| `0x73` | MPU9255 |

MPU6500/6050/9250 的**寄存器映射与量程换算一致**（`ACCEL_XOUT_H=0x3B`、`PWR_MGMT_1=0x6B`、
±2g→16384 LSB/g、±250dps→131 LSB/(°/s)），所以同一套代码都能用，**不要因为 WHO_AM_I 不是 0x68 就拒绝启动**。

> ESP-IDF 版当年没发现这点，是因为那段 C 代码只 `ESP_LOGI` 打印 WHO_AM_I、并不校验；
> 而 `code.py` 一开始写了严格校验，于是卡在"未就绪"重试循环里不动 —— 已改成只提示不拒绝。

## Windows 端要不要改？

**不用改任何东西**（除了可能要指定端口）：
JSON 格式、a/b 的轴定义、角度符号都与 ESP-IDF 版一致，所以
`win/config.json` 里现有的 `"axis": "b"`、`angle_open: -82.5`、`angle_closed: -38.35` 全部照旧有效。

一个小差异：CircuitPython 版**对两个轴都做了互补滤波**（ESP-IDF 版只有 `a` 滤波，`b` 是原始加速度角），
所以 `b` 会比以前更平滑（静止噪声从 ±0.6° 降到 ±0.1° 量级），静止时的角度值不变，标定值无需重测。

端口方面：CircuitPython 仍用原生 USB，`win/config.json` 的 `port: "auto"` 会优先挑 Espressif 口，照样自动找到。

## 如果 100Hz 达不到

`code.py` 顶部把 `SAMPLE_HZ` 调到 `50` 即可（Windows 端有 EMA 平滑，50Hz 观感差别很小）。
也可以把 `I2C_FREQ` 从 `400000` 降到 `100000` 提高长线稳定性。

## 想回到 ESP-IDF 版

```
WindowsDuo-bugfix\esp32\mpu6050_angle\prebuilt\flash_prebuilt.bat COM3
```

同样先 BOOT+RST 进下载模式，烧完按一下 RESET。
