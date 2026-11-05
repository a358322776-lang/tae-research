"""B2 真实数据接线引擎：1H 趋势 + 15m 信号 + 5m 代理成交。

时间语义（唯一口径，见 alignment.py）：决策时刻 = 某根 15m bar
的收盘时刻（open_time + 900000）；只能用收盘时刻 <= 决策时刻
的 bar。1H Pivot 在确认 bar 收盘后可用；15m Pivot 同理。

信号口径（解释 I2，B2 报告 §1 显式声明、待用户确认）：
趋势过滤用 1H Pivot；BOS 结构点用 15m 已确认 Pivot；FVG 用
15m 三根形态；止损锚用 15m 已确认反向结构点（经
anchor.resolve_stop_anchor，信号路径直接调用）。

触发语义与冻结的 signals.SignalEngine 完全一致（BOS_SEEN 窗口、
同 bar FVG、过期、跳过原因），等价性由 test_integration 证明；
消融开关只改变触发条件（mode 参数），不改任何冻结参数。
单遍指针推进：Pivot/趋势按确认时刻预扫，5m 只在订单/持仓
存续期推进；段间状态清零，段末未平仓记 censored。

成交与资金费口径见 SPEC §4/§5：5m 严格穿透、止损优先、
资金费 (t0, t1] 精确和（t0=成交 bar open_time，t1=出场 bar
open_time，约定见 B2 报告）；全部输出标注 5m proxy execution。
本模块只读缓存，永不写数据文件；最终测试段一律拒绝。
"""

from __future__ import annotations

import bisect
import csv
import hashlib
import json
from dataclasses import asdict, dataclass, field

from _deps import Bar
from alignment import check_series_gaps, validate_strictly_increasing
from anchor import resolve_stop_anchor
from bos import BOS
from config import SMCConfig
from cost_model import TradeCost, price_trade
from execution import resolve_bar, simulate_limit_fill
from funding_gate import check_funding_records
from fvg import find_fvgs
from risk import compute_stop_target
from signals import Order
from structure import Pivot, atr_wilder, find_pivots, trend_state

STEP_15M = 900_000
STEP_5M = 300_000
STEP_1H = 3_600_000

MODES = ("baseline", "no-bos", "no-fvg", "no-trend")

CENTRAL_TIER = {
    "name": "central",
    "maker": 0.0002,
    "taker": 0.0005,
    "slip_spread_per_side": 0.0,
    "fee_source": "SPEC-v1.0-central: Binance USD-M Regular/VIP0 list "
                  "rates, RESEARCH HYPOTHESIS pending official "
                  "verification",
}
CONSERVATIVE_TIER = {
    "name": "conservative",
    "maker": 0.0004,
    "taker": 0.0010,
    "slip_spread_per_side": 0.0020,
    "fee_source": "SPEC-v1.0-conservative: doubled fees + 0.0020 "
                  "slip/spread per side, pre-registered stress tier",
}
COST_TIERS = (CENTRAL_TIER, CONSERVATIVE_TIER)


class LookaheadError(ValueError):
    """未来函数 / 时间错位：停止条件，禁止带病运行。"""


@dataclass
class SignalLog:
    bar_index: int
    bar_ms: int
    kind: str
    detail: str = ""


@dataclass
class OrderLog:
    order_id: str
    segment: str
    mode: str
    direction: int
    limit_px: float
    stop_px: float
    target_px: float
    stop_distance_atr: float
    created_bar: int
    created_ms: int
    effective_ms: int
    expiry_ms: int
    status: str  # filled | expired | pending_at_end
    fill_5m_index: int | None = None
    fill_ms: int | None = None
    ambiguity: str = ""


@dataclass
class TradeLog:
    trade_id: str
    segment: str
    mode: str
    direction: int
    entry_px: float
    exit_px: float | None
    stop_px: float
    target_px: float
    outcome: str  # stop | target | both-stop-first | censored
    ambiguity: str
    fill_ms: int
    exit_ms: int | None
    fill_5m_index: int
    exit_5m_index: int | None
    stop_distance_pct: float
    central: dict = field(default_factory=dict)
    conservative: dict = field(default_factory=dict)
    funding_status: str = "ok"
    proxy_fill: bool = True


