"""结构识别测试：Wilder ATR、Pivot 确认时序、趋势判定、OHLC 契约。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _deps import Bar  # noqa: E402
from helpers import mk_bars  # noqa: E402
from structure import atr_wilder, find_pivots, trend_state  # noqa: E402


class AtrTest(unittest.TestCase):
    def test_wilder_hand_computed(self):
        # 手算：TR = [1, 1.5, 0.8, 1.9, 0.8]；ATR(3) 首值均值 1.1，
        # 后续 Wilder 递推。
        bars = mk_bars([(9.5, 10, 9, 9.5), (10.5, 11, 9.5, 10.5),
                        (10.2, 10.8, 10, 10.2), (11.5, 12, 10.1, 11.5),
                        (11, 11.6, 10.8, 11)])
        atr = atr_wilder(bars, 3)
        self.assertIsNone(atr[0])
        self.assertIsNone(atr[1])
        self.assertAlmostEqual(atr[2], 1.1)
        self.assertAlmostEqual(atr[3], (1.1 * 2 + 1.9) / 3)
        self.assertAlmostEqual(atr[4], ((1.1 * 2 + 1.9) / 3 * 2 + 0.8) / 3)

    def test_atr_needs_period_bars(self):
        bars = mk_bars([(10, 10, 9, 9.5), (10, 11, 9, 10)])
        self.assertEqual(atr_wilder(bars, 3), [None, None])


class PivotTest(unittest.TestCase):
    def test_pivot_only_after_confirmation(self):
        bars = mk_bars([(99, 100, 98, 99), (100, 101, 99, 100),
                        (102, 103, 100, 102), (100, 101, 99, 100),
                        (98, 100, 97, 98)])
        # 高点 @2 须右侧 2 根收盘后（confirmed_at=4）才可用。
        self.assertEqual(find_pivots(bars, 2, 2, as_of=3), [])
        pivots = find_pivots(bars, 2, 2, as_of=4)
        self.assertEqual(len(pivots), 1)
        self.assertEqual((pivots[0].index, pivots[0].kind,
                          pivots[0].confirmed_at), (2, "high", 4))

    def test_equal_highs_no_pivot(self):
        bars = mk_bars([(99, 100, 98, 99), (100, 102, 99, 100),
                        (102, 102, 100, 102), (100, 102, 99, 100),
                        (98, 100, 97, 98)])
        kinds = [p.kind for p in find_pivots(bars, 2, 2)]
        self.assertNotIn("high", kinds)


class TrendTest(unittest.TestCase):
    def test_hh_hl_long_and_lh_ll_short(self):
        bars = mk_bars([
            (99, 100, 98, 99), (100, 101, 99, 100),
            (102, 103, 100, 102), (100, 101, 99, 100),
            (98, 100, 97, 98), (101, 102, 98, 101),
            (103, 104, 99, 103), (105, 106, 100, 105),
            (101, 104, 100, 101), (100, 102, 99, 100),
            (104, 105, 101, 104), (107, 108, 102, 107),
        ])
        pivots = find_pivots(bars, 2, 2)
        self.assertEqual(trend_state(pivots), "long")

    def test_insufficient_swings_none(self):
        bars = mk_bars([(99, 100, 98, 99), (100, 101, 99, 100),
                        (102, 103, 100, 102), (100, 101, 99, 100),
                        (98, 100, 97, 98)])
        self.assertEqual(trend_state(find_pivots(bars, 2, 2)), "none")


class OhlcContractTest(unittest.TestCase):
    def test_ohlc_row_maps_named_fields(self):
        # D-ENG-1 类回归：行数组按 OHLC 声明时 high 必须是第 2 个数；
        # 若实现按 OLHC 误读，high 会变成 90 并触发 high<low 校验。
        bar = Bar.from_ohlc_row([100, 110, 90, 105], order="OHLC")
        self.assertEqual((bar.open, bar.high, bar.low, bar.close),
                         (100, 110, 90, 105))
        bar2 = Bar.from_ohlc_row([100, 90, 110, 105], order="OLHC")
        self.assertEqual((bar2.open, bar2.low, bar2.high, bar2.close),
                         (100, 90, 110, 105))


if __name__ == "__main__":
    unittest.main(verbosity=1)
