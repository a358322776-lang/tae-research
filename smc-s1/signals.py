"""交易信号状态机。

状态：IDLE → BOS_SEEN → ORDER_PLACED → POSITION → IDLE。
单仓约束：同一时刻最多一个有效订单或持仓（D 批复 + 任务书规则 8）。

时序铁律（调用方须按已收盘 bar 顺序驱动）：
- BOS 在 15m 收盘 bar 上确认；FVG 须在 BOS 确认时或其后 3 根
  15m bar 内出现（含 BOS bar 本身），且方向一致；
- 订单在 FVG 成立 bar 的下一根 bar 起生效（effective_bar），
  最多等待 8 根 15m bar，过期未成交即记录为 expired；
- 止损锚取信号生成时已确认的反向结构点（解释 I1，见规则文档）。

本模块不读 K 线、不算指标——趋势/BOS/FVG 由调用方用
structure/bos/fvg 在已收盘数据上算好后传入，保证无前视。
"""

from __future__ import annotations

from dataclasses import dataclass

from bos import BOS
from fvg import FVG
from risk import compute_stop_target


@dataclass
class Order:
    direction: int
    limit_px: float
    stop_px: float
    target_px: float
    stop_distance_atr: float
    created_bar: int  # FVG 成立 bar
    effective_bar: int  # = created_bar + 1
    expiry_bar: int  # = created_bar + max_wait（15m bar 下标，含）
    status: str = "pending"  # pending | filled | expired | cancelled
    skip_reason: str = ""


@dataclass
class SignalEvent:
    bar_index: int
    kind: str  # bos | fvg | order | order_expired | skip | filled | closed
    detail: str = ""


class SignalEngine:
    def __init__(self, config) -> None:
        self.cfg = config
        self.state = "IDLE"
        self.order: Order | None = None
        self.position_direction: int | None = None
        self.events: list[SignalEvent] = []
        self._bos: BOS | None = None
        self._bos_deadline: int | None = None
        self._bos_bar: int | None = None

    def _log(self, bar_index: int, kind: str, detail: str = "") -> None:
        self.events.append(SignalEvent(bar_index, kind, detail))

    def _try_create_order(self, bar_index: int, direction: int,
                          fvgs: list[FVG], opposite_swing_px: float | None,
                          atr: float | None) -> Order | None:
        hits = [f for f in fvgs if f.direction == direction]
        if not hits:
            return None
        fvg = hits[0]
        if atr is None or opposite_swing_px is None:
            self._log(bar_index, "skip", "missing-atr-or-structure")
            self._bos = None
            self.state = "IDLE"
            return None
        entry = fvg.mid
        stop_target, reason = compute_stop_target(
            direction, entry, opposite_swing_px, atr,
            self.cfg.stop_min_atr, self.cfg.stop_max_atr, self.cfg.target_r)
        if stop_target is None:
            self._log(bar_index, "skip", reason)
            self._bos = None
            self.state = "IDLE"
            return None
        order = Order(
            direction=direction, limit_px=entry,
            stop_px=stop_target.stop_px, target_px=stop_target.target_px,
            stop_distance_atr=stop_target.stop_distance_atr,
            created_bar=fvg.bar_index,
            effective_bar=fvg.bar_index + 1,
            expiry_bar=fvg.bar_index + self.cfg.order_max_wait_bars)
        self.order = order
        self.state = "ORDER_PLACED"
        self._bos = None
        self._log(bar_index, "order",
                  f"dir={direction} limit={entry} stop={order.stop_px}")
        return order

    def on_15m_close(self, bar_index: int, trend: str,
                     bos_event: BOS | None, fvgs: list[FVG],
                     opposite_swing_px: float | None,
                     atr: float | None) -> Order | None:
        """处理一根已收盘 15m bar。返回新下的订单（若有），否则 None。

        opposite_swing_px：信号生成时已确认的反向结构点价格；
        atr：该 bar 收盘后的 ATR 值。
        """
        cfg = self.cfg
        if self.state == "POSITION":
            return None
        if self.state == "ORDER_PLACED":
            if self.order is not None and bar_index > self.order.expiry_bar:
                self.order.status = "expired"
                self._log(bar_index, "order_expired",
                          f"order expired unfilled, created={self.order.created_bar}")
                self.order = None
                self.state = "IDLE"
            else:
                return None
        if self.state == "BOS_SEEN":
            if bar_index > self._bos_deadline:
                self._bos = None
                self.state = "IDLE"
                self._log(bar_index, "skip", "bos-fvg-window-expired")
            else:
                return self._try_create_order(
                    bar_index, self._bos.direction, fvgs,
                    opposite_swing_px, atr)
        if self.state == "IDLE":
            if bos_event is not None and trend in ("long", "short"):
                want = 1 if trend == "long" else -1
                if bos_event.direction == want:
                    self._bos = bos_event
                    self._bos_bar = bar_index
                    self._bos_deadline = bar_index + cfg.bos_fvg_max_bars
                    self.state = "BOS_SEEN"
                    self._log(bar_index, "bos",
                              f"dir={bos_event.direction} struct={bos_event.structure_px}")
                    # BOS 确认时同 bar 的 FVG 也算（任务书“确认时或其后”）。
                    return self._try_create_order(
                        bar_index, want, fvgs, opposite_swing_px, atr)
            return None
        return None

    def on_fill(self, bar_index: int) -> None:
        if self.order is None or self.state != "ORDER_PLACED":
            raise ValueError("no placed order to fill")
        self.position_direction = self.order.direction
        self.order.status = "filled"
        self._log(bar_index, "filled",
                  f"dir={self.order.direction} limit={self.order.limit_px}")
        self.order = None
        self.state = "POSITION"

    def on_position_close(self, bar_index: int, outcome: str) -> None:
        if self.state != "POSITION":
            raise ValueError("no open position")
        self.position_direction = None
        self.state = "IDLE"
        self._log(bar_index, "closed", outcome)
