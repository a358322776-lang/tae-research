"""FVG（Fair Value Gap）检测。

三根 bar 形态：多头 FVG = bar[i].low > bar[i-2].high，缺口
[high[i-2], low[i]]；空头镜像。缺口至少 0.2 ATR。FVG 在第
三根 bar 收盘时才成立，入场挂单自下一根 bar 起生效——本模块
只返回 FVG 事实，生效时序由 signals.py 强制。
"""

from __future__ import annotations

from dataclasses import dataclass

from _deps import Bar


@dataclass(frozen=True)
class FVG:
    bar_index: int  # 第三根 bar（成立时）
    direction: int
    top: float
    bottom: float
    mid: float
    gap: float
    gap_atr: float


def find_fvgs(bars: list[Bar], direction: int,
              atr_values: list[float | None], start_idx: int,
              end_idx: int, min_gap_atr: float) -> list[FVG]:
    """在 [start_idx, end_idx] 内按方向找 FVG（闭区间下标）。"""
    out: list[FVG] = []
    for i in range(max(2, start_idx), min(end_idx, len(bars) - 1) + 1):
        atr = atr_values[i]
        if atr is None:
            continue
        if direction == 1:
            gap = bars[i].low - bars[i - 2].high
            if gap >= min_gap_atr * atr:
                top, bottom = bars[i].low, bars[i - 2].high
                out.append(FVG(bar_index=i, direction=1, top=top,
                               bottom=bottom, mid=(top + bottom) / 2,
                               gap=gap, gap_atr=gap / atr))
        elif direction == -1:
            gap = bars[i - 2].low - bars[i].high
            if gap >= min_gap_atr * atr:
                top, bottom = bars[i - 2].low, bars[i].high
                out.append(FVG(bar_index=i, direction=-1, top=top,
                               bottom=bottom, mid=(top + bottom) / 2,
                               gap=gap, gap_atr=gap / atr))
        else:
            raise ValueError(f"bad direction: {direction}")
    return out
