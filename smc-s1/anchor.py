"""止损锚点解析器（B2-FIX）。

规则解释 I1 的唯一落地：信号生成时已确认的最近反向 15m 结构点
（多头取最近摆动低点，空头取最近摆动高点）。解析器是止损锚的
唯一来源——信号引擎直接调用它，任何外部传入的止损价格都不会
被接受（on_15m_close 不再接受止损值参数）。

时序：只取 confirmed_at <= as_of_bar_index 的 Pivot；未确认的
Pivot（确认 bar 尚未收盘）一律不可用，不得提前引用。
"""

from __future__ import annotations

from structure import Pivot, last_confirmed_swing


def resolve_stop_anchor(pivots: list[Pivot], direction: int,
                        as_of_bar_index: int) -> float | None:
    """返回止损锚价格；无符合的已确认反向结构点时返回 None。

    direction: 1 多头（取 kind="low"），-1 空头（取 kind="high"）。
    调用方不得用返回值以外的任何价格作止损锚。
    """
    if direction not in (1, -1):
        raise ValueError(f"bad direction: {direction}")
    kind = "low" if direction == 1 else "high"
    swing = last_confirmed_swing(pivots, kind, as_of_bar_index)
    return swing.price if swing is not None else None
