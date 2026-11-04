"""回测骨架测试：段位守卫 + 合成数据信号因果（单 TF 驱动）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest import BacktestEngine, SegmentBlocked  # noqa: E402
from config import SMCConfig  # noqa: E402
from helpers import mk_bars  # noqa: E402


def _scenario_bars():
    # 与手算一致的 13 根 15m bar：BOS @11、FVG @12、趋势 long。
    spec = [
        (99, 100, 98, 99), (100, 101, 99, 100),
        (102, 103, 100, 102), (100, 101, 99, 100),
        (98, 100, 97, 98), (98, 102, 98, 101),
        (101, 104, 99, 103), (103, 106, 100, 105),
        (103, 104, 100, 101), (101, 102, 99, 100),
        (100, 105, 100, 104), (104, 108, 102, 107),
        (107, 109, 106.5, 108),
    ]
    return mk_bars(spec)


class SkeletonTest(unittest.TestCase):
    def test_final_test_blocked(self):
        eng = BacktestEngine(SMCConfig(atr_period=3))
        with self.assertRaises(SegmentBlocked):
            eng.run_synthetic(_scenario_bars(), "final_test")

    def test_synthetic_signal_causality(self):
        eng = BacktestEngine(SMCConfig(atr_period=3))
        out = eng.run_synthetic(
            _scenario_bars(), "synthetic",
            opposite_swing_fn=lambda i, d: 99.0)
        self.assertEqual(len(out["orders"]), 1)
        order = out["orders"][0]
        self.assertAlmostEqual(order.limit_px, 105.75)
        self.assertEqual(order.stop_px, 99.0)
        self.assertEqual(order.status, "pending")
        kinds = [e.kind for e in out["events"]]
        self.assertIn("bos", kinds)
        self.assertIn("order", kinds)
        self.assertEqual(out["trades"], [])

    def test_no_order_without_bos(self):
        bars = mk_bars([(100, 101, 99, 100)] * 20)
        eng = BacktestEngine(SMCConfig(atr_period=3))
        out = eng.run_synthetic(bars, "synthetic",
                                opposite_swing_fn=lambda i, d: 99.0)
        self.assertEqual(out["orders"], [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
