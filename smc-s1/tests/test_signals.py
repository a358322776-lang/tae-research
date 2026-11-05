"""信号状态机测试：BOS→FVG→挂单→成交/过期，单仓约束。

止损锚不再由调用方传入价格，改传 15m Pivot 列表，由解析器
内部按 confirmed_at 过滤（B2-FIX）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bos import BOS  # noqa: E402
from config import SMCConfig  # noqa: E402
from fvg import FVG  # noqa: E402
from signals import SignalEngine  # noqa: E402
from structure import Pivot  # noqa: E402


def _cfg():
    return SMCConfig(atr_period=3)


def _bos(bar=10, direction=1):
    return BOS(bar_index=bar, direction=direction, structure_px=100.0,
               structure_index=8, atr=2.0, close_px=101.0)


def _fvg(bar=11, direction=1):
    return FVG(bar_index=bar, direction=direction, top=102.0, bottom=100.0,
               mid=101.0, gap=2.0, gap_atr=1.0)


def _pivots(px=98.0, confirmed_at=8, kind="low"):
    """单个已确认反向结构点（多头默认取摆动低点 98）。"""
    return [Pivot(index=6, kind=kind, price=px, confirmed_at=confirmed_at)]


class SignalFlowTest(unittest.TestCase):
    def test_full_flow_to_order(self):
        eng = SignalEngine(_cfg())
        order = eng.on_15m_close(10, "long", _bos(), [], _pivots(), 2.0)
        self.assertIsNone(order)
        self.assertEqual(eng.state, "BOS_SEEN")
        order = eng.on_15m_close(11, "long", None, [_fvg()], _pivots(),
                                 2.0)
        self.assertIsNotNone(order)
        self.assertEqual((order.limit_px, order.stop_px), (101.0, 98.0))
        self.assertAlmostEqual(order.target_px, 101.0 + 2 * 3.0)
        self.assertEqual(order.effective_bar, 12)
        self.assertEqual(order.expiry_bar, 11 + 8)
        self.assertEqual(eng.state, "ORDER_PLACED")

    def test_same_bar_fvg_counts(self):
        eng = SignalEngine(_cfg())
        order = eng.on_15m_close(10, "long", _bos(), [_fvg(bar=10)],
                                 _pivots(), 2.0)
        self.assertIsNotNone(order)

    def test_bos_fvg_window_expires(self):
        eng = SignalEngine(_cfg())
        eng.on_15m_close(10, "long", _bos(), [], _pivots(), 2.0)
        for bar in (11, 12, 13):
            self.assertIsNone(
                eng.on_15m_close(bar, "long", None, [], _pivots(), 2.0))
        eng.on_15m_close(14, "long", None, [_fvg(bar=14)], _pivots(), 2.0)
        self.assertEqual(eng.state, "IDLE")

    def test_trend_mismatch_ignored(self):
        eng = SignalEngine(_cfg())
        eng.on_15m_close(10, "short", _bos(direction=1), [], _pivots(),
                         2.0)
        self.assertEqual(eng.state, "IDLE")

    def test_stop_distance_filter_skips(self):
        eng = SignalEngine(_cfg())
        eng.on_15m_close(10, "long", _bos(), [], _pivots(), 2.0)
        # 止损锚 100.5 距入场 101 仅 0.25 ATR < 0.5 → 跳过。
        eng.on_15m_close(11, "long", None, [_fvg()],
                         _pivots(px=100.5), 2.0)
        self.assertEqual(eng.state, "IDLE")
        kinds = [e.kind for e in eng.events]
        self.assertIn("skip", kinds)

    def test_order_expiry_and_single_position(self):
        eng = SignalEngine(_cfg())
        eng.on_15m_close(10, "long", _bos(), [_fvg(bar=10)], _pivots(),
                         2.0)
        # 挂单期间新的 BOS 不得开第二单。
        eng.on_15m_close(12, "long", _bos(bar=12), [], _pivots(), 2.0)
        self.assertEqual(eng.state, "ORDER_PLACED")
        for bar in range(13, 20):
            eng.on_15m_close(bar, "long", None, [], _pivots(), 2.0)
        self.assertEqual(eng.state, "IDLE")
        kinds = [e.kind for e in eng.events]
        self.assertIn("order_expired", kinds)

    def test_fill_and_close_cycle(self):
        eng = SignalEngine(_cfg())
        eng.on_15m_close(10, "long", _bos(), [_fvg(bar=10)], _pivots(),
                         2.0)
        eng.on_fill(12)
        self.assertEqual(eng.state, "POSITION")
        # 持仓期间信号全部忽略。
        eng.on_15m_close(13, "long", _bos(bar=13), [], _pivots(), 2.0)
        self.assertEqual(eng.state, "POSITION")
        eng.on_position_close(15, "target")
        self.assertEqual(eng.state, "IDLE")


if __name__ == "__main__":
    unittest.main(verbosity=1)
