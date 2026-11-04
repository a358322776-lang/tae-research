"""登记模块测试（标准库 unittest，无外部依赖）。

覆盖实施方案 §6 / §8 G1 的关键门禁：
- 每轮第 4 个假设被拒绝；
- 每周第 21 次正式实验被拒绝；
- SCREEN 总分 < 6 或实质区别为 0 被拒绝；
- 指纹完全重复被拒绝；
- attempts / knowledge / audit_log 的 UPDATE 与 DELETE 被触发器拒绝。
运行：python3 -m unittest discover -s research-lab -p "test_registry.py" -v
（须在仓库根目录运行；测试只用临时库，不碰生产登记库。）
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import registry
from registry import (
    DuplicateError,
    RegistryError,
    RegistryLimitError,
    add_knowledge,
    audit,
    ensure_round,
    fingerprint,
    init_db,
    log_attempt,
    register_experiment,
    register_hypothesis,
    round_counts,
    screen_score,
)

ROUND = "ROUND-2026-W45"
SCORES = {
    "economic_logic": 2,
    "data_available": 1,
    "cost_estimable": 1,
    "complexity_ok": 1,
    "substantive_difference": 1,
}


def _hyp_kwargs(i: int) -> dict:
    return {
        "hypothesis_id": f"HYP-20261104-{i:02d}",
        "round_id": ROUND,
        "title": f"drill hypothesis {i}",
        "mechanism": f"drill-mechanism-{i}",
        "distinction_statement": "differs from archived failures in mechanism and data",
        "fp": fingerprint(f"drill-mechanism-{i}", "ETHUSDT", "1h",
                          f"entry{i}", f"exit{i}", "cost-v1"),
        "screen_scores": dict(SCORES),
    }


class TestCounters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = init_db(Path(self.tmp.name) / "drill.sqlite")
        ensure_round(self.conn, ROUND, "2026-11-02")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_fourth_hypothesis_rejected(self):
        for i in (1, 2, 3):
            register_hypothesis(self.conn, **_hyp_kwargs(i))
        with self.assertRaises(RegistryLimitError):
            register_hypothesis(self.conn, **_hyp_kwargs(4))
        self.assertEqual(round_counts(self.conn, ROUND)["hypotheses"], 3)

    def test_twenty_first_experiment_rejected(self):
        register_hypothesis(self.conn, **_hyp_kwargs(1))
        for i in range(1, 21):
            register_experiment(
                self.conn, experiment_id=f"EXP-20261104-{i:03d}",
                hypothesis_id="HYP-20261104-01", round_id=ROUND,
                spec_hash=f"spec{i}", snapshot_id="SNAP-DRILL",
                cost_model_version="cost-v1", seed=1)
        with self.assertRaises(RegistryLimitError):
            register_experiment(
                self.conn, experiment_id="EXP-20261104-021",
                hypothesis_id="HYP-20261104-01", round_id=ROUND,
                spec_hash="spec21", snapshot_id="SNAP-DRILL",
                cost_model_version="cost-v1", seed=1)
        self.assertEqual(round_counts(self.conn, ROUND)["experiments"], 20)

    def test_screen_threshold(self):
        self.assertEqual(screen_score(SCORES), 6)
        low = dict(SCORES, economic_logic=1)
        with self.assertRaises(RegistryError):
            screen_score(low)
        zero_diff = dict(SCORES, substantive_difference=0,
                         economic_logic=2, data_available=2,
                         cost_estimable=2, complexity_ok=2)
        with self.assertRaises(RegistryError):
            screen_score(zero_diff)

    def test_duplicate_fingerprint_rejected(self):
        register_hypothesis(self.conn, **_hyp_kwargs(1))
        dup = _hyp_kwargs(2)
        dup["mechanism"] = "drill-mechanism-1"
        dup["fp"] = _hyp_kwargs(1)["fp"]
        with self.assertRaises(DuplicateError):
            register_hypothesis(self.conn, **dup)


class TestAppendOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = init_db(Path(self.tmp.name) / "drill.sqlite")
        ensure_round(self.conn, ROUND, "2026-11-02")
        register_hypothesis(self.conn, **_hyp_kwargs(1))
        register_experiment(
            self.conn, experiment_id="EXP-20261104-001",
            hypothesis_id="HYP-20261104-01", round_id=ROUND,
            spec_hash="spec1", snapshot_id="SNAP-DRILL",
            cost_model_version="cost-v1", seed=1)
        self.aid = log_attempt(self.conn, experiment_id="EXP-20261104-001",
                               kind="formal", mean_net_R=-0.1, n_trades=10)
        add_knowledge(self.conn, knowledge_id="KNOW-20261104-001",
                      kind="failure_pattern", conclusion="drill",
                      evidence_refs="EXP-20261104-001", confidence="low")
        audit(self.conn, actor="drill", action="test", result="ok")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_attempts_cannot_be_updated_or_deleted(self):
        with self.assertRaises(Exception):
            self.conn.execute("UPDATE attempts SET mean_net_R = 1.0 WHERE attempt_id = ?",
                              (self.aid,))
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM attempts WHERE attempt_id = ?", (self.aid,))

    def test_knowledge_and_audit_cannot_be_deleted(self):
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM knowledge")
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM audit_log")


if __name__ == "__main__":
    unittest.main()
