"""多时间框架对齐测试：边界时间戳、同时间收盘、缺失、未来函数。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from alignment import (bar_close_ms, check_series_gaps,  # noqa: E402
                       higher_tf_usable_bars, pivot_usable_at,
                       validate_strictly_increasing)
from backtest import BacktestEngine  # noqa: E402
from config import SMCConfig  # noqa: E402
from helpers import mk_bars  # noqa: E402
from structure import Pivot  # noqa: E402

HOUR = 3600000
QTR = 900000


class BoundaryTest(unittest.TestCase):
    def test_higher_tf_bar_closing_exactly_at_decision_usable(self):
        bars = mk_bars([(100, 101, 99, 100)], start_ms=0, step_ms=HOUR)
        usable = higher_tf_usable_bars(bars, HOUR, 3600000)
        self.assertEqual(len(usable), 1)

    def test_one_ms_late_not_usable(self):
        bars = mk_bars([(100, 101, 99, 100)], start_ms=0, step_ms=HOUR)
        self.assertEqual(higher_tf_usable_bars(bars, HOUR, 3599999), [])

    def test_same_time_close_usable(self):
        # 15m 决策 bar（open 2700000）与 1H bar（open 0）同在
        # 3600000 收盘：高周期 bar 可用（决策发生在收盘后）。
        decision_close = bar_close_ms(2700000, QTR)
        self.assertEqual(decision_close, 3600000)
        bars = mk_bars([(100, 101, 99, 100)], start_ms=0, step_ms=HOUR)
        self.assertEqual(len(higher_tf_usable_bars(
            bars, HOUR, decision_close)), 1)

    def test_pivot_usable_at_boundary(self):
        pivot = Pivot(index=2, kind="low", price=98.0, confirmed_at=4)
        # 15m 序列 base 0：确认 bar 下标 4，收盘时刻 5*900000。
        self.assertTrue(pivot_usable_at(pivot, QTR, 0, 4500000))
        self.assertFalse(pivot_usable_at(pivot, QTR, 0, 4499999))

    def test_pivot_one_ms_after_confirmation_not_usable(self):
        pivot = Pivot(index=2, kind="low", price=98.0, confirmed_at=4)
        self.assertFalse(pivot_usable_at(pivot, QTR, 0, 4500000 - 1))


class GapTest(unittest.TestCase):
    def test_missing_bar_detected(self):
        gaps = check_series_gaps([0, QTR, 3 * QTR], QTR)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["index"], 2)
        self.assertEqual(gaps[0]["expected_ms"], 2 * QTR)
        self.assertEqual(gaps[0]["actual_ms"], 3 * QTR)
        self.assertEqual(gaps[0]["delta_ms"], QTR)

    def test_clean_series_no_gaps(self):
        self.assertEqual(
            check_series_gaps([0, QTR, 2 * QTR, 3 * QTR], QTR), [])

    def test_non_increasing_reported(self):
        gaps = check_series_gaps([0, QTR, QTR], QTR)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["delta_ms"], -QTR)

    def test_validate_strictly_increasing(self):
        bars = mk_bars([(100, 101, 99, 100)] * 3)
        validate_strictly_increasing(bars)
        dup = mk_bars([(100, 101, 99, 100)] * 2)
        dup[1] = dup[0]
        with self.assertRaises(ValueError):
            validate_strictly_increasing(dup)
        with self.assertRaises(ValueError):
            validate_strictly_increasing([])

    def test_backtest_rejects_gapped_series(self):
        spec = [(99, 100, 98, 99), (100, 101, 99, 100),
                (102, 103, 100, 102)]
        bars = mk_bars(spec)
        bars[2] = mk_bars([spec[2]], start_ms=3 * QTR)[0]
        eng = BacktestEngine(SMCConfig(atr_period=3))
        with self.assertRaises(ValueError):
            eng.run_synthetic(bars, "synthetic")


class LookaheadTest(unittest.TestCase):
    def test_prefix_run_equals_full_run_on_prefix(self):
        # 前缀 13 根与全量 16 根（后补 3 根平 bar）在前缀区间
        # 的订单必须完全一致：追加未来数据不得改变已有订单。
        spec = [
            (99, 100, 98, 99), (100, 101, 99, 100),
            (102, 103, 100, 102), (100, 101, 99, 100),
            (98, 100, 97, 98), (98, 102, 98, 101),
            (101, 104, 99, 103), (103, 106, 100, 105),
            (103, 104, 100, 101), (101, 102, 99, 100),
            (100, 105, 100, 104), (104, 108, 102, 107),
            (107, 109, 106.5, 108),
        ]
        prefix = mk_bars(spec)
        full = mk_bars(spec + [(108, 109, 107, 108)] * 3)
        eng_p = BacktestEngine(SMCConfig(atr_period=3))
        eng_f = BacktestEngine(SMCConfig(atr_period=3))
        out_p = eng_p.run_synthetic(prefix, "synthetic")
        out_f = eng_f.run_synthetic(full, "synthetic")
        key = lambda o: (o.direction, o.limit_px, o.stop_px, o.target_px,
                         o.effective_bar, o.expiry_bar, o.status)
        self.assertEqual([key(o) for o in out_p["orders"]],
                         [key(o) for o in out_f["orders"]])


if __name__ == "__main__":
    unittest.main(verbosity=1)
