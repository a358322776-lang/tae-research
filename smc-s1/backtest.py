"""事件驱动回测骨架（第一批）。

只定义因果推进顺序与段位守卫，不接真实数据、不出绩效数字：
- 驱动顺序：15m bar 收盘 → ATR/BOS/FVG/信号状态机；5m bar →
  订单成交与持仓结算（第二批接线）。
  任何步骤只用截至当前 bar 的已收盘数据。
- 段位守卫：segment="final_test" 一律拒绝（D4，冻结前禁止
  访问最终测试集绩效）；train/validation 亦须第二批另批后
  才可运行——本批骨架只接受合成数据驱动的单元测试。
- 本批 run_synthetic 为单时间框架驱动（15m Pivot 同时用于趋势、
  BOS 与止损锚），仅验证信号因果顺序；止损锚由 15m Pivot
  解析器直接计算（anchor.resolve_stop_anchor），不得外部传入。
  多时间框架（1H 趋势 + 15m 信号 + 5m 成交）的时间戳对齐属
  第二批工作，不在本批冒充；时间戳校验（严格递增、等步长）
  已由 alignment 模块在入口强制。

BacktestEngine 不读文件、不读缓存。
"""

from __future__ import annotations

from dataclasses import dataclass

from _deps import Bar
from alignment import check_series_gaps, validate_strictly_increasing
from bos import detect_bos
from config import SMCConfig
from execution import OrderRecord
from fvg import find_fvgs
from signals import SignalEngine
from structure import atr_wilder, find_pivots, trend_state


@dataclass
class TradeRecord:
    direction: int
    entry_px: float
    exit_px: float
    stop_px: float
    target_px: float
    outcome: str  # "stop" | "target" | "both-stop-first"
    ambiguity: str = ""
    fill_bar: int = -1
    exit_bar: int = -1
    proxy_fill: bool = True


class SegmentBlocked(Exception):
    """最终测试段在冻结前禁止运行。"""


class BacktestEngine:
    def __init__(self, config: SMCConfig | None = None) -> None:
        self.cfg = config or SMCConfig()
        self.engine = SignalEngine(self.cfg)

    def run_synthetic(self, bars_15m: list[Bar], segment: str) -> dict:
        """合成数据驱动：仅供单元测试验证因果顺序。

        止损锚由同一批 15m bar 求得的 Pivot 经解析器计算；
        时间戳须严格递增且等步长（步长由前两根 bar 推断），
        否则报错，拒绝以错位数据运行。
        """
        if segment == "final_test":
            raise SegmentBlocked(
                "final test segment is blocked until freeze (D4)")
        if segment not in ("train", "validation", "synthetic"):
            raise ValueError(f"unknown segment: {segment}")
        validate_strictly_increasing(bars_15m)
        if len(bars_15m) >= 2:
            step_ms = bars_15m[1].open_time - bars_15m[0].open_time
            gaps = check_series_gaps(
                [b.open_time for b in bars_15m], step_ms)
            if gaps:
                raise ValueError(f"bar timestamps have gaps: {gaps[:3]}")
        atr = atr_wilder(bars_15m, self.cfg.atr_period)
        pivots = find_pivots(bars_15m, self.cfg.pivot_left,
                             self.cfg.pivot_right)
        orders: list[OrderRecord] = []
        for i, bar in enumerate(bars_15m):
            known = [p for p in pivots if p.confirmed_at <= i]
            trend = trend_state(known)
            bos = detect_bos(bars_15m, pivots, atr, i,
                             self.cfg.bos_min_atr)
            direction = bos.direction if bos is not None else (
                self.engine._bos.direction
                if self.engine.state == "BOS_SEEN" else 0)
            fvgs = find_fvgs(bars_15m, direction, atr, i, i,
                             self.cfg.fvg_min_atr) if direction != 0 else []
            order = self.engine.on_15m_close(
                i, trend, bos, fvgs, pivots, atr[i])
            if order is not None:
                orders.append(OrderRecord(
                    direction=order.direction, limit_px=order.limit_px,
                    stop_px=order.stop_px, target_px=order.target_px,
                    effective_bar=order.effective_bar,
                    expiry_bar=order.expiry_bar, status="pending"))
        return {"orders": orders, "trades": [],
                "events": self.engine.events,
                "note": "skeleton: fill/position settlement is wired in "
                        "batch 2; batch 1 validates signal causality only"}
