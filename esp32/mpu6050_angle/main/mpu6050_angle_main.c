/*
 * mpu6050_angle_main.c  v2
 *
 * iPhone Duo「悬浮玻璃」效果 - 角度读取固件 (盛思乐动掌控1.0 + MPU6050)
 *
 * 启动流程（串口可见）:
 *   1. I2C 初始化 + WHO_AM_I 校验
 *   2. 陀螺仪零漂校准: 3 秒采样, 静止检测, 失败自动重试
 *   3. 100Hz 角度输出 (互补滤波, 陀螺仪零漂已扣除)
 *
 * 串口输出: COM3 115200, JSON 行 {"a":主角度,"b":副轴角度}
 *   a = 主轴角度 (HINGE_AXIS 决定, 默认绕 Y 轴)
 *   b = 另一轴的角度 (仅调试用: 用于判断模块安装方向)
 *
 * 装贴建议: 让模块的 Y 轴(丝印 Y 方向)平行于笔记本转轴。
 * 如果掰动模块时 a 不变而 b 变 → 把 HINGE_AXIS 改为 AXIS_X 重新烧录。
 */

#include <stdio.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_check.h"
#include "driver/i2c_master.h"

static const char *TAG = "mpu6050";

/* ---------------- 配置 ---------------- */
/* 盛思乐动掌控1.0（主控=掌控板）：专用 I2C 接口 = 金手指 P19/P20
 * 官方固件 machine_pin.c: P19=SCL->GPIO22, P20=SDA->GPIO23 */
#define I2C_SDA_IO      23
#define I2C_SCL_IO      22
#define I2C_FREQ_HZ     400000
#define MPU_ADDR        0x68        // AD0 悬空/GND = 0x68

#define SAMPLE_HZ       100
#define SAMPLE_DT       (1.0f / SAMPLE_HZ)

/*
 * 铰链轴选择:
 *   AXIS_Y(默认): 模块 Y 轴平行于转轴, 角度 = 绕 Y 轴旋转
 *   AXIS_X      : 模块 X 轴平行于转轴, 角度 = 绕 X 轴旋转
 * 方向: 若"开盖时角度变小", 把 HINGE_SIGN 改为 -1
 */
#define AXIS_Y          0
#define AXIS_X          1
#define HINGE_AXIS      AXIS_Y
#define HINGE_SIGN      1

#define CF_GYRO         0.98f
#define CF_ACC          0.02f
#define OUT_ALPHA       0.3f
#define ACC_LP_ALPHA    0.2f        // 加速度计角度低通
/* -------------------------------------- */

/* MPU6050 寄存器 */
#define REG_SMPLRT_DIV  0x19
#define REG_CONFIG      0x1A
#define REG_GYRO_CFG    0x1B
#define REG_ACCEL_CFG   0x1C
#define REG_PWR_MGMT1   0x6B
#define REG_WHO_AM_I    0x75
#define REG_ACCEL_XOUT  0x3B

typedef struct {
    float ax, ay, az;   // g
    float gx, gy, gz;   // deg/s (原始, 未扣零漂)
} imu_sample_t;

static i2c_master_dev_handle_t s_dev;

static esp_err_t mpu_write(uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = { reg, val };
    return i2c_master_transmit(s_dev, buf, sizeof(buf), 100);
}

static esp_err_t mpu_read(uint8_t reg, uint8_t *data, size_t len)
{
    return i2c_master_transmit_receive(s_dev, &reg, 1, data, len, 100);
}

static esp_err_t mpu_read_sample(imu_sample_t *s)
{
    uint8_t d[14];
    ESP_RETURN_ON_ERROR(mpu_read(REG_ACCEL_XOUT, d, 14), TAG, "read fail");
    s->ax = (int16_t)((d[0] << 8) | d[1]) / 16384.0f;   // ±2g
    s->ay = (int16_t)((d[2] << 8) | d[3]) / 16384.0f;
    s->az = (int16_t)((d[4] << 8) | d[5]) / 16384.0f;
    s->gx = (int16_t)((d[8] << 8) | d[9]) / 131.0f;     // ±250dps
    s->gy = (int16_t)((d[10] << 8) | d[11]) / 131.0f;
    s->gz = (int16_t)((d[12] << 8) | d[13]) / 131.0f;
    return ESP_OK;
}

static esp_err_t mpu_init(void)
{
    uint8_t who = 0;
    ESP_RETURN_ON_ERROR(mpu_read(REG_WHO_AM_I, &who, 1), TAG, "read WHO_AM_I fail");
    ESP_LOGI(TAG, "WHO_AM_I = 0x%02X (期望 0x68)", who);

    ESP_RETURN_ON_ERROR(mpu_write(REG_PWR_MGMT1, 0x00), TAG, "wake");
    vTaskDelay(pdMS_TO_TICKS(50));
    ESP_RETURN_ON_ERROR(mpu_write(REG_SMPLRT_DIV, 0x00), TAG, "smpl");
    ESP_RETURN_ON_ERROR(mpu_write(REG_CONFIG, 0x03), TAG, "dlpf");       // DLPF 44Hz
    ESP_RETURN_ON_ERROR(mpu_write(REG_GYRO_CFG, 0x00), TAG, "gyro");     // ±250dps
    ESP_RETURN_ON_ERROR(mpu_write(REG_ACCEL_CFG, 0x00), TAG, "accel");   // ±2g
    return ESP_OK;
}

