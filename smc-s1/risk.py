"""仓位、止损、止盈：纯计算，不持仓、不下单。

止损锚（规则解释 I1，见规则文档）：信号生成时已确认的最近反向
结构点——多头取最近摆动低点，空头取最近摆动高点。止损距离
须落在 [0.5, 3] ATR 内，否则跳过该信号（返回 None + 原因）。
目标固定 2R，R = |入场价 − 止损价|（入场价 = FVG 50% 限价）。
仓位数量只由调用方给定的 risk_amount 决定；本模块不设默认
风险比例（任务书未定，不得发明）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StopTarget:
    stop_px: float
    target_px: float
    stop_distance_px: float
    stop_distance_atr: float
    risk_per_unit: float


def compute_stop_target(direction: int, entry_px: float,
                        structure_px: float, atr: float,
                        stop_min_atr: float, stop_max_atr: float,
                        target_r: float) -> tuple[StopTarget | None, str]:
    """返回 (StopTarget, '') 或 (None, 跳过原因)。"""
    if atr is None or atr <= 0:
        return None, "atr-unavailable"
    dist = abs(entry_px - structure_px)
    dist_atr = dist / atr
    if dist_atr < stop_min_atr:
        return None, "stop-too-close"
    if dist_atr > stop_max_atr:
        return None, "stop-too-far"
    stop_px = structure_px
    target_px = entry_px + direction * target_r * dist
    return StopTarget(stop_px=stop_px, target_px=target_px,
                      stop_distance_px=dist, stop_distance_atr=dist_atr,
                      risk_per_unit=dist), ""


def position_qty(risk_amount: float, entry_px: float,
                 stop_px: float) -> float:
    """风险金额 / 单位风险 = 数量（ETH）。risk_amount 由调用方给定。"""
    dist = abs(entry_px - stop_px)
    if dist <= 0:
        raise ValueError("entry equals stop")
    if risk_amount <= 0:
        raise ValueError("risk_amount must be positive")
    return risk_amount / dist


def r_multiple(pnl_pct: float, stop_distance_pct: float) -> float:
    if stop_distance_pct <= 0:
        raise ValueError("stop_distance_pct must be positive")
    return pnl_pct / stop_distance_pct
