"""执行接口测试：严格穿透、生效前不成交、同 bar 保守规则、1m 保留。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution import (OneMinuteBarSource, resolve_bar,  # noqa: E402
                       simulate_limit_fill)
from helpers import mk_bars  # noqa: E402


class FillTest(unittest.TestCase):
    def test_strict_penetration_long(self):
        bars = mk_bars([(101, 102, 100.5, 101), (101, 102, 100.0, 101),
                        (100, 101, 99.5, 100)])
        # low == limit 不成交；low < limit 才成交。
        fill = simulate_limit_fill(100.0, 1, bars, 0, 2)
        self.assertIsNotNone(fill)
        self.assertEqual(fill.bar_index, 2)
        self.assertEqual(fill.fill_px, 100.0)

    def test_no_fill_without_penetration(self):
        bars = mk_bars([(101, 102, 100.5, 101), (101, 102, 100.2, 101)])
        self.assertIsNone(simulate_limit_fill(100.0, 1, bars, 0, 1))

    def test_bars_before_start_never_fill(self):
        bars = mk_bars([(100, 101, 99.0, 100), (101, 102, 100.5, 101),
                        (101, 102, 100.5, 101)])
        # 第 0 根已穿透，但 start_idx=1（生效后）→ 不得回看。
        self.assertIsNone(simulate_limit_fill(100.0, 1, bars, 1, 2))

    def test_short_penetration(self):
        bars = mk_bars([(99, 100.0, 98, 99), (99, 100.5, 98, 99)])
        fill = simulate_limit_fill(100.0, -1, bars, 0, 1)
        self.assertIsNotNone(fill)
        self.assertEqual(fill.bar_index, 1)


class ResolveBarTest(unittest.TestCase):
    def test_both_hit_stop_first(self):
        bar = mk_bars([(100, 105, 97, 104)])[0]
        out = resolve_bar(1, 98.0, 104.0, bar)
        self.assertEqual(out.outcome, "both-stop-first")
        self.assertTrue(out.ambiguity)

    def test_target_only(self):
        bar = mk_bars([(100, 105, 99, 104)])[0]
        self.assertEqual(resolve_bar(1, 98.0, 104.0, bar).outcome, "target")

    def test_stop_only_short(self):
        bar = mk_bars([(100, 101, 99, 100)])[0]
        self.assertEqual(resolve_bar(-1, 101.0, 96.0, bar).outcome, "stop")


class AdapterTest(unittest.TestCase):
    def test_one_minute_adapter_reserved(self):
        with self.assertRaises(NotImplementedError):
            OneMinuteBarSource()


if __name__ == "__main__":
    unittest.main(verbosity=1)
