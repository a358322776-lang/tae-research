"""统一成本函数测试（A1）。全部合成数据（字面量），不导入、不调用
任何回测引擎，不读历史收益记录。已知答案来自上一轮引擎验证中
已手算核对的数值（B1 -1.0845R；C5 central 腿净区间），此处仅
验证成本函数本身复现这些数——引擎代码零触碰。
"""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cost_model import (CostSpec, CostSpecsTampered, apply_costs,
                        fill_price, funding_exact_sum,
                        funding_prefix_interval, load_sealed_cost_specs)

HERE = Path(__file__).resolve().parent


def _specs():
    return load_sealed_cost_specs(HERE / "cost-specs-v1.json",
                                  HERE / "cost-specs-v1.sha256")


def _zero_spec():
    return CostSpec(name="zero", fee_per_side=0.0, fee_mode="fixed",
                    fee_fixed_pct=0.0, slip_entry=0.0, spread_entry=0.0,
                    slip_exit=0.0, spread_exit=0.0,
                    exit_cost_applies_to="all", funding_mode="exact",
                    source="test-only")


class FillSeparationTest(unittest.TestCase):
    def test_fill_applied_once(self):
        spec = CostSpec(name="t", fee_per_side=0.01, fee_mode="fixed",
                        fee_fixed_pct=0.0, slip_entry=0.0008,
                        spread_entry=0.0003, slip_exit=0.0008,
                        spread_exit=0.0003, exit_cost_applies_to="all",
                        funding_mode="exact", source="test")
        # 滑点+价差一次加总：1.0011；手续费不进成交价（fee 改 0.01
        # 与改 0.0 的成交价相同）。
        self.assertAlmostEqual(
            fill_price(2400.0, 1, "entry", spec), 2400.0 * 1.0011)
        self.assertAlmostEqual(
            fill_price(2400.0, -1, "entry", spec), 2400.0 * 0.9989)
        self.assertAlmostEqual(
            fill_price(2352.0, 1, "exit", spec), 2352.0 * 0.9989)
        spec2 = CostSpec(**{**spec.__dict__, "fee_per_side": 0.0})
        self.assertEqual(fill_price(2400.0, 1, "entry", spec),
                         fill_price(2400.0, 1, "entry", spec2))

    def test_theoretical_untouched_by_slip(self):
        specs = _specs()
        recs = [(8, 0.0001), (16, 0.0001)]
        a = apply_costs(2400.0, 2420.0, 1, spec=specs["c5-central"],
                        exit_kind="close", funding_records=recs,
                        t0_ms=0, t1_ms=24 * 3600000)
        zero = apply_costs(2400.0, 2420.0, 1, spec=_zero_spec(),
                           exit_kind="close", funding_records=recs,
                           t0_ms=0, t1_ms=24 * 3600000)
        # 理论毛收益与滑点无关；滑点只改变成交毛收益与 slip_cost。
        self.assertEqual(a.gross_theoretical_pct,
                         zero.gross_theoretical_pct)
        self.assertGreater(a.slip_cost_pct, 0)
        self.assertAlmostEqual(a.slip_cost_pct,
                               a.gross_theoretical_pct - a.gross_fill_pct)

    def test_stop_only_slip(self):
        spec = _specs()["b1"]
        self.assertEqual(fill_price(2352.0, 1, "exit", spec, "close"),
                         2352.0)
        self.assertAlmostEqual(
            fill_price(2352.0, 1, "exit", spec, "stop"),
            2352.0 * 0.9995)


