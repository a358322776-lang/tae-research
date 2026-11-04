"""风险计算与成本适配测试：止损过滤、R 换算、恒等式、假设标记。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cost_model import price_trade  # noqa: E402
from risk import compute_stop_target, position_qty  # noqa: E402

HOUR = 3600000


class RiskTest(unittest.TestCase):
    def test_stop_target_math(self):
        st, reason = compute_stop_target(1, 101.0, 98.0, 2.0, 0.5, 3.0, 2.0)
        self.assertEqual(reason, "")
        self.assertEqual((st.stop_px, st.target_px), (98.0, 107.0))
        self.assertAlmostEqual(st.stop_distance_atr, 1.5)

    def test_stop_filter(self):
        st, reason = compute_stop_target(1, 101.0, 100.5, 2.0, 0.5, 3.0, 2.0)
        self.assertIsNone(st)
        self.assertEqual(reason, "stop-too-close")
        st, reason = compute_stop_target(1, 101.0, 94.0, 2.0, 0.5, 3.0, 2.0)
        self.assertIsNone(st)
        self.assertEqual(reason, "stop-too-far")

    def test_position_qty(self):
        self.assertAlmostEqual(position_qty(2.0, 101.0, 98.0), 2.0 / 3.0)


class CostAdapterTest(unittest.TestCase):
    def test_golden_trade_identity(self):
        # 手算：入场 2400（maker 0.0002），止损出场 2352（taker
        # 0.0004），资金费 0.0002，止损距 0.02。
        # fee = 0.0002 + 0.0004*2352/2400 = 0.000592；
        # net = -0.02 - 0.000592 - 0.0002 = -0.020792 → -1.0396R。
        recs = [(8 * HOUR, 0.0001), (16 * HOUR, 0.0001)]
        out = price_trade(2400.0, 2352.0, 1, entry_fill_type="maker",
                          exit_fill_type="taker", entry_fee_rate=0.0002,
                          exit_fee_rate=0.0004,
                          fee_source="test-fixture-only",
                          funding_records=recs, t0_ms=0,
                          t1_ms=24 * HOUR, stop_distance_pct=0.02)
        self.assertAlmostEqual(out.fee_pct, 0.000592)
        self.assertAlmostEqual(out.funding_pct, 0.0002)
        self.assertAlmostEqual(out.net_r, -1.0396, places=10)
        self.assertAlmostEqual(
            out.net_pct, out.gross_pct - out.fee_pct - out.funding_pct)
        self.assertIn("proxy-fill-5m", out.assumptions)
        self.assertIn("slip/spread assumed 0", out.assumptions[1])

    def test_fee_source_required(self):
        with self.assertRaises(ValueError):
            price_trade(2400.0, 2420.0, 1, entry_fill_type="maker",
                        exit_fill_type="maker", entry_fee_rate=0.0002,
                        exit_fee_rate=0.0002, fee_source="",
                        funding_records=[], t0_ms=0, t1_ms=24 * HOUR,
                        stop_distance_pct=0.02)

    def test_funding_gap_refuses_net(self):
        recs = [(8 * HOUR, 0.0001), (40 * HOUR, 0.0001)]
        out = price_trade(2400.0, 2420.0, 1, entry_fill_type="maker",
                          exit_fill_type="maker", entry_fee_rate=0.0002,
                          exit_fee_rate=0.0002,
                          fee_source="test-fixture-only",
                          funding_records=recs, t0_ms=0,
                          t1_ms=48 * HOUR, stop_distance_pct=0.02)
        self.assertEqual(out.funding_status, "coverage_gap")
        self.assertIsNone(out.net_r)

    def test_missing_funding_unknown(self):
        out = price_trade(2400.0, 2420.0, 1, entry_fill_type="maker",
                          exit_fill_type="maker", entry_fee_rate=0.0002,
                          exit_fee_rate=0.0002,
                          fee_source="test-fixture-only",
                          funding_records=None, t0_ms=0,
                          t1_ms=24 * HOUR, stop_distance_pct=0.02)
        self.assertEqual(out.funding_status, "unknown")
        self.assertIsNone(out.net_r)


if __name__ == "__main__":
    unittest.main(verbosity=1)