/* 加速度计角度: 绕 Y 轴 (AXIS_Y) 或绕 X 轴 (AXIS_X) */
static inline float acc_angle_axis(const imu_sample_t *s, int axis)
{
    if (axis == AXIS_Y)
        return atan2f(-s->ax, sqrtf(s->ay * s->ay + s->az * s->az)) * 57.29578f;
    else
        return atan2f(s->ay, sqrtf(s->ax * s->ax + s->az * s->az)) * 57.29578f;
}

static inline float gyro_axis(const imu_sample_t *s, int axis)
{
    return (axis == AXIS_Y) ? s->gy : s->gx;
}

/* ---------- 陀螺仪零漂校准: 3s 采样 + 静止检测, 失败重试 ---------- */
static void gyro_calibrate(float *off_gx, float *off_gy, float *off_gz)
{
    const int N = 300;                       // 3s @ 100Hz
    for (;;) {
        ESP_LOGW(TAG, ">>> 陀螺仪校准中... 请保持模块完全静止 3 秒 <<<");
        float sx = 0, sy = 0, sz = 0;
        float amag_min = 1e9f, amag_max = -1e9f;
        imu_sample_t s;
        bool ok = true;
        TickType_t wake = xTaskGetTickCount();

        for (int i = 0; i < N; i++) {
            if (mpu_read_sample(&s) != ESP_OK) {
                ESP_LOGE(TAG, "校准期间 I2C 读取失败, 重试");
                ok = false;
                break;
            }
            sx += s.gx; sy += s.gy; sz += s.gz;
            float amag = sqrtf(s.ax * s.ax + s.ay * s.ay + s.az * s.az);
            if (amag < amag_min) amag_min = amag;
            if (amag > amag_max) amag_max = amag;
            vTaskDelayUntil(&wake, pdMS_TO_TICKS(1000 / SAMPLE_HZ));
        }
        if (!ok) { vTaskDelay(pdMS_TO_TICKS(500)); continue; }

        /* 静止检测: 加速度模长波动应 < 0.05g (纯旋转会改变模长分布? 模长不变, 但运动有抖动) */
        if (amag_max - amag_min > 0.05f) {
            ESP_LOGW(TAG, "检测到晃动(幅值波动 %.3fg), 重新校准...", amag_max - amag_min);
            continue;
        }
        *off_gx = sx / N; *off_gy = sy / N; *off_gz = sz / N;
        ESP_LOGI(TAG, "校准完成! 零漂偏移: gx=%.2f gy=%.2f gz=%.2f (deg/s)",
                 *off_gx, *off_gy, *off_gz);
        return;
    }
}

void app_main(void)
{
    /* 1. I2C 主机初始化 */
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = I2C_SDA_IO,
        .scl_io_num = I2C_SCL_IO,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus = NULL;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = MPU_ADDR,
        .scl_speed_hz = I2C_FREQ_HZ,
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dev_cfg, &s_dev));

    /* 2. 传感器初始化 (未接线时每 2s 重试, 不崩溃) */
    esp_err_t err = mpu_init();
    while (err != ESP_OK) {
        ESP_LOGE(TAG, "MPU6050 未就绪 (err=0x%x)。检查接线: VCC->VCC GND->GND "
                      "SCL->掌控板SCL(GPIO22) SDA->掌控板SDA(GPIO23)，2 秒后重试...", err);
        vTaskDelay(pdMS_TO_TICKS(2000));
        err = mpu_init();
    }
    ESP_LOGI(TAG, "MPU6050 初始化 OK (I2C: SDA=%d SCL=%d @%dkHz)",
             I2C_SDA_IO, I2C_SCL_IO, I2C_FREQ_HZ / 1000);

    /* 3. 陀螺仪零漂校准 */
    float off_gx, off_gy, off_gz;
    gyro_calibrate(&off_gx, &off_gy, &off_gz);

    /* 4. 100Hz 角度输出 */
    ESP_LOGI(TAG, "开始输出角度 @%dHz: {\"a\":主角度,\"b\":副轴角度}", SAMPLE_HZ);
    float angle = 0, acc_f = 0, out_f = 0;
    bool first = true;
    TickType_t wake = xTaskGetTickCount();

    while (1) {
        imu_sample_t s;
        if (mpu_read_sample(&s) == ESP_OK) {
            float main_acc = acc_angle_axis(&s, HINGE_AXIS) * HINGE_SIGN;
            float main_gyro = gyro_axis(&s, HINGE_AXIS) * HINGE_SIGN;

            /* 扣除零漂 */
            float gz = s.gz - off_gz;   // 备用
            (void)gz;
            float g = main_gyro - ((HINGE_AXIS == AXIS_Y) ? off_gy : off_gx) * HINGE_SIGN;

            acc_f += ACC_LP_ALPHA * (main_acc - acc_f);

            if (first) {
                angle = acc_f = out_f = main_acc;
                first = false;
            } else {
                angle = CF_GYRO * (angle + g * SAMPLE_DT) + CF_ACC * acc_f;
                if (fabsf(angle - acc_f) > 45.0f) angle = acc_f;   // 发散保护
                out_f += OUT_ALPHA * (angle - out_f);
            }

            /* b = 另一轴角度, 用于判断安装方向 */
            float other = acc_angle_axis(&s, (HINGE_AXIS == AXIS_Y) ? AXIS_X : AXIS_Y);
            printf("{\"a\":%.2f,\"b\":%.2f}\n", out_f, other);
        } else {
            ESP_LOGW(TAG, "I2C 读取失败, 检查接线");
        }
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(1000 / SAMPLE_HZ));
    }
}
