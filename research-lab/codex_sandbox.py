"""Codex 沙箱 v1（Stage 1 第五项，G5）——建设 + 安全测试，不开放自主研究。

授权边界（用户 2026-11-04 12:43 第三条）：
- 不访问交易密钥；不挂载生产凭据；不具备实盘下单权限；
  默认限制网络访问；限制 CPU/内存/磁盘/执行时间；
  代码执行与验证规则管理权限分离；禁止未经批准的生产部署。
- 沙箱完成后先安全测试，不能直接开放自主研究权限。
  因此 run_codex_task() 在本阶段一律拒绝（见 NotApprovedError）；
  本模块只接受本地 Python 代码片段做安全测试。

实现方式（本 VM 实测可用，见安全验收报告）：
- 网络：`unshare --net`（独立网络命名空间，无接口）+ fail-closed：
  unshare 不可用时拒绝运行，绝不降级为“无隔离运行”。
- 资源：preexec rlimits（CPU 时间、地址空间 2GiB、单文件 100MB、
  进程数）+ subprocess wall-clock 超时。
- 环境：白名单 env（PATH/HOME/TMPDIR/LANG），HOME/TMPDIR 均指向
  工作目录；全部继承 env 被丢弃，密钥不可能经环境进入。
- 文件：cwd = 隔离工作目录；AST 预扫描拒绝危险导入/调用与绝对
  路径写操作；运行后复核受保护文件（验证标准、登记库）哈希。
- 权限分离：验证标准与登记库不在工作目录内，沙箱代码无写路径；
  沙箱自身不能修改 validator.py / standards（运行后哈希复核）。

如实说明的残留风险（v1 非内核级文件隔离）：
- 本 VM 无 docker/podman/firejail/bwrap；v1 不做 mount 命名空间
  bind 隔离，文件隔离靠 cwd + AST 扫描 + 环境隔离 + 事后哈希复核。
  有决心的攻击代码仍可能经未拦截的路径访问文件系统。
  因此 v1 只适用于“受监督的、已扫描的代码片段”，Codex 自主任务
  仍须 Stage 2 单独批准 + 更强的隔离主机（容器/独立 VM）复核。
  沙箱不是“可以放心跑任意代码”的保证，不得如此宣传。
"""

from __future__ import annotations

import ast
import hashlib
import os
import resource
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# 批准值（方案 v1.1 G0）：单实验 2 核/2GiB/30 分钟；Codex 任务
# 20 分钟/2GiB/每周 ≤40 次。沙箱默认值取其中较严的一组。
DEFAULT_CPU_SECONDS = 20 * 60
DEFAULT_WALL_SECONDS = 20 * 60
DEFAULT_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_PROCS = 64
DEFAULT_MAX_OUTPUT_BYTES = 1 * 1024 * 1024


class SandboxUnavailable(Exception):
    """隔离机制不可用：拒绝运行（fail-closed）。"""


class NotApprovedError(Exception):
    """Codex 任务执行未批准：本阶段一律拒绝。"""


class CodeRejected(Exception):
    """AST 预扫描拒绝：代码含危险导入/调用/路径。"""


@dataclass
class SandboxLimits:
    cpu_seconds: int = DEFAULT_CPU_SECONDS
    wall_seconds: int = DEFAULT_WALL_SECONDS
    memory_bytes: int = DEFAULT_MEMORY_BYTES
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_procs: int = DEFAULT_MAX_PROCS
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES


_BLOCKED_IMPORTS = {
    "socket", "subprocess", "os", "shutil", "ctypes", "urllib",
    "urllib.request", "urllib.parse", "requests", "http", "http.client",
    "ftplib", "smtplib", "asyncio", "importlib", "pkgutil", "pty",
    "multiprocessing", "signal", "telnetlib", "xmlrpc", "webbrowser",
    "pty", "fcntl", "resource",
}
_BLOCKED_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint"}
_BLOCKED_ATTRS = {"environ", "system", "popen", "getenv", "putenv"}


