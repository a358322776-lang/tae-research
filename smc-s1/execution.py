"""执行接口：限价单、成交与撤单模拟（D2/D3）。

成交模型（代理模型，须标记 proxy_fill，不得称为真实成交验证）：
- 数据源接口 BarSource：当前实现 FiveMinuteBarSource；1m 适配
  接口 OneMinuteBarSource 已保留但未实现（无 1m 数据），调用即
  明确报错，不静默降级。
- 限价单只在生效后的 bar 中严格穿透才成交：多单 Low < Limit，
  空单 High > Limit；相等不成交；生效前（effective_bar 之前）的
  bar 永不成交。
- 同 bar 歧义保守规则：成交 bar 内同时触及止损与止盈时，止损
  优先（最不利），并以 ambiguity 字段单独记录；成交与止损同
  bar 时同样先计止损（开仓即止损的一笔，单独标记）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from _deps import Bar


class BarSource(ABC):
    """成交模拟用 bar 序列接口。1m 适配时只须实现本接口。"""

    @abstractmethod
    def bars(self) -> list[Bar]:
        raise NotImplementedError


class FiveMinuteBarSource(BarSource):
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars

    def bars(self) -> list[Bar]:
        return self._bars


class OneMinuteBarSource(BarSource):
    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError(
            "1m adapter reserved: no 1m data available (see D2); "
            "use FiveMinuteBarSource proxy model instead")

    def bars(self) -> list[Bar]:
        raise NotImplementedError


@dataclass(frozen=True)
class Fill:
    bar_index: int  # 在数据源 bars 列表中的下标
    fill_px: float  # = 限价（穿透成交按限价计，不优惠）
    fill_ms: int
    proxy_fill: bool = True


@dataclass
class OrderRecord:
    direction: int
    limit_px: float
    stop_px: float
    target_px: float
    effective_bar: int
    expiry_bar: int
    status: str  # filled | expired
    fill: Fill | None = None
    ambiguity: str = ""


def simulate_limit_fill(limit_px: float, direction: int,
                        bars: list[Bar], start_idx: int,
                        end_idx: int) -> Fill | None:
    """在 bars[start_idx:end_idx+1] 中找首个严格穿透 bar。

    start_idx 必须指向生效后的第一根 bar（调用方保证）；本函数
    不回看 start_idx 之前的任何 bar。
    """
    if direction not in (1, -1):
        raise ValueError(f"bad direction: {direction}")
    for i in range(start_idx, min(end_idx, len(bars) - 1) + 1):
        bar = bars[i]
        if direction == 1 and bar.low < limit_px:
            return Fill(bar_index=i, fill_px=limit_px,
                        fill_ms=bar.open_time)
        if direction == -1 and bar.high > limit_px:
            return Fill(bar_index=i, fill_px=limit_px,
                        fill_ms=bar.open_time)
    return None


@dataclass(frozen=True)
class BarOutcome:
    outcome: str  # "open" | "stop" | "target" | "both-stop-first"
    ambiguity: str = ""


def resolve_bar(direction: int, stop_px: float, target_px: float,
                bar: Bar) -> BarOutcome:
    """单根 bar 内的持仓结果：止损与止盈同 bar 时止损优先（保守）。"""
    if direction == 1:
        hit_stop = bar.low <= stop_px
        hit_target = bar.high >= target_px
    else:
        hit_stop = bar.high >= stop_px
        hit_target = bar.low <= target_px
    if hit_stop and hit_target:
        return BarOutcome(outcome="both-stop-first",
                          ambiguity="stop-and-target-same-bar-stop-first")
    if hit_stop:
        return BarOutcome(outcome="stop")
    if hit_target:
        return BarOutcome(outcome="target")
    return BarOutcome(outcome="open")
