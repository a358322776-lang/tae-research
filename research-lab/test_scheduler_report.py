"""调度器与周报模板测试：默认关闭、重试耗尽、七节齐全。"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scheduler import (REQUIRED_SECTIONS, Scheduler, Task,
                       build_weekly_report, collect_safety_gates)

HERE = Path(__file__).resolve().parent


class SchedulerTest(unittest.TestCase):
    def test_default_disabled_runs_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            sched = Scheduler(tmp)
            self.assertFalse(sched.enabled)
            sched.submit(Task(task_id="T1", kind="probe"))
            calls = []
            res = sched.tick(lambda t: (calls.append(t.task_id), True, {}, None)[1:])
            self.assertEqual(res, {"enabled": False, "ran": 0,
                                   "succeeded": 0, "failed": 0})
            self.assertEqual(calls, [])
            self.assertEqual(sched.tasks["T1"].status, "PENDING")
            # 日志只有 submitted 一行（未启用不产生分派记录）。
            lines = Path(tmp, "scheduler-log.jsonl").read_text().strip().splitlines()
            self.assertEqual(len(lines), 1)

    def test_retry_exhaustion_then_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            sched = Scheduler(tmp)
            sched.enable(by="test")
            sched.submit(Task(task_id="T1", kind="probe", max_retries=2))
            handler = lambda t: (False, {}, "boom")  # noqa: E731
            sched.tick(handler)
            self.assertEqual(sched.tasks["T1"].status, "PENDING")
            self.assertEqual(sched.tasks["T1"].attempts, 1)
            sched.tick(handler)
            self.assertEqual(sched.tasks["T1"].status, "PENDING")
            sched.tick(handler)
            self.assertEqual(sched.tasks["T1"].status, "FAILED")
            self.assertEqual(sched.tasks["T1"].attempts, 3)
            # 终态后不再分派。
            res = sched.tick(handler)
            self.assertEqual(res["ran"], 0)

    def test_success_and_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sched = Scheduler(tmp)
            sched.enable(by="test")
            sched.submit(Task(task_id="T1", kind="probe"))
            res = sched.tick(lambda t: (True, {"wall_s": 1.2}, None))
            self.assertEqual(res["succeeded"], 1)
            self.assertEqual(sched.tasks["T1"].status, "SUCCEEDED")
            with self.assertRaises(ValueError):
                sched.submit(Task(task_id="T1", kind="probe"))
            summary = sched.summary()
            self.assertEqual(summary["by_status"], {"SUCCEEDED": 1})
            self.assertEqual(summary["failures"], [])

    def test_no_cron_or_executor_code(self):
        # AST 级检查（注释/文档字符串中的提及不算）：不得导入执行器、
        # 线程、子进程、APScheduler，不得调用 Popen/系统命令。
        import ast
        tree = ast.parse((HERE / "scheduler.py").read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        for banned in ("apscheduler", "subprocess", "threading",
                       "multiprocessing", "os", "socket"):
            self.assertNotIn(banned, imports,
                             f"scheduler must not import {banned}")
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertNotIn("Popen", names)


class WeeklyReportTest(unittest.TestCase):
    def test_all_seven_sections_present(self):
        gates = collect_safety_gates(
            standards_path=HERE / "validation-standards-v1.json",
            hash_path=HERE / "validation-standards-v1.sha256",
            c5_path=HERE.parent / "tae-b1" / "screening-2"
            / "c5-exploratory-backtest.py",
            live_ok_path=HERE.parent / ".live-ok",
            scheduler_enabled=False)
        report = build_weekly_report(
            week_label="2026-W45",
            tasks_summary={"total": 0, "by_status": {}, "enabled": False,
                           "failures": []},
            registry_summary={"hypotheses": 0, "experiments": 0},
            data_quality_issues=[],
            resource_usage={"cpu_seconds": 0},
            safety_gates=gates,
            pending_approvals=["Stage 2 试运行申请（未批）"])
        for section in REQUIRED_SECTIONS:
            self.assertIn(section, report)
        self.assertIn("DRAFT", report)
        self.assertIn("SEALED_OK", report)
        self.assertIn("CLOSED", report)

    def test_failures_listed(self):
        report = build_weekly_report(
            week_label="2026-W45",
            tasks_summary={"total": 1, "by_status": {"FAILED": 1},
                           "enabled": True,
                           "failures": [{"task_id": "T9", "kind": "probe",
                                         "attempts": 3, "error": "boom"}]},
            registry_summary={}, data_quality_issues=["快照缺口 1 处"],
            resource_usage={}, safety_gates={},
            pending_approvals=[])
        self.assertIn("T9", report)
        self.assertIn("boom", report)
        self.assertIn("快照缺口", report)


if __name__ == "__main__":
    unittest.main(verbosity=1)
