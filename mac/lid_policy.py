"""开合角 → 玻璃浓度。

## 为什么不能直接套用 win 端的映射

win 端是纯线性: ratio = (angle - angle_open) / (angle_closed - angle_open), 且
ESP32 的角度约定是 `+10° ≈ 合盖, -90° ≈ 屏幕垂直`。mac 传感器完全相反:
`0° = 合盖, ~130° = 全开`, 单位也是正常的物理开合角。

更重要的是: 线性映射会误触发。你把屏幕停在 80° 正常敲代码, 线性映射已经给了
你一层朦胧。所以这里移植 Mac-Duo 的**意图识别**思路 (LidEffectPolicy.swift):
效果只在"盖子刚才确实在往下合"时才启动; 静止或往上开的盖子不触发。

## 状态机

  未激活 → 激活: 需要同时满足
      - 本次运行中盖子曾经开到 threshold 以上 (排除开机就是合着的)
      - 最近 memory 秒内有过明确的合盖动作 (角速度 <= -closing_speed)
      - 当前不是在明确地开盖
      - 角度 (含速度预测) 已经跌到 threshold 以下
  激活 → 释放: 任一满足
      - 明确开盖 且 角度回到 threshold 以上 且 比本次最低点抬升 >= 1.5°
      - 盖子在 threshold 以上停留够久 (dwell)
      - 角度 >= threshold + hysteresis (常规回差, 抗抖动)

那个 1.5° 的抬升门槛是为只有 1° 精度的机型准备的: 一个整度台阶跨过一次刷新
就会被算成"快速开盖", 盖子刚好停在半度边界上时读数会在两个值间跳, 效果就会
反复闪。要求真实抬升 1.5° 可以滤掉这种抖动。

浓度 = 从 threshold 往下跌了多少 / span, 夹到 [0,1]。
"""
import time

MINIMUM_RELEASE_RISE = 1.5     # 释放所需的最小抬升量 (度), 抗 1° 精度机型抖动


class LidEffectPolicy:
    """角度 → 浓度 + 激活状态。每帧调用 update(angle)。"""

    def __init__(
        self,
        threshold=90.0,          # 开始起效的角度
        span=60.0,               # 从 threshold 往下多少度到满浓度
        hysteresis=4.0,          # 释放回差
        closing_speed=8.0,       # 度/秒, 超过算"明确在合"
        opening_speed=8.0,       # 度/秒, 超过算"明确在开"
        intent_memory=2.0,       # 合盖意图记忆时长 (秒)
        dwell_duration=0.35,     # 在 threshold 以上停留多久算开回来了
        min_duration=0.25,       # 激活后至少保持多久才允许常规回差释放
        predict_ahead=0.12,      # 用角速度往前预测多少秒 (提前起效, 跟手)
    ):
        self.threshold = threshold
        self.span = max(span, 1e-3)
        self.hysteresis = hysteresis
        self.closing_speed = closing_speed
        self.opening_speed = opening_speed
        self.intent_memory = intent_memory
        self.dwell_duration = dwell_duration
        self.min_duration = min_duration
        self.predict_ahead = predict_ahead
        self.reset()

    def reset(self):
        self.active = False
        self._last_angle = None
        self._last_t = None
        self._velocity = 0.0
        self._last_closing_t = -1e18
        self._above_since = None
        self._activated_t = None
        self._lowest = None
        self._seen_above_threshold = False

    # ---------------------------------------------------------------- 更新
    def update(self, angle, now=None):
        """喂一个角度读数, 返回 (strength 0..1, active bool)。"""
        if angle is None:
            return 0.0, self.active
        now = time.monotonic() if now is None else now

        # 角速度 (度/秒), 轻度平滑
        if self._last_angle is not None and self._last_t is not None:
            dt = now - self._last_t
            if dt > 1e-4:
                v = (angle - self._last_angle) / dt
                self._velocity += (v - self._velocity) * 0.4
        self._last_angle, self._last_t = angle, now

        if angle >= self.threshold:
            self._seen_above_threshold = True

        # 合/开意图
        if self._velocity >= self.opening_speed:
            # 开盖是一次明确的反向操作, 之前的合盖记忆必须作废,
            # 否则在阈值附近来回时旧的合盖动作会把效果又点起来
            self._last_closing_t = -1e18
        elif self._velocity <= -self.closing_speed:
            self._last_closing_t = now

        # 在 threshold 之上的停留计时
        if angle >= self.threshold:
            if self._above_since is None:
                self._above_since = now
        else:
            self._above_since = None

        # 本次激活期间的最低角
        if self.active:
            self._lowest = angle if self._lowest is None else min(self._lowest, angle)

        clearly_opening = self._velocity >= self.opening_speed
        was_closing = (now - self._last_closing_t) < self.intent_memory
        dwelled = (
            self._above_since is not None
            and (now - self._above_since) >= self.dwell_duration
        )
        predicted = angle + self._velocity * self.predict_ahead

        if self.active:
            rise = (angle - self._lowest) if self._lowest is not None else 0.0
            elapsed_ok = (
                self._activated_t is None
                or (now - self._activated_t) >= self.min_duration
            )
            release = False
            if clearly_opening and angle >= self.threshold and rise >= MINIMUM_RELEASE_RISE:
                release = True
            elif dwelled:
                release = True
            elif elapsed_ok and angle >= self.threshold + self.hysteresis:
                release = True
            if release:
                self.active = False
                self._activated_t = None
                self._lowest = None
        else:
            if (
                self._seen_above_threshold
                and was_closing
                and not clearly_opening
                and predicted <= self.threshold
            ):
                self.active = True
                self._activated_t = now
                self._lowest = angle

        return (self.strength(angle) if self.active else 0.0), self.active

    def strength(self, angle):
        """跌破 threshold 的深度 → 0..1 浓度。"""
        return max(0.0, min(1.0, (self.threshold - angle) / self.span))

    @property
    def velocity(self):
        return self._velocity
