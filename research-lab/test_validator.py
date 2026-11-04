"""独立验证器测试（标准库 only；C5 原始模块仅只读导入、不调用 main）。

D-ENG-1 回归与漏网证明见 test_d_eng_1_*：现有门（C5 verify + 腿函数
OLHC 元组测试）全部通过的同时，边界审计必须把缺陷揪出来——这正是
旧测试漏网的机制：门从未把“标准 OHLC 行 -> 腿函数输入”这一步放进
检查范围。
"""

import hashlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validator
from validator import (Bar, ContractError, ValidationBlocked,
                       audit_day_builder, benchmark_return,
                       check_availability, check_bars, check_benchmark,
                       check_drawdown, check_event_within_split, check_fee_r,
                       check_funding_interval, check_no_label_overlap,
                       check_reproducibility, check_split, check_stop_exit,
                       funding_exact_sum, load_sealed_standards,
                       seal_directory, static_scan, verify_sealed_directory)

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def _load_c5():
    path = REPO / "tae-b1" / "screening-2" / "c5-exploratory-backtest.py"
    spec = importlib.util.spec_from_file_location("c5_orig_for_validator", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bars_ohlc():
    # 标准 OHLC：D+2 日平收，D+3 日真 low 穿止损（high 未穿）。
    rows = [
        (2400.0, 2420.0, 2360.0, 2410.0),
        (2410.0, 2420.0, 2340.0, 2400.0),
        (2400.0, 2400.0, 2400.0, 2400.0),
        (2400.0, 2400.0, 2400.0, 2400.0),
    ]
    return [Bar.from_ohlc_row(r) for r in rows]


class BarContractTest(unittest.TestCase):
    def test_from_ohlc_row_and_leg_day(self):
        b = Bar.from_ohlc_row((2400.0, 2420.0, 2360.0, 2410.0))
        self.assertEqual(b.to_ohlc_tuple(), (2400.0, 2420.0, 2360.0, 2410.0))
        # 腿函数约定出口：(open, low, high, close)——顺序显式翻转。
        self.assertEqual(b.to_leg_day(), (2400.0, 2360.0, 2420.0, 2410.0))

    def test_from_klines_row(self):
        row = [1_700_000_000_000, 2400.0, 2420.0, 2360.0, 2410.0, 12.5,
               1_700_003_599_999, 30000.0, 42, 0, 0, 0]
        b = Bar.from_klines_row(row)
        self.assertEqual((b.open_time, b.open, b.high, b.low, b.close),
                         (1_700_000_000_000, 2400.0, 2420.0, 2360.0, 2410.0))
        self.assertEqual(b.close_time, 1_700_003_599_999)

    def test_from_dict_requires_names(self):
        b = Bar.from_dict({"open_time": 7, "open": 2400.0, "high": 2420.0,
                           "low": 2360.0, "close": 2410.0})
        self.assertEqual(b.open, 2400.0)
        with self.assertRaises(ContractError):
            Bar.from_dict({"open": 2400.0, "high": 2420.0})

    def test_invalid_bars_rejected(self):
        with self.assertRaises(ContractError):
            Bar.from_ohlc_row((2400.0, 2350.0, 2360.0, 2410.0))  # high < low
        with self.assertRaises(ContractError):
            Bar.from_ohlc_row((2400.0, 2420.0, 2450.0, 2410.0))  # low > open
        with self.assertRaises(ContractError):
            Bar.from_ohlc_row((2400.0, 2420.0, 2360.0, -5.0))
        with self.assertRaises(ContractError):
            # 5 列歧义行必须拒绝，不得静默猜测。
            Bar.from_ohlc_row((2400.0, 2420.0, 2360.0, 2410.0, 100.0))

    def test_check_bars(self):
        bars = [Bar(open_time=i * 900_000, open=100.0, high=101.0,
                    low=99.0, close=100.0) for i in range(4)]
        self.assertTrue(check_bars(bars, step_ms=900_000)["passed"])
        bad = bars[:2] + [bars[1]]
        self.assertFalse(check_bars(bad, step_ms=900_000)["passed"])
        gapped = [bars[0], bars[2]]
        self.assertFalse(check_bars(gapped, step_ms=900_000)["passed"])
        self.assertFalse(
            check_bars(bars, cutoff_ms=900_000)["passed"])


class SplitAndTimingTest(unittest.TestCase):
    def test_split_ok_and_overlap(self):
        self.assertTrue(check_split((0, 100), (100, 200), (200, 300))["passed"])
        self.assertFalse(check_split((0, 150), (100, 200), (200, 300))["passed"])
        self.assertFalse(check_split((0, 100), (200, 150), (200, 300))["passed"])

    def test_event_straddle(self):
        self.assertTrue(check_event_within_split(110, 190, (100, 200))["passed"])
        self.assertFalse(check_event_within_split(190, 210, (100, 200))["passed"])

    def test_availability(self):
        self.assertTrue(check_availability(1000, 1000, 900)["passed"])
        self.assertFalse(check_availability(1000, 999, 900)["passed"])
        self.assertFalse(check_availability(1000, 1000, 1001)["passed"])

    def test_label_overlap(self):
        self.assertTrue(check_no_label_overlap(1000, 1000)["passed"])
        self.assertFalse(check_no_label_overlap(1000, 999)["passed"])

    def test_static_scan_advisory(self):
        src = "x = a[i + 1]\ny = close.shift(-1)\n"
        res = static_scan(src)
        self.assertEqual(len(res["findings"]), 2)
        self.assertTrue(res["passed"])  # 扫描只提示，永不单独定罪
        self.assertEqual(static_scan("x = a[i]\n")["findings"], [])


class CostFundingTest(unittest.TestCase):
    def test_stop_exit_and_fee(self):
        self.assertTrue(check_stop_exit(2352.0, 1, 2350.824, 0.0005)["passed"])
        self.assertTrue(check_stop_exit(2448.0, -1, 2449.224, 0.0005)["passed"])
        self.assertFalse(check_stop_exit(2352.0, 1, 2352.0, 0.0005)["passed"])
        self.assertTrue(check_fee_r(0.05, 0.02, 0.0005)["passed"])
        self.assertTrue(check_fee_r(0.1, 0.01, 0.0005)["passed"])
        self.assertFalse(check_fee_r(0.06, 0.02, 0.0005)["passed"])

    def test_funding_window_and_interval(self):
        recs = [(8, 0.0001), (16, 0.0001), (24, 0.0001), (32, -0.0005),
                (40, 0.0001)]
        self.assertAlmostEqual(funding_exact_sum(recs, 0, 40), -0.0001, places=12)
        # 前缀：0.0001, 0.0002, 0.0003, -0.0002, -0.0001 -> 区间须含 [-0.0002, 0.0003]。
        self.assertTrue(check_funding_interval(recs, 0, 40, -0.0002, 0.0003)["passed"])
        self.assertFalse(check_funding_interval(recs, 0, 40, 0.0, 0.0003)["passed"])
        self.assertFalse(check_funding_interval(recs, 0, 40, -0.0002, 0.0002)["passed"])

    def test_drawdown(self):
        self.assertTrue(check_drawdown([1.0, 1.1, 0.95, 1.05], 0.15)["passed"])
        self.assertFalse(check_drawdown([1.0, 1.1, 0.95, 1.05], 0.10)["passed"])


class BenchmarkReproTest(unittest.TestCase):
    def test_benchmark_and_repro(self):
        self.assertAlmostEqual(benchmark_return([100.0, 110.0]), 0.10)
        self.assertTrue(check_benchmark([100.0, 110.0], 0.10)["passed"])
        self.assertFalse(check_benchmark([100.0, 110.0], 0.09)["passed"])
        self.assertTrue(check_reproducibility(lambda: 42)["passed"])
        state = {"n": 0}

        def counting():
            state["n"] += 1
            return state["n"]

        self.assertFalse(check_reproducibility(counting)["passed"])


class SealedTest(unittest.TestCase):
    def test_standards_tamper_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            std = HERE / "validation-standards-v1.json"
            copy = Path(tmp) / "std.json"
            copy.write_bytes(std.read_bytes())
            hpath = Path(tmp) / "std.sha256"
            hpath.write_text(hashlib.sha256(copy.read_bytes()).hexdigest())
            self.assertIsInstance(
                load_sealed_standards(copy, hpath), dict)
            copy.write_text(copy.read_text() + " ")
            with self.assertRaises(ValidationBlocked):
                load_sealed_standards(copy, hpath)

    def test_vault_detects_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "testset"
            root.mkdir()
            (root / "a.csv").write_text("x\n")
            manifest = Path(tmp) / "manifest.json"
            seal_directory(root, manifest)
            self.assertTrue(verify_sealed_directory(root, manifest)["passed"])
            (root / "a.csv").write_text("y\n")
            res = verify_sealed_directory(root, manifest)
            self.assertFalse(res["passed"])
            self.assertEqual(res["changed"], ["a.csv"])
            (root / "b.csv").write_text("z\n")
            res = verify_sealed_directory(root, manifest)
            self.assertEqual(res["added"], ["b.csv"])


class DEng1RegressionTest(unittest.TestCase):
    def test_audit_day_builder_flags_raw_passthrough(self):
        bars = _bars_ohlc()

        def raw_passthrough(bs):
            return [b.to_ohlc_tuple() for b in bs]

        def fixed_builder(bs):
            return [b.to_leg_day() for b in bs]

        bad = audit_day_builder(raw_passthrough, bars)
        self.assertFalse(bad["passed"])
        self.assertIn("field-order mismatch", bad["findings"][0])
        good = audit_day_builder(fixed_builder, bars)
        self.assertTrue(good["passed"], good["findings"])

    def test_why_existing_tests_missed_d_eng_1(self):
        """漏网机制证明：旧门全过，边界审计失败。

        C5 verify()（33 项 e2e + 资金费边界）只用 (open, low, high,
        close) 元组直接调用腿函数，从不经过“OHLC 行 -> 腿输入”的
        边界；腿函数本身按其约定是正确的。缺陷只活在 run_tier 把
        OHLC 行原样传给腿函数的那一步——旧测试从未覆盖这一步。
        """
        c5 = _load_c5()
        self.assertFalse(c5.EXECUTION_APPROVED)
        # 1) 旧门通过（腿函数按自身约定正确）。
        self.assertTrue(c5.verify())
        # 2) 边界审计失败：原始 run_tier 路径（OHLC 行原样传入）下，
        #    真 low 穿止损的腿被判 close，而契约转换判 stop。
        bars = _bars_ohlc()
        days_raw = [b.to_ohlc_tuple() for b in bars]
        got_raw = c5.run_leg_prices(1, 2400.0, days_raw,
                                    c5.TIERS["central"]["exec"])
        days_fixed = [b.to_leg_day() for b in bars]
        got_fixed = c5.run_leg_prices(1, 2400.0, days_fixed,
                                      c5.TIERS["central"]["exec"])
        self.assertEqual(got_raw[0], "close")
        self.assertEqual(got_fixed[0], "stop")
        audit = audit_day_builder(
            lambda bs: [b.to_ohlc_tuple() for b in bs], bars)
        self.assertFalse(audit["passed"])
        # 3) 结论：verify() 通过 + 边界审计失败同时成立 = 门盲区得证。
        self.assertTrue(True, "gate blindness demonstrated")


if __name__ == "__main__":
    unittest.main(verbosity=1)