class GoldenTest(unittest.TestCase):
    def test_b1_known_trade(self):
        # B1 已知交易：入场 2400，止损 2352，risk 0.02，资金费两笔。
        recs = [(8 * 3600000, 0.0001), (16 * 3600000, 0.0001)]
        out = apply_costs(2400.0, 2352.0, 1, spec=_specs()["b1"],
                          exit_kind="stop", funding_records=recs,
                          t0_ms=0, t1_ms=24 * 3600000,
                          stop_distance_pct=0.02)
        self.assertAlmostEqual(out.fill_entry_px, 2400.0)
        self.assertAlmostEqual(out.fill_exit_px, 2350.824)
        self.assertAlmostEqual(out.slip_cost_pct, 0.00049)
        self.assertAlmostEqual(out.fee_pct, 0.001)
        self.assertAlmostEqual(out.funding_pct, 0.0002)
        self.assertAlmostEqual(out.net_pct, -0.02169, places=12)
        self.assertAlmostEqual(out.net_r, -1.0845, places=10)
        # 恒等式：net = gross_fill - fee - funding。
        self.assertAlmostEqual(
            out.net_pct, out.gross_fill_pct - out.fee_pct - out.funding_pct)

    def test_b1_known_trade_short(self):
        recs = [(8 * 3600000, 0.0001), (16 * 3600000, 0.0001)]
        out = apply_costs(2400.0, 2448.0, -1, spec=_specs()["b1"],
                          exit_kind="stop", funding_records=recs,
                          t0_ms=0, t1_ms=24 * 3600000,
                          stop_distance_pct=0.02)
        self.assertAlmostEqual(out.fill_exit_px, 2449.224)
        self.assertAlmostEqual(out.net_r, -1.0855, places=10)

    def test_c5_central_leg_interval(self):
        # C5 central 腿：入场开盘 2400，止损 2353.8816（按成交入场价
        # 2401.92 的 2%），资金费触发日前缀区间 (0.0003, 0.0005)。
        recs = [(h * 3600000, 0.0001) for h in range(8, 49, 8)]
        out = apply_costs(2400.0, 2353.8816, 1, spec=_specs()["c5-central"],
                          exit_kind="stop", funding_records=recs,
                          t0_ms=0, t1_ms=48 * 3600000,
                          funding_anchor_ms=24 * 3600000)
        self.assertAlmostEqual(out.fill_entry_px, 2401.92)
        self.assertAlmostEqual(out.fill_exit_px, 2351.99849472)
        self.assertAlmostEqual(out.gross_fill_pct, -0.020784, places=10)
        self.assertAlmostEqual(out.funding_lo, 0.0003)
        self.assertAlmostEqual(out.funding_hi, 0.0005)
        self.assertAlmostEqual(out.net_lo, -0.022284, places=10)
        self.assertAlmostEqual(out.net_hi, -0.022084, places=10)

    def test_zero_cost_identity(self):
        recs = [(8 * 3600000, 0.0001)]
        out = apply_costs(2400.0, 2420.0, 1, spec=_zero_spec(),
                          exit_kind="close", funding_records=recs,
                          t0_ms=0, t1_ms=24 * 3600000)
        # 零成本规格下：成交价 == 理论价，净 == 理论毛收益 - 资金费。
        self.assertEqual(out.fill_entry_px, 2400.0)
        self.assertEqual(out.fill_exit_px, 2420.0)
        self.assertEqual(out.slip_cost_pct, 0.0)
        self.assertEqual(out.fee_pct, 0.0)

    def test_reproducible(self):
        spec = _specs()["c5-central"]
        recs = [(8 * 3600000, 0.0001)]
        kw = dict(spec=spec, exit_kind="close", funding_records=recs,
                  t0_ms=0, t1_ms=24 * 3600000)
        self.assertEqual(apply_costs(2400.0, 2420.0, 1, **kw),
                         apply_costs(2400.0, 2420.0, 1, **kw))


class FundingTest(unittest.TestCase):
    def test_window_half_open(self):
        recs = [(0, 0.001), (10, 0.0001), (20, 0.0001), (30, 0.001)]
        # (0, 20] 含 10、20，不含 0；含 30 则越界。
        self.assertAlmostEqual(funding_exact_sum(recs, 0, 20), 0.0002)
        self.assertAlmostEqual(funding_exact_sum(recs, 0, 30), 0.0012)

    def test_gap_refuses(self):
        recs = [(8 * 3600000, 0.0001), (40 * 3600000, 0.0001)]
        out = apply_costs(2400.0, 2420.0, 1, spec=_specs()["b1"],
                          exit_kind="close", funding_records=recs,
                          t0_ms=0, t1_ms=48 * 3600000)
        self.assertEqual(out.funding_status, "coverage_gap")
        self.assertIsNone(out.net_pct)

    def test_prefix_interval(self):
        recs = [(24, 0.0001), (32, 0.0001), (40, 0.0001), (48, -0.0005)]
        # 上界结算点按 C5 约定排除（t < upper）；取 upper=56 含入 48 点。
        lo, hi = funding_prefix_interval(recs, 0, 24, 56)
        self.assertAlmostEqual(lo, -0.0002)
        self.assertAlmostEqual(hi, 0.0003)


class SealedSpecsTest(unittest.TestCase):
    def test_specs_load_and_match_audit(self):
        specs = _specs()
        self.assertEqual(set(specs), {"b1", "c5-low", "c5-central", "c5-high"})
        self.assertEqual(specs["b1"].fee_per_side, 0.0005)
        self.assertEqual(specs["c5-central"].slip_entry, 0.0008)
        self.assertEqual(specs["c5-high"].slip_entry, 0.002)
        self.assertEqual(specs["c5-low"].slip_entry, 0.00035)

    def test_tamper_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = HERE / "cost-specs-v1.json"
            copy = Path(tmp) / "specs.json"
            copy.write_bytes(src.read_bytes())
            hpath = Path(tmp) / "specs.sha256"
            hpath.write_text(hashlib.sha256(copy.read_bytes()).hexdigest())
            self.assertEqual(len(load_sealed_cost_specs(copy, hpath)), 4)
            copy.write_text(copy.read_text() + " ")
            with self.assertRaises(CostSpecsTampered):
                load_sealed_cost_specs(copy, hpath)


if __name__ == "__main__":
    unittest.main(verbosity=1)
