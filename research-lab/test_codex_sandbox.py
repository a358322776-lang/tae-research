"""Codex 沙箱安全测试：每项攻击/越界尝试都必须被挡住或杀死。

测试在隔离工作目录（tempfile）内运行；受保护文件用临时文件模拟
验证标准/登记库。网络隔离测试用 skip_scan=True 绕过 AST 扫描，
只为证明纵深防御的第二层（unshare）本身生效。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import codex_sandbox as sb
from codex_sandbox import (CodeRejected, NotApprovedError, SandboxLimits,
                           SandboxUnavailable, hash_files, run_codex_task,
                           run_python_code, scan_code)


class ScanTest(unittest.TestCase):
    def test_scan_blocks_dangerous_imports_and_calls(self):
        for src in ("import socket\n",
                    "import subprocess\n",
                    "import os\nprint(os.environ)\n",
                    "eval('1')\n",
                    "open('/etc/passwd').read()\n",
                    "open('../escape.txt', 'w')\n",
                    "from urllib.request import urlopen\n"):
            self.assertTrue(scan_code(src), src)
        self.assertEqual(scan_code("import math\nprint(math.sqrt(4))\n"), [])
        self.assertEqual(scan_code("open('out.txt', 'w').write('x')\n"), [])

    def test_run_rejects_blocked_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CodeRejected):
                run_python_code("import socket\n", work_root=tmp)


class RuntimeTest(unittest.TestCase):
    def test_benign_code_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_python_code("print(sum(range(100)))\n", work_root=tmp)
            self.assertEqual(res["returncode"], 0)
            self.assertIn("4950", res["stdout"])
            self.assertTrue(res["network_isolated"])

    def test_env_secrets_not_visible(self):
        # 调用方 env 中的标记不得进入沙箱 env（白名单构造证明）。
        os.environ["MUSE_SANDBOX_SECRET_MARKER"] = "should-not-leak"
        env = sb._sandbox_env(Path("/tmp/nope"))
        self.assertNotIn("MUSE_SANDBOX_SECRET_MARKER", env)
        # HOME/TMPDIR 在白名单内，但必须指向工作目录（隔离值），
        # 不得是调用方的真实 HOME。
        self.assertEqual(env["HOME"], "/tmp/nope")
        self.assertEqual(env["TMPDIR"], "/tmp/nope")
        for key in env:
            self.assertNotIn("KEY", key.upper())
            self.assertNotIn("TOKEN", key.upper())
            self.assertNotIn("SECRET", key.upper())

    def test_network_blocked_even_if_scan_bypassed(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_python_code(
                "import socket\n"
                "s = socket.create_connection(('8.8.8.8', 53), timeout=3)\n"
                "print('CONNECTED')\n",
                work_root=tmp, skip_scan=True,
                limits=SandboxLimits(wall_seconds=15))
            self.assertNotEqual(res["returncode"], 0)
            self.assertNotIn("CONNECTED", res["stdout"])
            self.assertTrue("Network" in res["stderr"]
                            or "unreachable" in res["stderr"]
                            or "Errno" in res["stderr"], res["stderr"])

    def test_infinite_loop_killed_by_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_python_code("while True:\n    pass\n", work_root=tmp,
                                  limits=SandboxLimits(wall_seconds=3,
                                                       cpu_seconds=5))
            self.assertTrue(res["timed_out"])
            self.assertLess(res["wall_seconds"], 10)

    def test_memory_hog_killed(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run_python_code(
                "x = []\nwhile True:\n    x.append(bytearray(1024 * 1024))\n",
                work_root=tmp,
                limits=SandboxLimits(wall_seconds=20,
                                     memory_bytes=128 * 1024 * 1024))
            self.assertNotEqual(res["returncode"], 0)

    def test_writes_stay_in_workdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "outside.txt"
            sentinel.write_text("untouched")
            res = run_python_code("open('out.txt', 'w').write('inside')\n",
                                  work_root=tmp)
            self.assertEqual(res["returncode"], 0)
            self.assertEqual((Path(res["workdir"]) / "out.txt").read_text(),
                             "inside")
            self.assertEqual(sentinel.read_text(), "untouched")

    def test_protected_files_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            protected = Path(tmp) / "standards.json"
            protected.write_text('{"v": 1}')
            res = run_python_code("print('ok')\n", work_root=tmp,
                                  protected_paths=[protected])
            self.assertTrue(res["protected_unchanged"])
            before = hash_files([protected])
            protected.write_text('{"v": 2}')
            self.assertNotEqual(before, hash_files([protected]))

    def test_codex_task_refused(self):
        with self.assertRaises(NotApprovedError):
            run_codex_task(task="anything")

    def test_fail_closed_without_unshare(self):
        orig = sb.network_isolation_available
        sb.network_isolation_available = lambda: False
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(SandboxUnavailable):
                    run_python_code("print(1)\n", work_root=tmp)
        finally:
            sb.network_isolation_available = orig


if __name__ == "__main__":
    unittest.main(verbosity=1)
