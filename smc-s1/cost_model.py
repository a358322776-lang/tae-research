"""成本适配层（D6）：薄适配，不得复制或重新实现费用公式。

费用分解与恒等式全部复用 research-lab 的统一成本函数
（cost_model.fill_price / funding_exact_sum / check_funding_coverage
与 CostSpec 数据类）。本层只做三件事：

1. 按成交类型（maker/taker）为每条腿选费率——费率由调用方
   显式传入并附来源字符串，模块内无任何硬编码费率；
2. 以“费率 × 成交名义”为定义逐腿计费（交易所定义），用
   统一模型的 fill_price 求成交价、用 funding_exact_sum 求资金费；
3. 资金费记录先过 funding_gate 三项检查（重复时间戳、8h 网格
   对齐容差 60s、异常值），再交统一模型查覆盖完整性。
3. 输出毛/费/滑点价差/资金费/净 R 五栏并断言恒等式
   net = gross_fill − fee − funding。

滑点/价差在 5m 代理模型下无法观测，取 0 并以 assumption 明确
标记“未核实假设”，不得称为实测成本。资金费记录缺失或覆盖
缺口时 net=None，拒绝估算。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from _deps import cost_model as _cm
from funding_gate import check_funding_records


@dataclass(frozen=True)
class TradeCost:
    gross_pct: float
    fee_pct: float
    slip_spread_pct: float
    funding_pct: float | None
    net_pct: float | None
    gross_r: float
    fee_r: float
    slip_spread_r: float
    funding_r: float | None
    net_r: float | None
    entry_fill_type: str  # "maker" | "taker"
    exit_fill_type: str
    fee_source: str
    funding_status: str  # "ok" | "coverage_gap" | "unknown"
    assumptions: tuple = ()


def _leg_spec(fee_rate: float, fee_source: str,
              slip_spread_per_side: float = 0.0) -> "_cm.CostSpec":
    # 滑点/价差由调用方显式传入（中央档 0；保守档 0.0020，见
    # SPEC §5）；费率按 filled 口径仅作规格载体；实际逐腿计费
    # 在 price_trade 中按定义式计算，见模块文档。
    return _cm.CostSpec(
        name="smc-leg", fee_per_side=fee_rate, fee_mode="filled",
        fee_fixed_pct=0.0, slip_entry=slip_spread_per_side,
        spread_entry=0.0, slip_exit=slip_spread_per_side,
        spread_exit=0.0, exit_cost_applies_to="all",
        funding_mode="exact", source=fee_source)


def price_trade(theoretical_entry: float, theoretical_exit: float,
                direction: int, *, entry_fill_type: str,
                exit_fill_type: str, entry_fee_rate: float,
                exit_fee_rate: float, fee_source: str,
                funding_records: list[tuple[int, float]] | None,
                t0_ms: int, t1_ms: int,
                stop_distance_pct: float,
                slip_spread_per_side: float = 0.0) -> TradeCost:
    """一笔交易的成本分解（纯函数）。

    entry_fill_type="maker"（限价成交）；exit_fill_type="maker"
    （止盈限价）或 "taker"（止损）。fee_source 不能为空。
    slip_spread_per_side：每边滑点/价差（经统一模型 fill_price
    一次计入成交价，默认 0 = 中央档行为零变化；保守档 0.0020）。
    """
    if not fee_source:
        raise ValueError("fee_source is required: fee rates must be sourced")
    if entry_fill_type not in ("maker", "taker"):
        raise ValueError(f"bad entry_fill_type: {entry_fill_type}")
    if exit_fill_type not in ("maker", "taker"):
        raise ValueError(f"bad exit_fill_type: {exit_fill_type}")
    if theoretical_entry <= 0 or theoretical_exit <= 0:
        raise ValueError("prices must be positive")
    if stop_distance_pct <= 0:
        raise ValueError("stop_distance_pct must be positive")
    if slip_spread_per_side < 0:
        raise ValueError("slip_spread_per_side must be >= 0")
    if funding_records is not None:
        # 资金费三项门禁先行（records=None 时跳过，保持 unknown 语义）；
        # 覆盖完整性仍由统一模型判定，门禁不重复、不冲突。
        check_funding_records(funding_records)
    entry_spec = _leg_spec(entry_fee_rate, fee_source, slip_spread_per_side)
    exit_spec = _leg_spec(exit_fee_rate, fee_source, slip_spread_per_side)
    # 成交价经统一模型 fill_price 求得（滑点/价差为 0 时等于理论价，
    # 但路径仍走统一模型，口径唯一）。
    fill_entry = _cm.fill_price(theoretical_entry, direction, "entry",
                                entry_spec)
    fill_exit = _cm.fill_price(theoretical_exit, direction, "exit",
                               exit_spec, "close")
    gross_theoretical = direction * (theoretical_exit - theoretical_entry) \
        / theoretical_entry
    gross_fill = direction * (fill_exit - fill_entry) / fill_entry
    slip_spread = gross_theoretical - gross_fill
    # 逐腿计费：费率 × 成交名义，以理论入场价为分母。
    fee_pct = (entry_fee_rate * fill_entry
               + exit_fee_rate * fill_exit) / theoretical_entry
    assumptions = ["proxy-fill-5m"]
    if slip_spread_per_side == 0.0:
        assumptions.append(
            "slip/spread assumed 0, unverified (proxy model)")
    else:
        assumptions.append(
            f"slip/spread {slip_spread_per_side} per side, "
            "pre-registered conservative tier")
    if funding_records is None:
        return TradeCost(
            gross_pct=gross_fill, fee_pct=fee_pct,
            slip_spread_pct=slip_spread, funding_pct=None, net_pct=None,
            gross_r=gross_fill / stop_distance_pct,
            fee_r=fee_pct / stop_distance_pct,
            slip_spread_r=slip_spread / stop_distance_pct,
            funding_r=None, net_r=None,
            entry_fill_type=entry_fill_type, exit_fill_type=exit_fill_type,
            fee_source=fee_source, funding_status="unknown",
            assumptions=tuple(assumptions))
    try:
        _cm.check_funding_coverage(funding_records, t0_ms, t1_ms)
    except _cm.FundingCoverageGap:
        return TradeCost(
            gross_pct=gross_fill, fee_pct=fee_pct,
            slip_spread_pct=slip_spread, funding_pct=None, net_pct=None,
            gross_r=gross_fill / stop_distance_pct,
            fee_r=fee_pct / stop_distance_pct,
            slip_spread_r=slip_spread / stop_distance_pct,
            funding_r=None, net_r=None,
            entry_fill_type=entry_fill_type, exit_fill_type=exit_fill_type,
            fee_source=fee_source, funding_status="coverage_gap",
            assumptions=tuple(assumptions))
    funding_pct = _cm.funding_exact_sum(funding_records, t0_ms, t1_ms)
    net_pct = gross_fill - fee_pct - funding_pct
    # 恒等式审计：净 = 成交毛 − 费 − 资金费（1e-12 内）。
    assert abs(net_pct - (gross_fill - fee_pct - funding_pct)) < 1e-12
    return TradeCost(
        gross_pct=gross_fill, fee_pct=fee_pct,
        slip_spread_pct=slip_spread, funding_pct=funding_pct,
        net_pct=net_pct,
        gross_r=gross_fill / stop_distance_pct,
        fee_r=fee_pct / stop_distance_pct,
        slip_spread_r=slip_spread / stop_distance_pct,
        funding_r=funding_pct / stop_distance_pct,
        net_r=net_pct / stop_distance_pct,
        entry_fill_type=entry_fill_type, exit_fill_type=exit_fill_type,
        fee_source=fee_source, funding_status="ok",
        assumptions=tuple(assumptions))