@dataclass
class RunResult:
    segment: str
    mode: str
    signals: list[SignalLog]
    orders: list[OrderLog]
    trades: list[TradeLog]
    n_bars: int
    n_bos: int = 0
    n_fvg: int = 0
    n_skips: int = 0


def _bars_from_npz(path, step_ms: int, label: str) -> list[Bar]:
    import numpy as np

    d = np.load(path)
    t = [int(x) for x in d["t"]]
    ohlc = d["ohlc"]
    bars = [Bar(open_time=t[i], open=float(ohlc[i][0]),
                high=float(ohlc[i][1]), low=float(ohlc[i][2]),
                close=float(ohlc[i][3])) for i in range(len(t))]
    validate_strictly_increasing(bars)
    gaps = check_series_gaps(t, step_ms)
    if gaps:
        raise LookaheadError(f"{label}: bar timestamp gaps: {gaps[:3]}")
    return bars


def _trend_from_last_two(highs: list[Pivot], lows: list[Pivot]) -> str:
    """与 structure.trend_state 相同规则，只读最近两点（O(1)）。"""
    if len(highs) < 2 or len(lows) < 2:
        return "none"
    if highs[-1].price > highs[-2].price and lows[-1].price > lows[-2].price:
        return "long"
    if highs[-1].price < highs[-2].price and lows[-1].price < lows[-2].price:
        return "short"
    return "none"


def build_trend_series(bars_1h: list[Bar], bars_15m: list[Bar],
                       pivots_1h: list[Pivot]) -> list[str]:
    """每根 15m bar 决策时刻的 1H 趋势（只用已收盘确认的 Pivot）。

    先按 1H 下标扫确认：trend_1h[k] 只用 confirmed_at <= k 的
    Pivot；再按决策收盘时刻映射到 15m 下标（bisect 找已收盘
    的最后 1H bar）。"""
    closes_1h = [b.open_time + STEP_1H for b in bars_1h]
    ordered = sorted(pivots_1h, key=lambda p: p.confirmed_at)
    ptr = 0
    highs: list[Pivot] = []
    lows: list[Pivot] = []
    trend_1h: list[str] = []
    for k in range(len(bars_1h)):
        while ptr < len(ordered) and ordered[ptr].confirmed_at <= k:
            (highs if ordered[ptr].kind == "high" else lows).append(
                ordered[ptr])
            ptr += 1
        trend_1h.append(_trend_from_last_two(highs, lows))
    out: list[str] = []
    for bar in bars_15m:
        decision_close = bar.open_time + STEP_15M
        k = bisect.bisect_right(closes_1h, decision_close) - 1
        out.append(trend_1h[k] if k >= 0 else "none")
    return out


def build_confirmed_pivot_series(
        bars_15m: list[Bar],
        pivots_15m: list[Pivot]) -> tuple[list[Pivot | None],
                                          list[Pivot | None]]:
    """每根 15m bar 决策时刻最近已确认的高/低 Pivot（确认扫）。"""
    ordered = sorted(pivots_15m, key=lambda p: p.confirmed_at)
    ptr = 0
    last_high: Pivot | None = None
    last_low: Pivot | None = None
    highs: list[Pivot | None] = []
    lows: list[Pivot | None] = []
    for i in range(len(bars_15m)):
        while ptr < len(ordered) and ordered[ptr].confirmed_at <= i:
            if ordered[ptr].kind == "high":
                last_high = ordered[ptr]
            else:
                last_low = ordered[ptr]
            ptr += 1
        highs.append(last_high)
        lows.append(last_low)
    return highs, lows


def detect_bos_from_gates(bar_index: int, close: float,
                          atr: float | None,
                          high_p: Pivot | None, low_p: Pivot | None,
                          bos_min_atr: float) -> BOS | None:
    """与 bos.detect_bos 相同的判定，只读预扫的已确认 Pivot。"""
    if atr is None:
        return None
    if high_p is not None and close > high_p.price + bos_min_atr * atr:
        return BOS(bar_index=bar_index, direction=1,
                   structure_px=high_p.price, structure_index=high_p.index,
                   atr=atr, close_px=close)
    if low_p is not None and close < low_p.price - bos_min_atr * atr:
        return BOS(bar_index=bar_index, direction=-1,
                   structure_px=low_p.price, structure_index=low_p.index,
                   atr=atr, close_px=close)
    return None


