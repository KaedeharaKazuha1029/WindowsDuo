"""LidEffectPolicy 单元测试 (纯逻辑, 不需要 GL / 传感器)。

用法: python -m pytest mac/test_lid_policy.py -q
      或   python mac/test_lid_policy.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lid_policy import MINIMUM_RELEASE_RISE, LidEffectPolicy


def feed(policy, samples, dt=0.05, t0=None):
    """按固定步长喂一串角度, 返回每步的 (strength, active)。"""
    out = []
    if t0 is None:
        t = 1000.0 if policy._last_t is None else policy._last_t + dt
    else:
        t = t0
    for a in samples:
        out.append(policy.update(a, now=t))
        t += dt
    return out


def ramp(start, end, steps):
    if steps <= 1:
        return [end]
    step = (end - start) / (steps - 1)
    return [start + step * i for i in range(steps)]


def new_policy(**kw):
    kw.setdefault("threshold", 90.0)
    kw.setdefault("span", 60.0)
    return LidEffectPolicy(**kw)


# ------------------------------------------------------- 基本映射
def test_strength_maps_linearly_below_threshold():
    p = new_policy()
    assert p.strength(90.0) == 0.0
    assert abs(p.strength(60.0) - 0.5) < 1e-9      # 跌 30° / span 60
    assert p.strength(30.0) == 1.0                  # 跌 60° 到满
    assert p.strength(0.0) == 1.0                   # 夹住, 不超过 1


def test_strength_clamped_above_threshold():
    p = new_policy()
    assert p.strength(120.0) == 0.0


# ------------------------------------------------------- 意图识别
def test_resting_below_threshold_does_not_activate():
    """静止停在 80° 正常使用 —— 绝不能起效 (线性映射会误触发, 这是移植意图识别的原因)。"""
    p = new_policy()
    out = feed(p, [80.0] * 40)
    assert not any(active for _, active in out)
    assert all(s == 0.0 for s, _ in out)


def test_closing_from_open_activates():
    """从 120° 快速合到 70°, 应当起效。"""
    p = new_policy()
    out = feed(p, ramp(120.0, 70.0, 20))
    assert out[-1][1] is True
    assert out[-1][0] > 0.0


def test_never_opened_above_threshold_does_not_activate():
    """开机就是半合状态 (从未到过 threshold 以上), 合下去也不该起效。"""
    p = new_policy()
    out = feed(p, ramp(85.0, 40.0, 20))
    assert not any(active for _, active in out)


def test_slow_close_below_closing_speed_does_not_activate():
    """慢到低于 closing_speed 的移动不算合盖意图。"""
    p = new_policy(closing_speed=8.0)
    # 100 -> 80, 每步 0.05s 走 0.2° => 4°/s, 低于 8°/s
    out = feed(p, ramp(100.0, 80.0, 101))
    assert not any(active for _, active in out)


def test_closing_intent_expires():
    """合一下停住等久于 intent_memory, 旧意图过期; 之后的慢速下移不该起效。

    注意快速合到 95° 时 policy 会因 predict_ahead 提前激活 (预测角已跌破
    threshold), 但此时 strength 仍为 0, 画面无变化 —— 提前激活是有意的, 给截图
    预热留时间。停住之后 dwell 会把它释放掉。这个测试关心的是**过期的合盖意图
    不能在后来把效果点起来**。
    """
    p = new_policy(intent_memory=0.5, dwell_duration=0.2)
    out1 = feed(p, ramp(120.0, 95.0, 10))   # 明确在合, 但仍在 threshold 之上
    assert all(s == 0.0 for s, _ in out1), "threshold 之上浓度必须为 0"

    # 停在 95° 等 1s: 超过 dwell 会释放, 也超过 0.5s 的意图记忆
    out = feed(p, [95.0] * 20)
    assert out[0][1] is True, "dwell 计时应从激活时刻开始"
    assert out[-1][1] is False, "在 threshold 之上停住应当释放"

    # 现在慢慢降到 threshold 以下 (慢于 closing_speed, 且旧意图已过期) -> 不该起效
    out2 = feed(p, ramp(95.0, 88.0, 60))
    assert not any(active for _, active in out2)
    assert all(s == 0.0 for s, _ in out2)


# ------------------------------------------------------- 释放
def test_opening_back_above_threshold_releases():
    p = new_policy()
    feed(p, ramp(120.0, 60.0, 20))
    assert p.active
    out = feed(p, ramp(60.0, 120.0, 20))
    assert out[-1][1] is False
    assert out[-1][0] == 0.0


def test_dwell_above_threshold_releases_even_when_slow():
    """缓慢开回 threshold 之上并停住, 靠 dwell 释放。"""
    p = new_policy(dwell_duration=0.2, opening_speed=1000.0)
    feed(p, ramp(120.0, 60.0, 20))
    assert p.active
    out = feed(p, [91.0] * 20)              # 停在阈值之上且未越过 hysteresis
    assert out[0][1] is True
    assert out[-1][1] is False


def test_hysteresis_prevents_flapping_at_threshold():
    """激活后在 threshold 上方一点点抖动, 不应立刻释放 (需超过 hysteresis)。"""
    p = new_policy(
        hysteresis=4.0,
        dwell_duration=10.0,
        min_duration=0.0,
        opening_speed=10000.0,
    )
    feed(p, ramp(120.0, 60.0, 20))
    assert p.active
    # 抬到 91°, 低于 90+4, dwell 也远未到 -> 保持激活
    out = feed(p, [91.0] * 3, dt=0.01)
    assert out[-1][1] is True


def test_tiny_jitter_does_not_release_on_whole_degree_sensor():
    """1° 精度机型: 一个整度台阶不足 MINIMUM_RELEASE_RISE, 不应靠"快速开盖"释放。"""
    p = new_policy(dwell_duration=10.0, min_duration=10.0)
    feed(p, ramp(120.0, 89.0, 20))
    assert p.active
    lowest = 89.0
    # 抬一个整度台阶到 90°, rise = 1.0 < 1.5, 且 dwell/min_duration 都没到
    out = feed(p, [lowest + 1.0], dt=0.01)
    assert out[-1][1] is True, "1° 抖动不应释放效果"


def test_release_rise_threshold_value():
    assert MINIMUM_RELEASE_RISE == 1.5


# ------------------------------------------------------- 其它
def test_none_angle_is_ignored():
    p = new_policy()
    s, a = p.update(None)
    assert s == 0.0 and a is False


def test_reset_clears_state():
    p = new_policy()
    feed(p, ramp(120.0, 60.0, 20))
    assert p.active
    p.reset()
    assert not p.active
    # reset 后从未见过 threshold 以上, 合下去不该起效
    out = feed(p, ramp(85.0, 50.0, 20))
    assert not any(active for _, active in out)


def test_full_close_reaches_full_strength():
    p = new_policy()
    out = feed(p, ramp(120.0, 20.0, 40))
    assert out[-1][1] is True
    assert out[-1][0] == 1.0


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
