"""端到端集成测试：真实接线前的因果证明（合成对齐时间戳序列）。

须在真实回测前全过；任一失败即停止 B2。覆盖：1H Pivot 确认
时序、锚点只取 15m 已确认点、5m 穿透与止损优先、资金费结算
边界、前缀/全量一致（无未来函数）、缺失 bar 检出、触发语义
与冻结 SignalEngine 等价。
"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _deps import Bar  # noqa: E402
from bos import detect_bos  # noqa: E402
from config import SMCConfig  # noqa: E402
from cost_model import price_trade  # noqa: E402
from helpers import mk_bars  # noqa: E402
from live_engine import (LookaheadError, MarketData, _bars_from_npz,  # noqa: E402
                         build_confirmed_pivot_series,
                         build_confirmed_pivot_series_1h,
                         build_trend_series,
                         detect_bos_from_gates, load_market_data,
                         run_segment, trades_hash)
from structure import atr_wilder, find_pivots, trend_state  # noqa: E402

CFG3 = SMCConfig(atr_period=3)
BASE = 1577836800000


def _flat(n, px=100.0):
    return [(px, px + 1, px - 1, px)] * n


def _market(spec15, spec1h, spec5m, atr_period=3):
    bars15 = mk_bars(spec15, start_ms=BASE, step_ms=900000)
    bars1h = mk_bars(spec1h, start_ms=BASE, step_ms=3600000)
    bars5 = mk_bars(spec5m, start_ms=BASE, step_ms=300000)
    cfg = SMCConfig(atr_period=atr_period)
    atr = atr_wilder(bars15, cfg.atr_period)
    p15 = find_pivots(bars15, 2, 2)
    p1h = find_pivots(bars1h, 2, 2)
    highs, lows = build_confirmed_pivot_series(bars15, p15)
    highs_1h, lows_1h = build_confirmed_pivot_series_1h(
        bars1h, bars15, p1h)
    return MarketData(
        bars_15m=bars15, bars_5m=bars5, bars_1h=bars1h,
        t_5m=[b.open_time for b in bars5],
        t_15m=[b.open_time for b in bars15],
        funding_records=[(BASE, 0.0001)],
        atr_15m=atr, pivots_15m=p15, pivots_1h=p1h,
        trend_at=build_trend_series(bars1h, bars15, p1h),
        high_at=highs, low_at=lows,
        high_at_1h=highs_1h, low_at_1h=lows_1h)


def _zigzag_1h():
    # 高点 @3(104,conf@5)/@6(106,conf@8) HH，低点 @2(95,conf@4)/
    # @5(97,conf@7) HL；峰谷错开（find_pivots 的 elif 使同 bar
    # 不能兼为高低 Pivot）。15m bar 35 起趋势 long；15m bar 35
    # 收盘 107 突破最近已确认 1H 结构点 106（解释 I2，SPEC v1.1）。
    highs = [100, 101, 102, 104, 103, 102, 106, 105, 104, 103, 102, 101]
    lows = [99, 100, 95, 99, 98, 97, 100, 99, 101, 100, 99, 98]
    return [((h + l) / 2, h, l, (h + l) / 2) for h, l in zip(highs, lows)]


def _derive_5m(spec15):
    out = []
    for (o, h, l, c) in spec15:
        out.extend([(o, h, l, c)] * 3)
    return out


class TrendSweepTest(unittest.TestCase):
    def test_trend_series_matches_naive(self):
        spec1h = _zigzag_1h() * 3  # 30 根 1H，重复 zigzag
        bars1h = mk_bars(spec1h, start_ms=BASE, step_ms=3600000)
        bars15 = mk_bars(_flat(120), start_ms=BASE, step_ms=900000)
        pivots = find_pivots(bars1h, 2, 2)
        got = build_trend_series(bars1h, bars15, pivots)
        closes = [b.open_time + 3600000 for b in bars1h]
        for i, bar in enumerate(bars15):
            import bisect
            k = bisect.bisect_right(closes, bar.open_time + 900000) - 1
            want = trend_state(find_pivots(bars1h, 2, 2, as_of=k)) \
                if k >= 0 else "none"
            self.assertEqual(got[i], want, f"bar {i}")

    def test_trend_only_after_confirmation(self):
        bars1h = mk_bars(_zigzag_1h(), start_ms=BASE, step_ms=3600000)
        bars15 = mk_bars(_flat(40), start_ms=BASE, step_ms=900000)
        pivots = find_pivots(bars1h, 2, 2)
        got = build_trend_series(bars1h, bars15, pivots)
        # 第二对 Pivot 在 1H bar 8 确认（bar 8 收盘 = 9h）；15m
        # bar 35 收盘恰为 9h，此前 trend 须为 none，此后为 long。
        self.assertEqual(got[34], "none")
        self.assertEqual(got[35], "long")


class BosGateTest(unittest.TestCase):
    def test_bos_gates_match_detect_bos(self):
        spec = _flat(30)
        spec[10] = (102, 103, 100, 102)
        spec[15] = (98, 100, 97, 98)
        spec[20] = (104, 108, 102, 107)
        spec[25] = (100, 101, 96, 97)
        bars = mk_bars(spec, start_ms=BASE, step_ms=900000)
        atr = atr_wilder(bars, 3)
        pivots = find_pivots(bars, 2, 2)
        highs, lows = build_confirmed_pivot_series(bars, pivots)
        for i in range(len(bars)):
            want = detect_bos(bars, pivots, atr, i, 0.1)
            got = detect_bos_from_gates(i, bars[i].close, atr[i],
                                        highs[i], lows[i], 0.1)
            self.assertEqual(got, want, f"bar {i}")


class AnchorGatingTest(unittest.TestCase):
    def _scenario(self):
        spec15 = _flat(40)
        spec15[30] = (100, 101, 99, 100)
        spec15[31] = (102, 103, 100, 102)
        spec15[32] = (100, 101, 99, 100)
        spec15[33] = (98, 100, 97, 98)
        spec15[34] = (100, 102, 98, 101)
        spec15[35] = (104, 108, 102, 107)
        spec15[36] = (106, 107, 90, 106)  # 未确认的更低低点（conf@38）
        spec15[37] = (100, 102, 95, 101)
        spec15[38] = (101, 103, 96, 102)
        spec15[39] = (100, 101, 99, 100)
        return spec15

    def test_anchor_ignores_unconfirmed_lower_low(self):
        spec15 = self._scenario()
        data = _market(spec15, _zigzag_1h(), _derive_5m(spec15))
        res = run_segment(data, "train", 0, 40, "baseline", CFG3)
        self.assertGreaterEqual(len(res.orders), 1)
        first = res.orders[0]
        self.assertEqual(first.created_bar, 35)
        self.assertAlmostEqual(first.limit_px, 101.0)
        # 止损锚 = 已确认低点 @33 的 97，而不是未确认的 90。
        self.assertAlmostEqual(first.stop_px, 97.0)


class FillSettlementTest(unittest.TestCase):
    def test_equality_no_fill_then_stop_first(self):
        # 复用锚点场景（40 根，订单在 bar 35）；重建 5m 窗口：
        # 15m bar 36 的三根 5m（下标 108,109,110）。
        spec15 = _flat(40)
        spec15[30] = (100, 101, 99, 100)
        spec15[31] = (102, 103, 100, 102)
        spec15[32] = (100, 101, 99, 100)
        spec15[33] = (98, 100, 97, 98)
        spec15[34] = (100, 102, 98, 101)
        spec15[35] = (104, 108, 102, 107)
        spec15[36] = (106, 107, 90, 106)
        spec15[37] = (100, 102, 95, 101)
        spec15[38] = (101, 103, 96, 102)
        spec15[39] = (100, 101, 99, 100)
        data0 = _market(spec15, _zigzag_1h(), _derive_5m(spec15))
        res0 = run_segment(data0, "train", 0, 40, "baseline", CFG3)
        self.assertEqual(len(res0.orders), 1)
        order = res0.orders[0]
        limit, stop = order.limit_px, order.stop_px
        spec5 = _derive_5m(spec15)
        # 第一根 5m low == limit 不成交；第二根穿透且触止损与
        # 止盈 → 同 bar 止损优先并记 ambiguity。
        spec5[108] = (limit + 1, limit + 1, limit, limit + 0.5)
        spec5[109] = (limit, order.target_px + 1, stop - 1, limit)
        data = _market(spec15, _zigzag_1h(), spec5)
        res = run_segment(data, "train", 0, 40, "baseline", CFG3)
        self.assertEqual(len(res.orders), 1)
        self.assertEqual(res.orders[0].status, "filled")
        self.assertEqual(res.orders[0].fill_5m_index, 109)
        self.assertEqual(len(res.trades), 1)
        trade = res.trades[0]
        self.assertEqual(trade.outcome, "stop")
        self.assertEqual(trade.exit_px, stop)
        self.assertEqual(trade.ambiguity,
                         "stop-and-target-same-bar-stop-first")


class FundingBoundaryTest(unittest.TestCase):
    def test_settlement_at_t1_included_t0_excluded(self):
        recs = [(0, 0.001), (28800000, 0.002)]
        out = price_trade(100.0, 102.0, 1, entry_fill_type="maker",
                          exit_fill_type="taker", entry_fee_rate=0.0,
                          exit_fee_rate=0.0, fee_source="test",
                          funding_records=recs, t0_ms=0,
                          t1_ms=28800000, stop_distance_pct=0.02)
        self.assertAlmostEqual(out.funding_pct, 0.002)
        out2 = price_trade(100.0, 102.0, 1, entry_fill_type="maker",
                           exit_fill_type="taker", entry_fee_rate=0.0,
                           exit_fee_rate=0.0, fee_source="test",
                           funding_records=recs, t0_ms=0,
                           t1_ms=28799999, stop_distance_pct=0.02)
        self.assertAlmostEqual(out2.funding_pct, 0.0)


class PrefixConsistencyTest(unittest.TestCase):
    def test_prefix_orders_match_and_deterministic(self):
        spec15 = _flat(40)
        spec15[30] = (100, 101, 99, 100)
        spec15[31] = (102, 103, 100, 102)
        spec15[32] = (100, 101, 99, 100)
        spec15[33] = (98, 100, 97, 98)
        spec15[34] = (100, 102, 98, 101)
        spec15[35] = (104, 108, 102, 107)
        spec15[36] = (106, 107, 90, 106)
        spec15[37] = (100, 102, 95, 101)
        spec15[38] = (101, 103, 96, 102)
        spec15[39] = (100, 101, 99, 100)
        data = _market(spec15, _zigzag_1h(), _derive_5m(spec15))
        full = run_segment(data, "train", 0, 40, "baseline", CFG3)
        full2 = run_segment(data, "train", 0, 40, "baseline", CFG3)
        self.assertEqual(trades_hash(full.trades),
                         trades_hash(full2.trades))
        short = run_segment(data, "train", 0, 37, "baseline", CFG3)
        key = lambda o: (o.direction, o.limit_px, o.stop_px,
                         o.target_px, o.created_bar)
        short_keys = [key(o) for o in short.orders]
        full_keys = [key(o) for o in full.orders]
        for k in short_keys:
            self.assertIn(k, full_keys)


class GapDetectionTest(unittest.TestCase):
    def test_missing_bar_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = np.array([0, 900000, 2700000], dtype=np.int64)
            ohlc = np.array([[100, 101, 99, 100]] * 3, dtype=float)
            np.savez(Path(tmp) / "x.npz", t=t, ohlc=ohlc)
            with self.assertRaises(LookaheadError):
                _bars_from_npz(Path(tmp) / "x.npz", 900000, "test")


class Bos1hSeriesTest(unittest.TestCase):
    def test_1h_series_matches_naive(self):
        spec1h = _zigzag_1h() * 3  # 30 根 1H，重复 zigzag
        bars1h = mk_bars(spec1h, start_ms=BASE, step_ms=3600000)
        bars15 = mk_bars(_flat(120), start_ms=BASE, step_ms=900000)
        pivots = find_pivots(bars1h, 2, 2)
        highs, lows = build_confirmed_pivot_series_1h(
            bars1h, bars15, pivots)
        closes = [b.open_time + 3600000 for b in bars1h]
        for i, bar in enumerate(bars15):
            import bisect
            k = bisect.bisect_right(closes, bar.open_time + 900000) - 1
            if k < 0:
                self.assertIsNone(highs[i], f"bar {i}")
                self.assertIsNone(lows[i], f"bar {i}")
                continue
            conf = find_pivots(bars1h, 2, 2, as_of=k)
            want_h = [p for p in conf if p.kind == "high"]
            want_l = [p for p in conf if p.kind == "low"]
            self.assertEqual(
                highs[i].price if highs[i] else None,
                want_h[-1].price if want_h else None, f"bar {i}")
            self.assertEqual(
                lows[i].price if lows[i] else None,
                want_l[-1].price if want_l else None, f"bar {i}")

    def test_1h_pivot_only_after_confirmation_close(self):
        bars1h = mk_bars(_zigzag_1h(), start_ms=BASE, step_ms=3600000)
        bars15 = mk_bars(_flat(40), start_ms=BASE, step_ms=900000)
        pivots = find_pivots(bars1h, 2, 2)
        highs, lows = build_confirmed_pivot_series_1h(
            bars1h, bars15, pivots)
        # 第二个 1H 高点 106 在 1H bar 8 确认（bar 8 收盘 = 9h）；
        # 15m bar 34 收盘 8.75h 时仍为 104，bar 35 收盘 9h 时为 106。
        self.assertEqual(highs[34].price, 104)
        self.assertEqual(highs[35].price, 106)
        # 低点 97 在 1H bar 7 确认（收盘 8h）；bar 31 收盘 8h 时
        # 已可用，bar 30 收盘 7.75h 时仍为 95。
        self.assertEqual(lows[30].price, 95)
        self.assertEqual(lows[31].price, 97)

    def test_bos_breaks_1h_structure_not_15m(self):
        # 锚点场景：15m bar 35 收盘 107。15m 已确认高点仅 ~103，
        # 1H 已确认高点为 106；BOS 结构价须为 106（解释 I2）。
        spec15 = AnchorGatingTest()._scenario()
        data = _market(spec15, _zigzag_1h(), _derive_5m(spec15))
        res = run_segment(data, "train", 0, 40, "baseline", CFG3)
        self.assertEqual(res.n_bos, 1)
        bos_logs = [s for s in res.signals if s.kind == "bos"]
        self.assertEqual(len(bos_logs), 1)
        self.assertEqual(bos_logs[0].bar_index, 35)
        self.assertIn("struct=106", bos_logs[0].detail)
        self.assertGreaterEqual(len(res.orders), 1)
        self.assertEqual(res.orders[0].created_bar, 35)


class EquivalenceTest(unittest.TestCase):
    def test_baseline_matches_signal_engine_driver(self):
        """同一 bar 流 + 同一 1H 趋势下，live 引擎触发订单须与
        冻结 SignalEngine 逐 bar 驱动的结果完全一致。BOS 按
        SPEC v1.1（解释 I2）取 1H 结构点，驱动端与 live 引擎
        同口径；止损锚仍取 15m Pivot。"""
        from fvg import find_fvgs as _find_fvgs
        from signals import SignalEngine

        spec = _flat(40)
        # 0..29 无 FVG（区间重叠），只留 31..35 的触发结构。
        spec[5] = (100, 102, 99, 101)
        spec[13] = (101, 103, 100, 102)
        spec[21] = (102, 104, 101, 103)
        spec[30] = (100, 101, 99, 100)
        spec[31] = (102, 103, 100, 102)
        spec[32] = (100, 101, 99, 100)
        spec[33] = (98, 100, 97, 98)
        spec[34] = (100, 102, 98, 101)
        spec[35] = (104, 108, 102, 107)
        spec[36] = (106, 107, 90, 106)
        spec[37] = (100, 102, 95, 101)
        spec[38] = (101, 103, 96, 102)
        spec[39] = (100, 101, 99, 100)
        bars = mk_bars(spec, start_ms=BASE, step_ms=900000)
        data = _market(spec, _zigzag_1h(), _derive_5m(spec))
        # 冻结引擎驱动（与 backtest.py 骨架同一循环，趋势取 1H）。
        eng = SignalEngine(CFG3)
        atr = data.atr_15m
        pivots = data.pivots_15m
        ref_orders = []
        for i, bar in enumerate(bars):
            trend = data.trend_at[i]
            bos = detect_bos_from_gates(i, bar.close, atr[i],
                                        data.high_at_1h[i],
                                        data.low_at_1h[i], 0.1)
            direction = bos.direction if bos is not None else (
                eng._bos.direction if eng.state == "BOS_SEEN" else 0)
            fvgs = _find_fvgs(bars, direction, atr, i, i, 0.2) \
                if direction != 0 else []
            order = eng.on_15m_close(i, trend, bos, fvgs, pivots, atr[i])
            if order is not None:
                ref_orders.append(order)
                eng.on_fill(i)
                eng.on_position_close(i, "test-reset")
        res = run_segment(data, "train", 0, 40, "baseline", CFG3)
        got = [(o.direction, o.limit_px, o.stop_px, o.target_px,
                o.created_bar) for o in res.orders]
        want = [(o.direction, o.limit_px, o.stop_px, o.target_px,
                 o.created_bar) for o in ref_orders]
        self.assertEqual(got, want)
        self.assertEqual(len(got), 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
