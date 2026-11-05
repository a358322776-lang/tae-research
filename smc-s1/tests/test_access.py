"""最终测试集隔离测试：拒绝、切片、越界、日志哈希链、篡改检出。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from access import (FinalTestBlocked, SegmentStore,  # noqa: E402
                    verify_log)

_MANIFEST = {
    "format_version": "smc-split-manifest-v1-test",
    "split_15m": {
        "train": {"start_idx": 0, "end_idx": 100},
        "validation": {"start_idx": 100, "end_idx": 140},
        "final_test": {"start_idx": 140, "end_idx": 200},
    },
}


class IsolationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "access.jsonl"
        self.store = SegmentStore(_MANIFEST, log_path=self.log,
                                  caller="test")

    def tearDown(self):
        self.tmp.cleanup()

    def test_final_test_denied_and_logged(self):
        with self.assertRaises(FinalTestBlocked):
            self.store.open_segment("final_test", "b2-backtest")
        entries = verify_log(self.log)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["segment"], "final_test")
        self.assertEqual(entries[0]["result"], "denied")
        self.assertEqual(entries[0]["manifest_version"],
                         "smc-split-manifest-v1-test")

    def test_train_validation_slices(self):
        self.assertEqual(self.store.open_segment("train", "check"),
                         (0, 100))
        self.assertEqual(
            self.store.slice_for("validation", "check", 200),
            slice(100, 140))

    def test_unknown_segment_rejected(self):
        with self.assertRaises(ValueError):
            self.store.open_segment("oos", "check")

    def test_out_of_range_slice_rejected(self):
        with self.assertRaises(ValueError):
            self.store.slice_for("train", "check", 50)

    def test_purpose_required(self):
        with self.assertRaises(ValueError):
            self.store.open_segment("train", "  ")

    def test_log_appends_and_verifies(self):
        self.store.open_segment("train", "a")
        self.store.open_segment("validation", "b")
        entries = verify_log(self.log)
        self.assertEqual(len(entries), 2)
        self.assertEqual([e["result"] for e in entries],
                         ["granted", "granted"])
        self.assertEqual(entries[1]["prev_hash"],
                         entries[0]["entry_hash"])

    def test_tamper_detected(self):
        self.store.open_segment("train", "a")
        lines = self.log.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[0])
        entry["purpose"] = "forged"
        self.log.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            verify_log(self.log)

    def test_deletion_detected(self):
        self.store.open_segment("train", "a")
        self.store.open_segment("validation", "b")
        lines = self.log.read_text(encoding="utf-8").splitlines()
        self.log.write_text(lines[1] + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            verify_log(self.log)

    def test_from_file(self):
        manifest_path = Path(self.tmp.name) / "manifest.json"
        manifest_path.write_text(json.dumps(_MANIFEST), encoding="utf-8")
        store = SegmentStore.from_file(manifest_path, log_path=self.log)
        self.assertEqual(store.open_segment("train", "x"), (0, 100))


if __name__ == "__main__":
    unittest.main(verbosity=1)