def scan_code(source: str) -> list[str]:
    """AST 预扫描：返回拒绝原因列表（空 = 通过）。这是 lint 层防护，
    不是内核强制；运行时隔离（unshare/rlimits/env）是第二层。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"syntax error: {exc}"]
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if alias.name in _BLOCKED_IMPORTS or top in _BLOCKED_IMPORTS:
                    findings.append(f"blocked import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in _BLOCKED_IMPORTS or mod.split(".")[0] in _BLOCKED_IMPORTS:
                findings.append(f"blocked import from: {mod}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _BLOCKED_CALLS:
                findings.append(f"blocked call: {func.id}")
            if isinstance(func, ast.Name) and func.id == "open" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    path = arg.value
                    if path.startswith("/") or ".." in Path(path).parts:
                        findings.append(f"blocked open() path: {path!r}")
        elif isinstance(node, ast.Attribute):
            if node.attr in _BLOCKED_ATTRS:
                findings.append(f"blocked attribute access: .{node.attr}")
    return findings


def hash_files(paths: list[str | Path]) -> dict[str, str | None]:
    """受保护文件哈希快照（不存在记 None）。"""
    out: dict[str, str | None] = {}
    for p in paths:
        path = Path(p)
        out[str(path)] = (hashlib.sha256(path.read_bytes()).hexdigest()
                          if path.exists() else None)
    return out


def _sandbox_env(workdir: Path) -> dict[str, str]:
    """白名单环境：不继承任何调用方 env，密钥无从进入。"""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(workdir),
        "TMPDIR": str(workdir),
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
    }


def network_isolation_available() -> bool:
    """探针：unshare --net 是否可用。"""
    if shutil.which("unshare") is None:
        return False
    try:
        res = subprocess.run(["unshare", "--net", "true"],
                             timeout=10, capture_output=True)
        return res.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _limits_preexec(limits: SandboxLimits):
    def preexec() -> None:
        resource.setrlimit(resource.RLIMIT_CPU,
                           (limits.cpu_seconds, limits.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS,
                           (limits.memory_bytes, limits.memory_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE,
                           (limits.max_file_bytes, limits.max_file_bytes))
        resource.setrlimit(resource.RLIMIT_NPROC,
                           (limits.max_procs, limits.max_procs))
    return preexec


def run_python_code(source: str, *, limits: SandboxLimits | None = None,
                    work_root: str | Path | None = None,
                    protected_paths: list[str | Path] | None = None,
                    skip_scan: bool = False) -> dict:
    """在沙箱内运行一段 Python 代码（测试用；非 Codex 任务入口）。

    skip_scan=True 仅供安全测试验证纵深防御（证明即使扫描被绕过，
    网络隔离与资源限制仍生效）；生产调用一律不得传 True。
    返回 {returncode, stdout, stderr, timed_out, wall_seconds,
    peak_rss_kb, workdir, protected_unchanged, network_isolated}。
    """
    limits = limits or SandboxLimits()
    findings = [] if skip_scan else scan_code(source)
    if findings:
        raise CodeRejected("; ".join(findings))
    if not network_isolation_available():
        raise SandboxUnavailable(
            "unshare --net unavailable; refusing to run without network isolation")
    root = Path(work_root) if work_root is not None else Path(
        tempfile.mkdtemp(prefix="muse-sandbox-"))
    root.mkdir(parents=True, exist_ok=True)
    workdir = root / "run"
    workdir.mkdir(exist_ok=True)
    task_path = workdir / "task.py"
    task_path.write_text(source, encoding="utf-8")
    before = hash_files(protected_paths or [])
    cmd = ["unshare", "--net", "python3", "-I", str(task_path)]
    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd, cwd=str(workdir), env=_sandbox_env(workdir),
            stdin=subprocess.DEVNULL, capture_output=True,
            timeout=limits.wall_seconds,
            preexec_fn=_limits_preexec(limits))
        returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode, stdout, stderr = -1, exc.stdout or b"", exc.stderr or b""
    wall = time.monotonic() - started
    try:
        peak_rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    except Exception:  # noqa: BLE001 - 资源统计失败不掩盖运行结果
        peak_rss = -1
    after = hash_files(protected_paths or [])
    return {
        "returncode": returncode,
        "stdout": stdout[:limits.max_output_bytes].decode("utf-8", "replace"),
        "stderr": stderr[:limits.max_output_bytes].decode("utf-8", "replace"),
        "timed_out": timed_out,
        "wall_seconds": round(wall, 3),
        "peak_rss_kb": peak_rss,
        "workdir": str(workdir),
        "protected_unchanged": before == after,
        "network_isolated": True,
    }


def run_codex_task(*args, **kwargs):
    """Codex 任务入口（本阶段）：一律拒绝。

    开放自主研究权限须 Stage 2 单独批准 + API 花费计量手段；
    在此之前，任何 Codex exec 调用（包括经沙箱）均未批准。
    未来的批准实现须：任务登记（registry）→ 沙箱运行 → 验证器复核，
    且 Codex 自身不得接触密钥、网络与生产路径。
    """
    raise NotApprovedError(
        "Codex task execution is not approved in Stage 1: sandbox is "
        "for safety testing only; autonomous research requires a "
        "separate Stage 2 approval with API metering.")
