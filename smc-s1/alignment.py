"""多时间框架对齐：统一事件时间定义与时序校验（B2-FIX）。

事件时间定义（全模块唯一口径）：
- 一根 Bar 覆盖半开区间 [open_time, open_time + step_ms)；
  收盘时刻 = open_time + step_ms（即下一根 bar 的 open_time）。
- 决策在某根 bar 的收盘时刻进行，只能使用收盘时刻
  <= 该时刻的 bar；高周期 bar 若恰在同一时刻收盘则可用
  （决策发生在收盘之后），晚 1ms 也不行。
- Pivot 可用条件：确认 bar（下标 confirmed_at）已收盘，即
  确认 bar 的收盘时刻 <= 决策时刻。

本模块只做时间口径与校验，不产生信号、不读数据。
"""

from __future__ import annotations

from _deps import Bar
from structure import Pivot


def bar_close_ms(open_time_ms: int, step_ms: int) -> int:
    """bar 的收盘时刻 = open_time + step_ms。"""
    return open_time_ms + step_ms


def higher_tf_usable_bars(tf_bars: list[Bar], step_ms: int,
                          decision_close_ms: int) -> list[Bar]:
    """截至决策时刻已收盘的高周期 bar（收盘时刻 <= 决策时刻）。"""
    if step_ms <= 0:
        raise ValueError("step_ms must be positive")
    return [b for b in tf_bars
            if bar_close_ms(b.open_time, step_ms) <= decision_close_ms]


def pivot_usable_at(pivot: Pivot, tf_step_ms: int, base_ms: int,
                    decision_close_ms: int) -> bool:
    """Pivot 在决策时刻是否可用：其确认 bar 已收盘。

    base_ms 为该时间框架序列首根 bar 的 open_time；确认 bar 的
    收盘时刻 = base_ms + (confirmed_at + 1) * tf_step_ms。
    """
    if tf_step_ms <= 0:
        raise ValueError("tf_step_ms must be positive")
    confirm_close = base_ms + (pivot.confirmed_at + 1) * tf_step_ms
    return confirm_close <= decision_close_ms


def check_series_gaps(timestamps_ms: list[int],
                      step_ms: int) -> list[dict]:
    """检查等步长时间序列：返回全部异常位置（缺失/错位/倒退）。

    每项：{index, expected_ms, actual_ms, delta_ms}，index 为
    异常 bar 在序列中的下标；空列表 = 序列干净。
    """
    if step_ms <= 0:
        raise ValueError("step_ms must be positive")
    gaps: list[dict] = []
    for i in range(1, len(timestamps_ms)):
        expected = timestamps_ms[i - 1] + step_ms
        actual = timestamps_ms[i]
        if actual != expected:
            gaps.append({"index": i, "expected_ms": expected,
                         "actual_ms": actual,
                         "delta_ms": actual - expected})
    return gaps


def validate_strictly_increasing(bars: list[Bar]) -> None:
    """bar 序列须严格按 open_time 递增；否则报错。"""
    if not bars:
        raise ValueError("empty bar series")
    for prev, cur in zip(bars, bars[1:]):
        if cur.open_time <= prev.open_time:
            raise ValueError(
                "bars must be strictly increasing in open_time: "
                f"{prev.open_time} -> {cur.open_time}")
