"""止损锚点解析器测试：无锚点、未确认、错误方向、距离过滤、边界。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from anchor import resolve_stop_anchor  # noqa: E402
from bos import BOS  # noqa: E402
from config import SMCConfig  # noqa: E402
from fvg import FVG  # noqa: E402
from signals import SignalEngine  # noqa: E402
from structure import Pivot  # noqa: E402


def _low(price, confirmed_at, index=6):
    return Pivot(index=index, kind="low", price=price,
                 confirmed_at=confirmed_at)


def _high(price, confirmed_at, index=6):
    return Pivot(index=index, kind="high", price=price,
                 confirmed_at=confirmed_at)


class ResolverTest(unittest.TestCase):
    def test_no_anchor_empty(self):
        self.assertIsNone(resolve_stop_anchor([], 1, 10))

    def test_unconfirmed_anchor_unusable(self):
        pivots = [_low(98.0, confirmed_at=12)]
        self.assertIsNone(resolve_stop_anchor(pivots, 1, 11))

    def test_wrong_direction_returns_none(self):
        # 多头只要摆动低点；只有高点时返回 None，不得取错方向。
        self.assertIsNone(resolve_stop_anchor([_high(105.0, 8)], 1, 10))
        self.assertIsNone(resolve_stop_anchor([_low(98.0, 8)], -1, 10))

    def test_short_takes_high(self):
        self.assertEqual(
            resolve_stop_anchor([_high(105.0, 8), _low(98.0, 8)], -1, 10),
            105.0)

    def test_nearest_confirmed_wins(self):
        pivots = [_low(97.0, 6, index=4), _low(99.0, 9, index=7),
                  _low(100.0, 12, index=10)]
        self.assertEqual(resolve_stop_anchor(pivots, 1, 10), 99.0)

    def test_boundary_confirmed_at_equals_as_of(self):
        pivots = [_low(98.0, 10)]
        self.assertEqual(resolve_stop_anchor(pivots, 1, 10), 98.0)
        self.assertIsNone(resolve_stop_anchor(pivots, 1, 9))

    def test_boundary_near_first_bar(self):
        # 首个可能 Pivot：index=2，right=2 → confirmed_at=4。
        pivots = [_low(98.0, 4, index=2)]
        self.assertIsNone(resolve_stop_anchor(pivots, 1, 3))
        self.assertEqual(resolve_stop_anchor(pivots, 1, 4), 98.0)

    def test_bad_direction_rejected(self):
        with self.assertRaises(ValueError):
            resolve_stop_anchor([_low(98.0, 8)], 0, 10)


class EngineAnchorTest(unittest.TestCase):
    def _engine_with_bos(self, pivots):
        eng = SignalEngine(SMCConfig(atr_period=3))
        bos = BOS(bar_index=10, direction=1, structure_px=100.0,
                  structure_index=8, atr=2.0, close_px=101.0)
        eng.on_15m_close(10, "long", bos, [], pivots, 2.0)
        return eng

    def test_no_anchor_skips_and_logs(self):
        eng = self._engine_with_bos([])
        fvg = FVG(bar_index=11, direction=1, top=102.0, bottom=100.0,
                  mid=101.0, gap=2.0, gap_atr=1.0)
        eng.on_15m_close(11, "long", None, [fvg], [], 2.0)
        self.assertEqual(eng.state, "IDLE")
        self.assertTrue(any(e.kind == "skip"
                            and "anchor" in e.detail
                            for e in eng.events))

    def test_unconfirmed_anchor_skips(self):
        pivots = [_low(98.0, confirmed_at=12)]
        eng = self._engine_with_bos(pivots)
        fvg = FVG(bar_index=11, direction=1, top=102.0, bottom=100.0,
                  mid=101.0, gap=2.0, gap_atr=1.0)
        eng.on_15m_close(11, "long", None, [fvg], pivots, 2.0)
        self.assertEqual(eng.state, "IDLE")
        self.assertIsNone(eng.order)

    def test_stop_too_far_skips(self):
        # 锚 94 距入场 101 为 7/2 = 3.5 ATR > 3 → 跳过。
        pivots = [_low(94.0, 8)]
        eng = self._engine_with_bos(pivots)
        fvg = FVG(bar_index=11, direction=1, top=102.0, bottom=100.0,
                  mid=101.0, gap=2.0, gap_atr=1.0)
        eng.on_15m_close(11, "long", None, [fvg], pivots, 2.0)
        self.assertEqual(eng.state, "IDLE")
        self.assertTrue(any(e.kind == "skip" and e.detail == "stop-too-far"
                            for e in eng.events))

    def test_confirmed_anchor_creates_order(self):
        pivots = [_low(98.0, 8)]
        eng = self._engine_with_bos(pivots)
        fvg = FVG(bar_index=11, direction=1, top=102.0, bottom=100.0,
                  mid=101.0, gap=2.0, gap_atr=1.0)
        order = eng.on_15m_close(11, "long", None, [fvg], pivots, 2.0)
        self.assertIsNotNone(order)
        self.assertEqual(order.stop_px, 98.0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
