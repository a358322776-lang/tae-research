"""结构识别：Pivot、HH/HL/LH/LL、Wilder ATR。

只消费 validator.Bar（显式字段），永不按位置解包 OHLC 行——
D-ENG-1 的教训。所有函数只读“已收盘” bar 列表；Pivot 只有在
右侧确认 bar 全部收盘后才可用（confirmed_at = index + right），
此前任何决策不得引用它。
"""

from __future__ import annotations

from dataclasses import dataclass

from _deps import Bar


@dataclass(frozen=True)
class Pivot:
    index: int
    kind: str  # "high" | "low"
    price: float
    confirmed_at: int  # 首次可用的 bar 下标


def true_range(bar: Bar, prev_close: float | None) -> float:
    if prev_close is None:
        return bar.high - bar.low
    return max(bar.high - bar.low,
               abs(bar.high - prev_close),
               abs(bar.low - prev_close))


def atr_wilder(bars: list[Bar], period: int) -> list[float | None]:
    """Wilder RMA ATR，与 bar 下标对齐。

    atr[i] 由截至 bar i（含）的 TR 计算，首个有效值在下标
    period-1 处（前 period 根 TR 的均值），之前为 None。
    调用方只能用已收盘 bar 的 atr[i] 作下一根 bar 的决策依据。
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    trs: list[float] = []
    prev_close: float | None = None
    for bar in bars:
        trs.append(true_range(bar, prev_close))
        prev_close = bar.close
    out: list[float | None] = [None] * len(bars)
    if len(trs) < period:
        return out
    seed = sum(trs[:period]) / period
    out[period - 1] = seed
    for i in range(period, len(trs)):
        out[i] = (out[i - 1] * (period - 1) + trs[i]) / period
    return out


def find_pivots(bars: list[Bar], left: int, right: int,
                as_of: int | None = None) -> list[Pivot]:
    """左右各 left/right 根确认的 Pivot。

    高点：high 严格大于左右各 left/right 根的 high；低点反之。
    相等不算 Pivot（避免重复摆动点）。as_of 限制“截至某根收盘
    已知”的 Pivot：confirmed_at <= as_of。
    """
    if as_of is None:
        as_of = len(bars) - 1
    pivots: list[Pivot] = []
    for i in range(left, len(bars) - right):
        if i + right > as_of:
            break
        bar = bars[i]
        if all(bar.high > bars[j].high
               for j in range(i - left, i + right + 1) if j != i):
            pivots.append(Pivot(index=i, kind="high", price=bar.high,
                                confirmed_at=i + right))
        elif all(bar.low < bars[j].low
                 for j in range(i - left, i + right + 1) if j != i):
            pivots.append(Pivot(index=i, kind="low", price=bar.low,
                                confirmed_at=i + right))
    return pivots


def _last_two(pivots: list[Pivot], kind: str) -> list[Pivot]:
    return [p for p in pivots if p.kind == kind][-2:]


def trend_state(pivots: list[Pivot]) -> str:
    """结构趋势：连续 HH/HL 只做多，LH/LL 只做空，其余 none。

    取最近两个已确认摆动高点与低点分别比较；任一序列不足
    两点即 none，不猜方向。
    """
    highs = _last_two(pivots, "high")
    lows = _last_two(pivots, "low")
    if len(highs) < 2 or len(lows) < 2:
        return "none"
    if highs[-1].price > highs[-2].price and lows[-1].price > lows[-2].price:
        return "long"
    if highs[-1].price < highs[-2].price and lows[-1].price < lows[-2].price:
        return "short"
    return "none"


def last_confirmed_swing(pivots: list[Pivot], kind: str,
                         as_of: int) -> Pivot | None:
    """截至 as_of 已确认的最近反向结构点（止损锚）。"""
    cands = [p for p in pivots if p.kind == kind and p.confirmed_at <= as_of]
    return cands[-1] if cands else None
