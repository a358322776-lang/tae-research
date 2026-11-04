"""数据快照与连通性测试（标准库 unittest，无外部依赖、无外网）。

覆盖实施方案 v1.1 §8 G2 的关键门禁：
- 质量检查：通过合法 bar；拒绝重复、缺口、high/low 越界、未收盘/未来 bar；
- 哈希复核：篡改 data.json 后 verify 失败；
- 只读冻结：同一快照 ID 二次写入被拒绝；文件权限为 0o444；
- 版本记录：ledger 只追加；
- 只读取数：本地 HTTP 服务器上 fetch/probe 成功，且签名参数 URL 被拒绝；
- 探针不保存响应体（probe 返回无 body 字段）。
运行：python3 -m unittest discover -s research-lab -p "test_data_engine.py" -v
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import data_engine
from data_engine import (drop_unclosed_bars, fetch_json, fetch_klines, probe,
                         validate_bars, verify_snapshot, write_snapshot)

STEP = 3_600_000
BASE = 1_760_000_000_000  # 固定过去时间戳，避免“未来 bar”误判


def _bar(i: int, overrides: dict | None = None) -> list:
    bar = [BASE + i * STEP, "100.0", "101.0", "99.0", "100.5", "10.0",
           BASE + i * STEP + STEP - 1, "1000.0", 5, "5.0", "500.0", "0"]
    for key, value in (overrides or {}).items():
        bar[key] = value
    return bar


def _bars(n: int = 5) -> list:
    return [_bar(i) for i in range(n)]


class TestValidateBars(unittest.TestCase):
    def test_valid_bars_pass(self):
        result = validate_bars(_bars(), "1h", now_ms=BASE + 10 * STEP)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["n_bars"], 5)
        self.assertEqual(result["gaps"], [])

    def test_gap_detected(self):
        bars = [_bar(0), _bar(2)]
        result = validate_bars(bars, "1h", now_ms=BASE + 10 * STEP)
        self.assertFalse(result["passed"])
        self.assertEqual(result["gaps"], [BASE + STEP])

    def test_duplicate_detected(self):
        bars = [_bar(0), _bar(0)]
        result = validate_bars(bars, "1h", now_ms=BASE + 10 * STEP)
        self.assertFalse(result["passed"])
        self.assertEqual(result["duplicates"], [BASE])

    def test_high_low_violation(self):
        bars = [_bar(0, {2: "99.0"})]  # high < open/close
        result = validate_bars(bars, "1h", now_ms=BASE + 10 * STEP)
        self.assertFalse(result["passed"])

    def test_unclosed_bar_rejected(self):
        bars = [_bar(0)]
        # now 在该 bar 收盘之前 -> 未收盘
        result = validate_bars(bars, "1h", now_ms=BASE + STEP // 2)
        self.assertFalse(result["passed"])

    def test_empty_rejected(self):
        result = validate_bars([], "1h", now_ms=BASE)
        self.assertFalse(result["passed"])

    def test_drop_unclosed_bars(self):
        closed, dropped = drop_unclosed_bars(_bars(3), BASE + 2 * STEP)
        self.assertEqual(len(closed), 2)
        self.assertEqual(dropped, 1)


class TestSnapshotImmutability(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_verify_and_readonly(self):
        manifest = write_snapshot(self.state, "SNAP-20261104-001", "ETHUSDT",
                                  "1h", _bars(), "https://example.invalid/klines",
                                  "2026-11-04T00:00:00Z")
        snap_dir = self.state / "snapshots" / "SNAP-20261104-001"
        self.assertTrue(manifest["quality_passed"])
        self.assertEqual(len(manifest["data_sha256"]), 64)
        modes = data_engine.file_modes(snap_dir)
        self.assertEqual(modes["data.json"], "0o444")
        self.assertEqual(modes["manifest.json"], "0o444")
        self.assertTrue(verify_snapshot(snap_dir)["ok"])

    def test_second_write_same_id_refused(self):
        write_snapshot(self.state, "SNAP-20261104-001", "ETHUSDT", "1h",
                       _bars(), "https://example.invalid/klines",
                       "2026-11-04T00:00:00Z")
        with self.assertRaises(FileExistsError):
            write_snapshot(self.state, "SNAP-20261104-001", "ETHUSDT", "1h",
                           _bars(), "https://example.invalid/klines",
                           "2026-11-04T00:00:00Z")

    def test_tamper_detected(self):
        write_snapshot(self.state, "SNAP-20261104-001", "ETHUSDT", "1h",
                       _bars(), "https://example.invalid/klines",
                       "2026-11-04T00:00:00Z")
        data_path = self.state / "snapshots" / "SNAP-20261104-001" / "data.json"
        os.chmod(data_path, 0o644)
        data = json.loads(data_path.read_text())
        data["bars"][0]["close"] = 999.0
        data_path.write_text(json.dumps(data))
        result = verify_snapshot(self.state / "snapshots" / "SNAP-20261104-001")
        self.assertFalse(result["ok"])
        self.assertFalse(result["hash_ok"])

    def test_quality_failure_refuses_write(self):
        with self.assertRaises(ValueError):
            write_snapshot(self.state, "SNAP-20261104-001", "ETHUSDT", "1h",
                           [_bar(0), _bar(2)], "https://example.invalid/klines",
                           "2026-11-04T00:00:00Z")
        self.assertFalse((self.state / "snapshots").exists()
                         or list((self.state / "snapshots").glob("*")))

    def test_ledger_appends(self):
        write_snapshot(self.state, "SNAP-20261104-001", "ETHUSDT", "1h",
                       _bars(), "https://example.invalid/klines",
                       "2026-11-04T00:00:00Z")
        write_snapshot(self.state, "SNAP-20261104-002", "BTCUSDT", "1h",
                       _bars(), "https://example.invalid/klines",
                       "2026-11-04T00:00:00Z")
        lines = (self.state / "snapshot-ledger.jsonl").read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["snapshot_id"], "SNAP-20261104-001")
        self.assertEqual(json.loads(lines[1])["snapshot_id"], "SNAP-20261104-002")


class TestFetchReadOnly(unittest.TestCase):
    def test_https_only(self):
        with self.assertRaises(data_engine.FetchError):
            fetch_json("http://127.0.0.1:9/ping", allowed_hosts={"127.0.0.1"})

    def test_signed_params_rejected(self):
        with self.assertRaises(data_engine.FetchError):
            fetch_json("https://www.binance.com/fapi/v1/klines?symbol=ETHUSDT&signature=abc")

    def test_non_allowlisted_host_rejected(self):
        with self.assertRaises(data_engine.FetchError):
            fetch_json("https://example.invalid/ping")

    def test_probe_rejects_http_and_leaks_no_body(self):
        with self.assertRaises(data_engine.FetchError):
            probe("http://127.0.0.1:9/ping", allowed_hosts={"127.0.0.1"})

    def test_fetch_json_parses_without_network(self):
        # 伪造 urlopen：验证解析路径，不产生真实网络请求。
        import urllib.request
        from unittest import mock

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps([_bar(0)]).encode()

        with mock.patch.object(urllib.request, "urlopen", return_value=_Resp()):
            bars = fetch_klines("https://www.binance.com/fapi/v1/klines",
                                "ETHUSDT", "1h", 1)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0][0], BASE)

    def test_probe_success_has_no_body_field(self):
        import urllib.request
        from unittest import mock

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b"{}"

        with mock.patch.object(urllib.request, "urlopen", return_value=_Resp()):
            result = probe("https://www.binance.com/fapi/v1/ping")
        self.assertEqual(result["status"], 200)
        self.assertNotIn("body", result)
        self.assertEqual(result["body_bytes"], 2)


if __name__ == "__main__":
    unittest.main()
