"""结构突破（BOS）识别。

规则：15m 收盘价突破最近已确认结构点至少 0.1 ATR（D1 批复值，
配置见 config）。结构点必须是确认的（confirmed_at <= 决策 bar），
ATR 必须是决策 bar 收盘后计算的值——调用方传入截至决策 bar 的
atr 列表，本模块不向前取任何未来 bar。
结构点所属周期由调用方传入的 pivots 决定：实盘接线（live_engine）
按 SPEC v1.1（解释 I2 已确认）传入 1H 已确认 Pivot；本模块本身
与周期无关，只判定传入的已确认点。
"""

from __future__ import annotations

from dataclasses import dataclass

from _deps import Bar
from structure import Pivot


@dataclass(frozen=True)
class BOS:
    bar_index: int
    direction: int  # 1 多 / -1 空
    structure_px: float
    structure_index: int
    atr: float
    close_px: float


def detect_bos(bars: list[Bar], pivots: list[Pivot],
               atr_values: list[float | None], bar_index: int,
               bos_min_atr: float) -> BOS | None:
    """检测单根 15m 收盘 bar 的 BOS；无突破返回 None。"""
    atr = atr_values[bar_index]
    if atr is None:
        return None
    close = bars[bar_index].close
    highs = [p for p in pivots if p.kind == "high"
             and p.confirmed_at <= bar_index]
    lows = [p for p in pivots if p.kind == "low"
            and p.confirmed_at <= bar_index]
    if highs:
        top = highs[-1]
        if close > top.price + bos_min_atr * atr:
            return BOS(bar_index=bar_index, direction=1,
                       structure_px=top.price, structure_index=top.index,
                       atr=atr, close_px=close)
    if lows:
        bottom = lows[-1]
        if close < bottom.price - bos_min_atr * atr:
            return BOS(bar_index=bar_index, direction=-1,
                       structure_px=bottom.price,
                       structure_index=bottom.index,
                       atr=atr, close_px=close)
    return None