@dataclass
class MarketData:
    bars_15m: list[Bar]
    bars_5m: list[Bar]
    bars_1h: list[Bar]
    t_5m: list[int]
    t_15m: list[int]
    funding_records: list[tuple[int, float]]
    atr_15m: list[float | None]
    pivots_15m: list[Pivot]
    pivots_1h: list[Pivot]
    trend_at: list[str]
    high_at: list[Pivot | None]
    low_at: list[Pivot | None]


def load_market_data(cache_dir) -> MarketData:
    """只读加载 stitched 缓存 + 资金费；缺口/门禁失败即报错停止。"""
    from pathlib import Path

    cache_dir = Path(cache_dir)
    bars_15m = _bars_from_npz(cache_dir / "stitched_15m.npz", STEP_15M,
                              "15m")
    bars_5m = _bars_from_npz(cache_dir / "stitched_5m.npz", STEP_5M, "5m")
    bars_1h = _bars_from_npz(cache_dir / "stitched_1h.npz", STEP_1H, "1h")
    t0 = bars_15m[0].open_time
    if bars_5m[0].open_time != t0 or bars_1h[0].open_time != t0:
        raise LookaheadError("timeframe series do not share base open_time")
    with open(cache_dir / "stitched_funding.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    funding = sorted((int(r["fundingTime"]), float(r["fundingRate"]))
                     for r in rows)
    check_funding_records(funding)  # 三项门禁不过即停
    cfg = SMCConfig()
    atr_15m = atr_wilder(bars_15m, cfg.atr_period)
    pivots_15m = find_pivots(bars_15m, cfg.pivot_left, cfg.pivot_right)
    pivots_1h = find_pivots(bars_1h, cfg.pivot_left, cfg.pivot_right)
    trend_at = build_trend_series(bars_1h, bars_15m, pivots_1h)
    high_at, low_at = build_confirmed_pivot_series(bars_15m, pivots_15m)
    return MarketData(
        bars_15m=bars_15m, bars_5m=bars_5m, bars_1h=bars_1h,
        t_5m=[b.open_time for b in bars_5m],
        t_15m=[b.open_time for b in bars_15m],
        funding_records=funding, atr_15m=atr_15m,
        pivots_15m=pivots_15m, pivots_1h=pivots_1h,
        trend_at=trend_at, high_at=high_at, low_at=low_at)


def _cost_one_trade(direction: int, entry_px: float, exit_px: float,
                    stop_distance_pct: float, funding_records, t0_ms: int,
                    t1_ms: int, tier: dict) -> TradeCost:
    return price_trade(
        entry_px, exit_px, direction, entry_fill_type="maker",
        exit_fill_type="taker", entry_fee_rate=tier["maker"],
        exit_fee_rate=tier["taker"], fee_source=tier["fee_source"],
        funding_records=funding_records, t0_ms=t0_ms, t1_ms=t1_ms,
        stop_distance_pct=stop_distance_pct,
        slip_spread_per_side=tier["slip_spread_per_side"])


