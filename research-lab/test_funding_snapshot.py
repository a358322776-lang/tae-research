"""资金费率快照管道测试：全部合成数据，离线；取数函数用桩替换。"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import funding_snapshot as fs
from data_engine import FetchError


def good_records(symbol="ETHUSDT", start=1_700_000_000_000, n=5, rate=0.0001):
    return [{"symbol": symbol, "fundingTime": start + i * 28_800_000,
             "fundingRate": str(rate)} for i in range(n)]


class ValidateTest(unittest.TestCase):
    def test_good(self):
        r = fs.validate_funding_records(good_records(), "ETHUSDT",
                                        now_ms=1_700_200_000_000)
        self.assertTrue(r["passed"], r["issues"])
        self.assertEqual(r["n_records"], 5)
        self.assertEqual(r["missing_steps"], [])

    def test_unsorted_fails(self):
        recs = good_records()
        recs[1], recs[2] = recs[2], recs[1]
        r = fs.validate_funding_records(recs, "ETHUSDT", now_ms=1_700_200_000_000)
        self.assertFalse(r["passed"])

    def test_duplicate_fails(self):
        recs = good_records()
        recs[1] = dict(recs[0])
        r = fs.validate_funding_records(recs, "ETHUSDT", now_ms=1_700_200_000_000)
        self.assertFalse(r["passed"])

    def test_future_fails(self):
        recs = good_records()
        r = fs.validate_funding_records(recs, "ETHUSDT", now_ms=1_700_000_000_000)
        self.assertFalse(r["passed"])

    def test_wrong_symbol_fails(self):
        r = fs.validate_funding_records(good_records("BTCUSDT"), "ETHUSDT",
                                        now_ms=1_700_200_000_000)
        self.assertFalse(r["passed"])

    def test_non_numeric_rate_fails(self):
        recs = good_records()
        recs[0]["fundingRate"] = "abc"
        r = fs.validate_funding_records(recs, "ETHUSDT", now_ms=1_700_200_000_000)
        self.assertFalse(r["passed"])

    def test_gap_over_24h_fails(self):
        recs = good_records(n=3)
        recs[2]["fundingTime"] = recs[1]["fundingTime"] + 32 * 3600_000
        r = fs.validate_funding_records(recs, "ETHUSDT", now_ms=1_800_000_000_000)
        self.assertFalse(r["passed"])

    def test_gap_16h_noted_not_failed(self):
        recs = good_records(n=3)
        recs[2]["fundingTime"] = recs[1]["fundingTime"] + 16 * 3600_000
        r = fs.validate_funding_records(recs, "ETHUSDT", now_ms=1_800_000_000_000)
        self.assertTrue(r["passed"], r["issues"])
        self.assertEqual(len(r["missing_steps"]), 1)

    def test_ms_jitter_not_missing(self):
        # 镜像 fundingTime 带 0-5ms 抖动：同一 8h 网格内的抖动不得
        # 误判为缺失结算点。
        recs = good_records(n=4)
        recs[1]["fundingTime"] += 3
        recs[2]["fundingTime"] += 1
        recs[3]["fundingTime"] += 5
        r = fs.validate_funding_records(recs, "ETHUSDT", now_ms=1_800_000_000_000)
        self.assertTrue(r["passed"], r["issues"])
        self.assertEqual(r["missing_steps"], [])

    def test_empty_fails(self):
        r = fs.validate_funding_records([], "ETHUSDT")
        self.assertFalse(r["passed"])

    def test_negative_rate_ok(self):
        recs = good_records(rate=-0.0002)
        r = fs.validate_funding_records(recs, "ETHUSDT", now_ms=1_700_200_000_000)
        self.assertTrue(r["passed"], r["issues"])


class WriteVerifyTest(unittest.TestCase):
    def test_write_verify_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = fs.write_funding_snapshot(
                tmp, "FUND-20261104-001", "ETHUSDT", good_records(),
                "https://example.invalid/fundingRate", "2026-11-04T00:00:00Z",
                now_ms=1_700_200_000_000)
            snap_dir = Path(tmp) / "funding-snapshots" / "FUND-20261104-001"
            self.assertTrue(fs.verify_funding_snapshot(snap_dir)["ok"])
            for name in ("data.json", "manifest.json"):
                mode = stat.S_IMODE((snap_dir / name).stat().st_mode)
                self.assertEqual(oct(mode), "0o444")
            ledger = (Path(tmp) / "funding-ledger.jsonl").read_text()
            self.assertIn("FUND-20261104-001", ledger)
            with self.assertRaises(FileExistsError):
                fs.write_funding_snapshot(
                    tmp, "FUND-20261104-001", "ETHUSDT", good_records(),
                    "https://example.invalid/fundingRate",
                    "2026-11-04T00:00:00Z", now_ms=1_700_200_000_000)
            # 篡改后复核必须失败。
            data_path = snap_dir / "data.json"
            os.chmod(data_path, 0o644)
            data_path.write_text(data_path.read_text() + " ")
            self.assertFalse(fs.verify_funding_snapshot(snap_dir)["ok"])

    def test_refused_on_bad_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                fs.write_funding_snapshot(
                    tmp, "FUND-20261104-001", "ETHUSDT", [],
                    "https://example.invalid/fundingRate",
                    "2026-11-04T00:00:00Z")


class FetchTest(unittest.TestCase):
    def test_fetch_validates_shape_and_limit(self):
        orig = fs.fetch_json
        fs.fetch_json = lambda url, timeout=15: [{"symbol": "ETHUSDT",
                                                  "fundingTime": 1,
                                                  "fundingRate": "0.0001"}]
        try:
            self.assertEqual(len(fs.fetch_funding("ETHUSDT", limit=1)), 1)
            with self.assertRaises(FetchError):
                fs.fetch_funding("ETHUSDT", limit=0)
            with self.assertRaises(FetchError):
                fs.fetch_funding("ETHUSDT;DROP", limit=1)
        finally:
            fs.fetch_json = orig
        fs.fetch_json = lambda url, timeout=15: {"not": "a list"}
        try:
            with self.assertRaises(FetchError):
                fs.fetch_funding("ETHUSDT", limit=1)
        finally:
            fs.fetch_json = orig


if __name__ == "__main__":
    unittest.main(verbosity=1)
