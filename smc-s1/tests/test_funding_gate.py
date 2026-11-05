"""资金费门禁测试：重复、网格抖动、异常值。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from funding_gate import (FundingGateError, GRID_MS,  # noqa: E402
                          check_funding_records)

HOUR = 3600000


class FundingGateTest(unittest.TestCase):
    def test_clean_records_pass(self):
        recs = [(0, 0.0001), (GRID_MS, -0.0002), (2 * GRID_MS, 0.0003)]
        summary = check_funding_records(recs)
        self.assertEqual(summary["n"], 3)
        self.assertAlmostEqual(summary["max_abs_rate"], 0.0003)

    def test_duplicate_timestamp_rejected(self):
        with self.assertRaises(FundingGateError):
            check_funding_records([(0, 0.0001), (0, 0.0002)])

    def test_jitter_within_tolerance_passes(self):
        # 已知抖动 -5ms~+47ms：网格前后 47s 内均通过。
        recs = [(GRID_MS + 47000, 0.0001), (2 * GRID_MS - 5000, 0.0001)]
        summary = check_funding_records(recs)
        self.assertEqual(summary["n"], 2)

    def test_jitter_beyond_tolerance_rejected(self):
        with self.assertRaises(FundingGateError):
            check_funding_records([(GRID_MS + 61000, 0.0001)])

    def test_anomalous_rate_rejected(self):
        with self.assertRaises(FundingGateError):
            check_funding_records([(0, 0.0101)])
        with self.assertRaises(FundingGateError):
            check_funding_records([(0, -0.02)])

    def test_boundary_rate_passes(self):
        summary = check_funding_records([(0, 0.01)])
        self.assertEqual(summary["max_abs_rate"], 0.01)

    def test_empty_records_pass_vacuously(self):
        # 空列表无可查项；覆盖缺口由统一模型判定，不由门禁越俎。
        self.assertEqual(check_funding_records([])["n"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
