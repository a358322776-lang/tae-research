"""BOS 与 FVG 测试：阈值、确认时序、方向镜像。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import mk_bars  # noqa: E402
from bos import detect_bos  # noqa: E402
from fvg import find_fvgs  # noqa: E402
from structure import Pivot, atr_wilder  # noqa: E402


def _bars_with_atr():
    bars = mk_bars([(99, 100, 98, 99), (100, 101, 99, 100),
                    (102, 103, 100, 102), (100, 101, 99, 100),
                    (98, 100, 97, 98), (101, 102, 98, 101),
                    (103, 104, 99, 103), (105, 106, 100, 105),
                    (101, 104, 100, 101), (100, 102, 99, 100),
                    (104, 105, 101, 104), (107, 108, 102, 107)])
    return bars, atr_wilder(bars, 3)


class BosTest(unittest.TestCase):
    def test_bos_requires_confirmed_structure(self):
        bars, atr = _bars_with_atr()
        pivots = [Pivot(index=2, kind="high", price=103, confirmed_at=4)]
        # bar 3 收盘 100 未突破；且 @2 的结构点在 bar 3 已确认。
        self.assertIsNone(detect_bos(bars, pivots, atr, 3, 0.1))
        # bar 7 收盘 105 > 103 + 0.1*atr：BOS（结构点已确认）。
        bos = detect_bos(bars, pivots, atr, 7, 0.1)
        self.assertIsNotNone(bos)
        self.assertEqual(bos.direction, 1)

    def test_bos_ignores_unconfirmed_structure(self):
        bars, atr = _bars_with_atr()
        # 结构点 confirmed_at=8 > 决策 bar 7：不得用于 BOS。
        pivots = [Pivot(index=6, kind="high", price=104, confirmed_at=8)]
        self.assertIsNone(detect_bos(bars, pivots, atr, 7, 0.1))

    def test_bos_threshold(self):
        bars = mk_bars([(100, 100, 99, 99.5), (100, 101, 99, 100),
                        (101, 102, 100, 101), (102, 103, 101, 102)])
        atr = [None, None, 2.0, 2.0]
        pivots = [Pivot(index=1, kind="high", price=101, confirmed_at=1)]
        # close 102 > 101 + 0.1*2=101.2 → BOS。
        self.assertIsNotNone(detect_bos(bars, pivots, atr, 3, 0.1))
        # 阈值 0.6：102 < 101 + 1.2 → 无 BOS。
        self.assertIsNone(detect_bos(bars, pivots, atr, 3, 0.6))

    def test_bos_short_mirror(self):
        bars = mk_bars([(100, 101, 99, 100), (100, 100, 98, 99),
                        (99, 99, 97, 98), (98, 98, 96, 97)])
        atr = [None, None, 2.0, 2.0]
        pivots = [Pivot(index=1, kind="low", price=98, confirmed_at=1)]
        bos = detect_bos(bars, pivots, atr, 3, 0.1)
        self.assertIsNotNone(bos)
        self.assertEqual(bos.direction, -1)


class FvgTest(unittest.TestCase):
    def test_long_fvg_mid(self):
        bars = mk_bars([(100, 101, 99, 100), (101, 102, 100, 101),
                        (103, 104, 102.5, 103)])
        atr = [None, None, 2.0]
        fvgs = find_fvgs(bars, 1, atr, 2, 2, 0.2)
        self.assertEqual(len(fvgs), 1)
        self.assertAlmostEqual(fvgs[0].mid, (102.5 + 101) / 2)
        self.assertAlmostEqual(fvgs[0].gap, 1.5)

    def test_fvg_too_small_rejected(self):
        bars = mk_bars([(100, 101, 99, 100), (101, 102, 100, 101),
                        (103, 104, 101.1, 103)])
        atr = [None, None, 2.0]
        self.assertEqual(find_fvgs(bars, 1, atr, 2, 2, 0.2), [])

    def test_short_fvg_mirror(self):
        bars = mk_bars([(100, 101, 99, 100), (99, 100, 98, 99),
                        (97, 98, 96.5, 97)])
        atr = [None, None, 2.0]
        fvgs = find_fvgs(bars, -1, atr, 2, 2, 0.2)
        self.assertEqual(len(fvgs), 1)
        self.assertAlmostEqual(fvgs[0].mid, (99 + 98) / 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