def run_segment(data: MarketData, segment: str, start_idx: int,
                end_idx: int, mode: str,
                cfg: SMCConfig | None = None) -> RunResult:
    """跑一段（train/validation 之一，状态清零）。禁止 final_test。

    segment="rolling" 仅用于 SPEC §9 滚动评估：调用方保证
    [start_idx, end_idx) 完全落在 train+validation 范围内。
    """
    if segment not in ("train", "validation", "rolling"):
        raise ValueError(
            f"run_segment refuses segment {segment!r}: only "
            "train/validation/rolling-subset")
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    if not (0 <= start_idx < end_idx <= len(data.bars_15m)):
        raise ValueError(f"bad segment bounds [{start_idx}, {end_idx})")
    cfg = cfg or SMCConfig()
    bars15, bars5 = data.bars_15m, data.bars_5m
    segment_end_ms = bars15[end_idx - 1].open_time + STEP_15M
    # 5m 扫描上界：段末前最后一根 5m bar 下标。
    last_5m_in_segment = bisect.bisect_left(data.t_5m, segment_end_ms) - 1

    signals: list[SignalLog] = []
    orders: list[OrderLog] = []
    trades: list[TradeLog] = []
    n_bos = n_fvg = n_skips = 0
    order_seq = trade_seq = 0

    def log(i: int, kind: str, detail: str = "") -> None:
        signals.append(SignalLog(bar_index=i, bar_ms=bars15[i].open_time,
                                 kind=kind, detail=detail))

    def log_ms(bar_ms: int, kind: str, detail: str = "") -> None:
        # 5m 时间刻度的事件（成交/平仓）：bar_index 记 enclosing
        # 15m 下标，bar_ms 记事件 bar 的 open_time。
        idx = bisect.bisect_right(data.t_15m, bar_ms) - 1
        signals.append(SignalLog(bar_index=idx, bar_ms=bar_ms,
                                 kind=kind, detail=detail))

    def try_create_order(direction: int, entry_px: float, bar_index: int,
                         atr: float | None) -> Order | None:
        nonlocal n_skips
        anchor_px = resolve_stop_anchor(data.pivots_15m, direction,
                                        bar_index)
        if atr is None or anchor_px is None:
            log(bar_index, "skip", "missing-atr-or-anchor")
            n_skips += 1
            return None
        stop_target, reason = compute_stop_target(
            direction, entry_px, anchor_px, atr, cfg.stop_min_atr,
            cfg.stop_max_atr, cfg.target_r)
        if stop_target is None:
            log(bar_index, "skip", reason)
            n_skips += 1
            return None
        order = Order(
            direction=direction, limit_px=entry_px,
            stop_px=stop_target.stop_px, target_px=stop_target.target_px,
            stop_distance_atr=stop_target.stop_distance_atr,
            created_bar=bar_index, effective_bar=bar_index + 1,
            expiry_bar=bar_index + cfg.order_max_wait_bars)
        log(bar_index, "order",
            f"dir={direction} limit={entry_px} stop={order.stop_px}")
        return order

    def settle_order(order: Order) -> int:
        """成交扫描 + 持仓结算；返回下一根待处理的 15m 下标。"""
        nonlocal order_seq, trade_seq
        order_seq += 1
        oid = f"{segment}-{mode}-o{order_seq}"
        created_close_ms = bars15[order.created_bar].open_time + STEP_15M
        expiry_within = order.expiry_bar < len(bars15)
        expiry_close_ms = bars15[order.expiry_bar].open_time + STEP_15M \
            if expiry_within else segment_end_ms
        expiry_reached = expiry_within \
            and expiry_close_ms <= segment_end_ms
        first_5m = bisect.bisect_left(data.t_5m, created_close_ms)
        last_by_expiry = bisect.bisect_left(data.t_5m, expiry_close_ms) - 1
        last_5m = min(last_by_expiry, last_5m_in_segment)
        olog = OrderLog(
            order_id=oid, segment=segment, mode=mode,
            direction=order.direction, limit_px=order.limit_px,
            stop_px=order.stop_px, target_px=order.target_px,
            stop_distance_atr=order.stop_distance_atr,
            created_bar=order.created_bar,
            created_ms=bars15[order.created_bar].open_time,
            effective_ms=created_close_ms, expiry_ms=expiry_close_ms,
            status="pending")
        fill = None
        if first_5m <= last_5m:
            fill = simulate_limit_fill(order.limit_px, order.direction,
                                       bars5, first_5m, last_5m)
        if fill is None:
            if expiry_reached:
                olog.status = "expired"
                log(order.expiry_bar, "order_expired",
                    f"order expired unfilled, created={order.created_bar}")
                orders.append(olog)
                return min(order.expiry_bar + 1, end_idx)
            olog.status = "pending_at_end"
            orders.append(olog)
            return end_idx
        olog.status = "filled"
        olog.fill_5m_index = fill.bar_index
        olog.fill_ms = fill.fill_ms
        log_ms(fill.fill_ms, "filled",
               f"dir={order.direction} limit={order.limit_px}")
        orders.append(olog)
        # 持仓结算：从成交 bar 起（含）顺序结算，止损优先。
        exit_idx: int | None = None
        exit_outcome = ""
        exit_ambiguity = ""
        scan = fill.bar_index
        while scan <= last_5m_in_segment:
            out = resolve_bar(order.direction, order.stop_px,
                              order.target_px, bars5[scan])
            if out.outcome != "open":
                exit_idx = scan
                exit_outcome = out.outcome
                exit_ambiguity = out.ambiguity
                break
            scan += 1
        trade_seq += 1
        stop_distance_pct = abs(order.limit_px - order.stop_px) \
            / order.limit_px
        if exit_idx is None:
            trades.append(TradeLog(
                trade_id=f"{segment}-{mode}-t{trade_seq}", segment=segment,
                mode=mode, direction=order.direction,
                entry_px=order.limit_px, exit_px=None,
                stop_px=order.stop_px, target_px=order.target_px,
                outcome="censored", ambiguity="",
                fill_ms=fill.fill_ms, exit_ms=None,
                fill_5m_index=fill.bar_index, exit_5m_index=None,
                stop_distance_pct=stop_distance_pct))
            log(end_idx - 1, "censored",
                f"position open at segment end, created={order.created_bar}")
            return end_idx
        exit_bar = bars5[exit_idx]
        exit_px = order.stop_px if exit_outcome in ("stop",
                                                    "both-stop-first") \
            else order.target_px
        outcome = "stop" if exit_outcome in ("stop", "both-stop-first") \
            else "target"
        central = _cost_one_trade(
            order.direction, order.limit_px, exit_px, stop_distance_pct,
            data.funding_records, fill.fill_ms, exit_bar.open_time,
            CENTRAL_TIER)
        conservative = _cost_one_trade(
            order.direction, order.limit_px, exit_px, stop_distance_pct,
            data.funding_records, fill.fill_ms, exit_bar.open_time,
            CONSERVATIVE_TIER)
        funding_status = central.funding_status
        if funding_status != conservative.funding_status:
            raise LookaheadError(
                "cost tiers disagree on funding status: "
                f"{funding_status} vs {conservative.funding_status}")
        trades.append(TradeLog(
            trade_id=f"{segment}-{mode}-t{trade_seq}", segment=segment,
            mode=mode, direction=order.direction,
            entry_px=order.limit_px, exit_px=exit_px,
            stop_px=order.stop_px, target_px=order.target_px,
            outcome=outcome, ambiguity=exit_ambiguity,
            fill_ms=fill.fill_ms, exit_ms=exit_bar.open_time,
            fill_5m_index=fill.bar_index, exit_5m_index=exit_idx,
            stop_distance_pct=stop_distance_pct,
            central=asdict(central), conservative=asdict(conservative),
            funding_status=funding_status))
        log_ms(exit_bar.open_time, "closed", outcome)
        # 出场所在 15m bar 收盘后恢复 IDLE：其收盘时刻后方可再决策。
        enclosing = bisect.bisect_right(data.t_15m, exit_bar.open_time) - 1
        return max(order.created_bar + 1, min(enclosing, end_idx))

    bos_state: dict | None = None  # {direction, deadline}
    i = start_idx
    while i < end_idx:
        bar = bars15[i]
        atr = data.atr_15m[i]
        trend = data.trend_at[i]
        bos = detect_bos_from_gates(
            i, bar.close, atr, data.high_at[i], data.low_at[i],
            cfg.bos_min_atr)
        if mode == "no-trend":
            eff_trend = "long" if (bos is not None and bos.direction == 1) \
                else ("short" if bos is not None else "none")
        else:
            eff_trend = trend
        order: Order | None = None
        if mode == "no-bos":
            if eff_trend in ("long", "short"):
                want = 1 if eff_trend == "long" else -1
                fvgs = find_fvgs(bars15, want, data.atr_15m, i, i,
                                 cfg.fvg_min_atr)
                if fvgs:
                    n_fvg += 1
                    log(i, "fvg",
                        f"dir={want} mid={fvgs[0].mid} gap_atr={fvgs[0].gap_atr:.3f}")
                    order = try_create_order(want, fvgs[0].mid, i, atr)
        elif mode == "no-fvg":
            if bos is not None:
                n_bos += 1
                log(i, "bos",
                    f"dir={bos.direction} struct={bos.structure_px}")
                if eff_trend in ("long", "short"):
                    want = 1 if eff_trend == "long" else -1
                    if bos.direction == want:
                        order = try_create_order(want, bos.close_px, i,
                                                 atr)
                    else:
                        log(i, "bos_ignored_trend_mismatch",
                            f"bos_dir={bos.direction} trend={eff_trend}")
                        n_skips += 1
                else:
                    log(i, "bos_ignored_trend_mismatch",
                        f"bos_dir={bos.direction} trend={eff_trend}")
                    n_skips += 1
        else:  # baseline
            if bos_state is None:
                if bos is not None:
                    n_bos += 1
                    log(i, "bos",
                        f"dir={bos.direction} struct={bos.structure_px}")
                    if eff_trend in ("long", "short"):
                        want = 1 if eff_trend == "long" else -1
                        if bos.direction == want:
                            bos_state = {"direction": want,
                                         "deadline": i + cfg.bos_fvg_max_bars}
                            fvgs = find_fvgs(bars15, want, data.atr_15m,
                                             i, i, cfg.fvg_min_atr)
                            if fvgs:
                                n_fvg += 1
                                log(i, "fvg",
                                    f"dir={want} mid={fvgs[0].mid} "
                                    f"gap_atr={fvgs[0].gap_atr:.3f}")
                                order = try_create_order(want, fvgs[0].mid,
                                                         i, atr)
                                bos_state = None
                        else:
                            log(i, "bos_ignored_trend_mismatch",
                                f"bos_dir={bos.direction} trend={eff_trend}")
                            n_skips += 1
                    else:
                        log(i, "bos_ignored_trend_mismatch",
                            f"bos_dir={bos.direction} trend={eff_trend}")
                        n_skips += 1
            else:
                if i > bos_state["deadline"]:
                    log(i, "skip", "bos-fvg-window-expired")
                    n_skips += 1
                    bos_state = None
                    # 落入 IDLE 分支：同 bar 的新 BOS 仍可受理。
                    if bos is not None:
                        n_bos += 1
                        log(i, "bos",
                            f"dir={bos.direction} struct={bos.structure_px}")
                        if eff_trend in ("long", "short"):
                            want = 1 if eff_trend == "long" else -1
                            if bos.direction == want:
                                bos_state = {
                                    "direction": want,
                                    "deadline": i + cfg.bos_fvg_max_bars}
                                fvgs = find_fvgs(bars15, want, data.atr_15m,
                                                 i, i, cfg.fvg_min_atr)
                                if fvgs:
                                    n_fvg += 1
                                    log(i, "fvg",
                                        f"dir={want} mid={fvgs[0].mid} "
                                        f"gap_atr={fvgs[0].gap_atr:.3f}")
                                    order = try_create_order(
                                        want, fvgs[0].mid, i, atr)
                                    bos_state = None
                else:
                    want = bos_state["direction"]
                    fvgs = find_fvgs(bars15, want, data.atr_15m, i, i,
                                     cfg.fvg_min_atr)
                    if fvgs:
                        n_fvg += 1
                        log(i, "fvg",
                            f"dir={want} mid={fvgs[0].mid} "
                            f"gap_atr={fvgs[0].gap_atr:.3f}")
                        order = try_create_order(want, fvgs[0].mid, i, atr)
                        bos_state = None
                    # 无 FVG：保持 BOS_SEEN 等待；新 BOS 被忽略（冻结语义）。
        if order is not None:
            i = settle_order(order)
        else:
            i += 1
    return RunResult(segment=segment, mode=mode, signals=signals,
                     orders=orders, trades=trades, n_bars=end_idx - start_idx,
                     n_bos=n_bos, n_fvg=n_fvg, n_skips=n_skips)


def trades_hash(trades: list[TradeLog]) -> str:
    """确定性指纹：逐笔交易规范 JSON 的 SHA256。"""
    canonical = json.dumps([asdict(t) for t in trades], sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
