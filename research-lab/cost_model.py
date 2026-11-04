"""统一成本函数（A1，G3）。

仅 Python 标准库。引擎不动、历史不动：本模块只提供成本计算，
不导入、不调用任何回测引擎；已知答案测试只用合成数据（字面量），
不重跑任何引擎。

核心约束（用户 2026-11-04 17:02 A1 批准条件）：

1. 理论价格 vs 实际成交价格严格分离：
   - 理论价（theoretical）= 信号/规则参考价（收盘价、止损价），
     不含任何执行成本；
   - 成交价（fill）= 理论价经**一次**不利调整后的价格，
     由唯一的 fill_price() 计算；
   - gross_theoretical_pct 只用理论价，gross_fill_pct 只用成交价，
     两者之差即 slip_cost_pct——滑点/价差只出现在这一处。
2. 防重复扣除：滑点与价差在同一侧只加总一次
   （fill = ref * (1 ± (slip + spread))，一次乘法）；手续费
   永远不折进成交价，单独以 fee_pct 列出；资金费单独列出。
   任何“成交价已含成本、又在净值里再扣一次”的路径在本模块
   中不存在——三个成本项各有唯一出处，恒等式
   net = gross_fill - fee - funding 在测试中逐项核对。
3. 费用基准显式化：fee_mode 写在密封规格里（two_sided_entry /
   filled / fixed），三种口径的公式各不相同，不得混用。
   B1 的 2*FEE 与 C5 的 FEE_RT 是两种不同的约定，本模块
   如实保留两种约定并标注来源，不强行“统一”成第三种算法。
4. 资金费：精确和取 (t0, t1]；区间模式按 C5 止损日约定
   （base = (t0, 触发日开盘] 之和，前缀自触发日起累积取极值）；
   覆盖缺口 > 24h 时拒绝计算（net=None），不插值、不估算。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class CostSpecsTampered(Exception):
    """密封成本规格被篡改：拒绝加载，不降级为警告。"""


class FundingCoverageGap(Exception):
    """资金费覆盖缺口 > 24h：拒绝计算净值。"""


@dataclass(frozen=True)
class CostSpec:
    """一条密封的成本规格。全部字段显式，无默认值猜测。"""
    name: str
    fee_per_side: float
    fee_mode: str  # "two_sided_entry" | "filled" | "fixed"
    fee_fixed_pct: float
    slip_entry: float
    spread_entry: float
    slip_exit: float
    spread_exit: float
    exit_cost_applies_to: str  # "all" | "stop_only"
    funding_mode: str  # "exact" | "interval"
    source: str


def load_sealed_cost_specs(specs_path: str | Path,
                           hash_path: str | Path) -> dict[str, CostSpec]:
    """读密封规格并校验 SHA256；不符即拒绝。"""
    specs_path = Path(specs_path)
    recorded = Path(hash_path).read_text(encoding="utf-8").strip().split()[0]
    actual = hashlib.sha256(specs_path.read_bytes()).hexdigest()
    if actual != recorded:
        raise CostSpecsTampered(
            f"cost specs tampered: recorded {recorded}, actual {actual}")
    data = json.loads(specs_path.read_text(encoding="utf-8"))
    out: dict[str, CostSpec] = {}
    for item in data["specs"]:
        spec = CostSpec(**{k: item[k] for k in
                           ("name", "fee_per_side", "fee_mode",
                            "fee_fixed_pct", "slip_entry", "spread_entry",
                            "slip_exit", "spread_exit",
                            "exit_cost_applies_to", "funding_mode",
                            "source")})
        out[spec.name] = spec
    return out


def fill_price(ref_px: float, direction: int, side: str, spec: CostSpec,
               exit_kind: str = "close") -> float:
    """理论价 -> 成交价：唯一调整点，滑点+价差只加总一次。

    多头入场/空头出场为不利方向取 +，反之取 -；手续费不参与。
    exit_cost_applies_to == "stop_only" 时，非止损出场不调整。
    """
    if direction not in (1, -1):
        raise ValueError(f"bad direction: {direction}")
    if side == "entry":
        adj = spec.slip_entry + spec.spread_entry
        return ref_px * (1 + direction * adj)
    if side == "exit":
        if spec.exit_cost_applies_to == "stop_only" and exit_kind != "stop":
            return ref_px
        adj = spec.slip_exit + spec.spread_exit
        return ref_px * (1 - direction * adj)
    raise ValueError(f"bad side: {side}")


def funding_exact_sum(records: list[tuple[int, float]], t0: int,
                      t1: int) -> float:
    """(t0, t1] 内结算费率精确和。"""
    return sum(r for (t, r) in records if t0 < t <= t1)


def funding_prefix_interval(records: list[tuple[int, float]],
                            entry_ms: int, low_cut_ms: int,
                            upper_ms: int) -> tuple[float, float]:
    """C5 止损日区间语义（精确复现 funding_for_leg）：
    base = (entry_ms, low_cut_ms] 内结算和（触发日 00:00 结算含在内）；
    前缀 = base 及之后每次触发日内结算的累积和；取 min/max。
    low_cut_ms = 触发日开盘时刻（entry + exit_day_idx 天）。
    """
    window = sorted((t, r) for (t, r) in records
                    if entry_ms < t < upper_ms)
    base = sum(r for (t, r) in window if t <= low_cut_ms)
    prefixes = [base]
    run = base
    for (t, r) in window:
        if low_cut_ms < t < upper_ms:
            run += r
            prefixes.append(run)
    return (min(prefixes), max(prefixes))


def check_funding_coverage(records: list[tuple[int, float]], t0: int,
                           t1: int, max_gap_ms: int = 24 * 3600000) -> None:
    """覆盖检查：[t0, t1] 内任一相邻结算点间隔 > 24h 即拒收。"""
    points = [t0] + sorted(t for (t, _) in records if t0 < t < t1) + [t1]
    for prev, cur in zip(points, points[1:]):
        if cur - prev > max_gap_ms:
            raise FundingCoverageGap(
                f"funding gap {cur - prev}ms > {max_gap_ms}ms in ({t0}, {t1}]")


@dataclass(frozen=True)
class CostBreakdown:
    """一笔交易的成本分解（全部以理论入场价为分母的百分比）。

    恒等式：net_pct == gross_fill_pct - fee_pct - funding_pct
    （exact 模式）；区间模式下 net_lo 用 funding_hi、net_hi 用
    funding_lo。slip_cost_pct == gross_theoretical_pct - gross_fill_pct，
    即滑点/价差的唯一出处。
    """
    fill_entry_px: float
    fill_exit_px: float
    gross_theoretical_pct: float
    gross_fill_pct: float
    slip_cost_pct: float
    fee_pct: float
    funding_pct: float | None
    funding_lo: float | None
    funding_hi: float | None
    funding_status: str  # "ok" | "coverage_gap"
    net_pct: float | None
    net_lo: float | None
    net_hi: float | None
    net_r: float | None
    net_r_lo: float | None
    net_r_hi: float | None


def apply_costs(theoretical_entry: float, theoretical_exit: float,
                direction: int, *, spec: CostSpec, exit_kind: str,
                funding_records: list[tuple[int, float]],
                t0_ms: int, t1_ms: int,
                funding_anchor_ms: int | None = None,
                stop_distance_pct: float | None = None) -> CostBreakdown:
    """统一成本计算（纯函数，确定性）。

    theoretical_exit = 规则止损价或收盘价（理论价）；成交价由
    fill_price() 唯一确定。funding_records 为 (t_ms, rate) 列表。
    """
    if theoretical_entry <= 0 or theoretical_exit <= 0:
        raise ValueError("prices must be positive")
    try:
        check_funding_coverage(funding_records, t0_ms, t1_ms)
    except FundingCoverageGap:
        fill_entry = fill_price(theoretical_entry, direction, "entry", spec)
        fill_exit = fill_price(theoretical_exit, direction, "exit", spec,
                               exit_kind)
        gross_theoretical = direction * (theoretical_exit - theoretical_entry) \
            / theoretical_entry
        gross_fill = direction * (fill_exit - fill_entry) / fill_entry
        return CostBreakdown(
            fill_entry_px=fill_entry, fill_exit_px=fill_exit,
            gross_theoretical_pct=gross_theoretical,
            gross_fill_pct=gross_fill,
            slip_cost_pct=gross_theoretical - gross_fill,
            fee_pct=0.0, funding_pct=None,
            funding_lo=None, funding_hi=None, funding_status="coverage_gap",
            net_pct=None, net_lo=None, net_hi=None, net_r=None,
            net_r_lo=None, net_r_hi=None)
    fill_entry = fill_price(theoretical_entry, direction, "entry", spec)
    fill_exit = fill_price(theoretical_exit, direction, "exit", spec,
                           exit_kind)
    gross_theoretical = direction * (theoretical_exit - theoretical_entry) \
        / theoretical_entry
    gross_fill = direction * (fill_exit - fill_entry) / fill_entry
    slip_cost = gross_theoretical - gross_fill
    if spec.fee_mode == "two_sided_entry":
        fee_pct = 2 * spec.fee_per_side
    elif spec.fee_mode == "filled":
        fee_pct = spec.fee_per_side * (fill_entry + fill_exit) \
            / theoretical_entry
    elif spec.fee_mode == "fixed":
        fee_pct = spec.fee_fixed_pct
    else:
        raise ValueError(f"unknown fee_mode: {spec.fee_mode}")
    anchor = t0_ms if funding_anchor_ms is None else funding_anchor_ms
    if spec.funding_mode == "exact":
        funding_pct = funding_exact_sum(funding_records, t0_ms, t1_ms)
        net = gross_fill - fee_pct - funding_pct
        return CostBreakdown(
            fill_entry_px=fill_entry, fill_exit_px=fill_exit,
            gross_theoretical_pct=gross_theoretical,
            gross_fill_pct=gross_fill, slip_cost_pct=slip_cost,
            fee_pct=fee_pct, funding_pct=funding_pct,
            funding_lo=funding_pct, funding_hi=funding_pct,
            funding_status="ok", net_pct=net, net_lo=net, net_hi=net,
            net_r=(net / stop_distance_pct
                   if stop_distance_pct else None),
            net_r_lo=(net / stop_distance_pct
                      if stop_distance_pct else None),
            net_r_hi=(net / stop_distance_pct
                      if stop_distance_pct else None))
    if spec.funding_mode == "interval":
        lo, hi = funding_prefix_interval(funding_records, t0_ms, anchor,
                                         t1_ms)
        net_lo = gross_fill - fee_pct - hi
        net_hi = gross_fill - fee_pct - lo
        return CostBreakdown(
            fill_entry_px=fill_entry, fill_exit_px=fill_exit,
            gross_theoretical_pct=gross_theoretical,
            gross_fill_pct=gross_fill, slip_cost_pct=slip_cost,
            fee_pct=fee_pct, funding_pct=None, funding_lo=lo,
            funding_hi=hi, funding_status="ok", net_pct=None,
            net_lo=net_lo, net_hi=net_hi, net_r=None,
            net_r_lo=(net_lo / stop_distance_pct
                      if stop_distance_pct else None),
            net_r_hi=(net_hi / stop_distance_pct
                      if stop_distance_pct else None))
    raise ValueError(f"unknown funding_mode: {spec.funding_mode}")
