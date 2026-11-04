"""指标/评估门/切分测试：已知答案、D5 阈值、哈希清单（合成数据）。"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from metrics import evaluation_gate, lag1_autocorr, trade_stats  # noqa: E402
from splits import build_split_manifest, compute_split  # noqa: E402


class MetricsTest(unittest.TestCase):
    def test_known_series(self):
        stats = trade_stats([1.0, -1.0, 2.0, -0.5])
        self.assertEqual(stats["n"], 4)
        self.assertAlmostEqual(stats["win_rate"], 0.5)
        self.assertAlmostEqual(stats["mean_net_r"], 0.375)
        self.assertAlmostEqual(stats["profit_factor"], 2.0)
        self.assertAlmostEqual(stats["max_drawdown_r"], 1.0)
        self.assertIsNotNone(stats["ci95"])

    def test_empty_series(self):
        self.assertEqual(trade_stats([])["n"], 0)

    def test_lag1(self):
        self.assertIsNone(lag1_autocorr([1.0, 1.0]))
        ac = lag1_autocorr([1.0, 2.0, 1.0, 2.0, 1.0])
        self.assertIsNotNone(ac)
        self.assertLess(ac, 0)  # 交替序列负自相关


class GateTest(unittest.TestCase):
    def test_d5_thresholds(self):
        self.assertEqual(evaluation_gate(99, "train")["status"],
                         "insufficient")
        self.assertEqual(evaluation_gate(99, "train")["verdict"],
                         "INCONCLUSIVE")
        self.assertEqual(evaluation_gate(150, "train")["status"],
                         "exploration-only")
        self.assertEqual(evaluation_gate(200, "train")["status"], "formal")

    def test_final_test_blocked(self):
        gate = evaluation_gate(500, "final_test")
        self.assertEqual(gate["status"], "blocked")


class SplitTest(unittest.TestCase):
    def test_boundaries(self):
        ts = list(range(0, 1000))
        sp = compute_split(ts)
        self.assertEqual((sp["train"]["end_idx"],
                          sp["validation"]["end_idx"],
                          sp["final_test"]["end_idx"]), (500, 700, 1000))
        self.assertEqual(sp["train"]["start_ms"], 0)
        self.assertEqual(sp["final_test"]["start_ms"], 700)

    def test_non_increasing_rejected(self):
        with self.assertRaises(ValueError):
            compute_split([0, 5, 5, 9])

    def test_manifest_from_synthetic_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            np.savez(d / "stitched_15m.npz",
                     t=np.arange(0, 1000 * 900000, 900000, dtype=np.int64),
                     ohlc=np.zeros((1000, 4)))
            np.savez(d / "stitched_5m.npz",
                     t=np.arange(0, 3000 * 300000, 300000, dtype=np.int64),
                     ohlc=np.zeros((3000, 4)))
            np.savez(d / "stitched_1h.npz",
                     t=np.arange(0, 250 * 3600000, 3600000, dtype=np.int64),
                     ohlc=np.zeros((250, 4)))
            with open(d / "stitched_funding.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["fundingTime", "fundingRate"])
                w.writerow(["1577836800000", "0.0001"])
            manifest = build_split_manifest(d, d / "manifest.json")
            self.assertFalse(manifest["performance_computed"])
            self.assertEqual(manifest["split_15m"]["n_bars"], 1000)
            self.assertEqual(len(manifest["files"]["stitched_15m.npz"]["sha256"]), 64)
            self.assertTrue((d / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=1)
