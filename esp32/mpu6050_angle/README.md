# MPU6050 角度读取固件（iPhone Duo 悬浮玻璃项目 · Stage 1）

ESP-IDF v5.4.4 · 目标芯片 ESP32 (D0WDQ6) · 已编译并烧录至 COM3 ✅

## 接线（MPU6050 GY-521 ↔ 乐动掌控1.0 专用 I2C 口）✅ 已验证

板子为盛思乐动掌控 1.0，主控 = 掌控板。官方 mPython 固件 `machine_pin.c` 定义：
金手指 **P19 = SCL → GPIO22**，**P20 = SDA → GPIO23**（与板载 OLED/六轴共享总线）。

| MPU6050 引脚 | 掌控板 I2C 接口 | 实际 GPIO |
|---|---|---|
| VCC | VCC | 3.3V |
| GND | GND | — |
| SCL | SCL | GPIO22 |
| SDA | SDA | GPIO23 |
| AD0 | 悬空 | 地址 0x68 |

固件已按此配置（`I2C_SDA_IO=23, I2C_SCL_IO=22`）。MPU6050(0x68) 与板载
OLED(0x3C)/六轴(0x26)/地磁(0x30) 无地址冲突，可共存。

**实测**：100Hz 稳定输出，静止抖动 ±0.05°，600 帧/6s 零丢帧。

## 安装位置

MPU6050 模块**平贴在笔记本屏幕背盖上盖内侧**（芯片正面朝外），3M 胶固定，
USB 线从转轴缝隙引出。模块绕水平转轴转动即产生 0°~140° 开合角。

## 串口输出

- `COM3`，`115200`，100Hz
- 格式：`{"a":87.50}`（单位：度，未做绝对角度校准，为原始 pitch）
- 启动日志含 `WHO_AM_I = 0x68` 与 `MPU6050 init OK`

## 验证

```
D:\Espressif\python_env\idf5.4_py3.11_env\Scripts\python.exe D:\KaiFa\find\duo\esp32\read_serial.py 8
```

## 重新编译/烧录

```
D:\Espressif\python_env\idf5.4_py3.11_env\Scripts\python.exe run_build.py -p COM3 flash
```

（`run_build.py` 是环境包装器：在 Python 内设置 PATH/IDF_PATH 后调用 idf.py，
规避本机 shell 无法传递 IDF 环境的问题。）

## 滤波参数（main 文件顶部可调）

- `CF_GYRO=0.98 / CF_ACC=0.02`：互补滤波权重
- `GYRO_SIGN=1`：开合时角度乱跳改为 `-1`；改 `0` 则纯加速度计+EMA（稳定但略迟滞）
- `OUT_ALPHA=0.3`：输出 EMA 平滑度

## 下一步（Stage 2 · Windows 端）

串口读取 → 角度平滑 → 全屏玻璃 Overlay（blur/透明度随角度）。
