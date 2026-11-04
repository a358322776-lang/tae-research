"""任务调度器（Stage 1 第六项，G6）——仅开发，默认关闭，不启动。

授权边界（用户 2026-11-04 12:43 第四条）：
- 允许开发调度器、任务状态机、失败重试机制和周报模板。
- 调度器默认关闭，禁止接入现有生产 cron 自动运行。
  因此本模块：无 cron 集成、无 APScheduler 依赖、无线程/循环、
  无自动执行。任务只在调用方显式调用 tick() 且调度器已启用时
  才会被分派给调用方提供的 handler；调度器自身从不执行代码、
  不调用 Codex、不访问网络、不触碰生产配置。
- 重试上限 2 次（与方案 G0 一致），耗尽后任务终态 FAILED，
  不再自动重试，不存在无限循环。

状态机：PENDING -> RUNNING -> SUCCEEDED；RUNNING --失败-->
FAILED（可重试时回 PENDING 并计 attempts，耗尽则终态 FAILED）。
全部状态变迁只追加写入 scheduler-log.jsonl（本地-only）。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

MAX_RETRIES = 2


@dataclass
class Task:
    task_id: str
    kind: str
    status: str = "PENDING"
    attempts: int = 0
    max_retries: int = MAX_RETRIES
    last_error: str | None = None
    usage: dict = field(default_factory=dict)
    created_at_utc: str = ""
    updated_at_utc: str = ""


class Scheduler:
    """默认关闭的状态机。enabled 只能由显式 enable() 打开，且每次
    打开都记入日志（含调用方标注）；生产环境中启用还须用户单独批准
    ——本模块不提供任何自动启用的路径。"""

    def __init__(self, state_dir: str | Path, *, enabled: bool = False):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.enabled = enabled
        self.enabled_by: str | None = None
        self.tasks: dict[str, Task] = {}
        self.log_path = self.state_dir / "scheduler-log.jsonl"

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _log(self, event: str, task: Task | None = None, **extra) -> None:
        record = {"event": event, "at_utc": self._now(),
                  "task_id": task.task_id if task else None,
                  "status": task.status if task else None, **extra}
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def enable(self, *, by: str) -> None:
        """显式启用（须人工调用并留名）。仅内存状态，不写 cron。"""
        self.enabled = True
        self.enabled_by = by
        self._log("scheduler_enabled", enabled_by=by)

    def disable(self, *, by: str) -> None:
        self.enabled = False
        self._log("scheduler_disabled", enabled_by=by)

    def submit(self, task: Task) -> Task:
        if task.task_id in self.tasks:
            raise ValueError(f"duplicate task_id: {task.task_id}")
        if task.status != "PENDING":
            raise ValueError("new tasks must start PENDING")
        task.created_at_utc = self._now()
        task.updated_at_utc = task.created_at_utc
        self.tasks[task.task_id] = task
        self._log("submitted", task, kind=task.kind)
        return task

    def tick(self, handler) -> dict:
        """分派一轮 PENDING 任务。关闭时不做任何事（返回 ran=0）。

        handler: callable(task) -> (ok: bool, usage: dict, error: str|None)，
        由调用方提供；调度器只负责状态变迁与重试记账。
        """
        if not self.enabled:
            return {"enabled": False, "ran": 0, "succeeded": 0, "failed": 0}
        ran = succeeded = failed = 0
        for task in list(self.tasks.values()):
            if task.status != "PENDING":
                continue
            ran += 1
            task.status = "RUNNING"
            task.attempts += 1
            task.updated_at_utc = self._now()
            self._log("started", task, attempt=task.attempts)
            ok, usage, error = handler(task)
            task.usage = usage or {}
            if ok:
                task.status = "SUCCEEDED"
                task.last_error = None
                succeeded += 1
                self._log("succeeded", task, usage=task.usage)
            elif task.attempts <= task.max_retries:
                task.status = "PENDING"
                task.last_error = error
                self._log("failed_retry_pending", task, error=error,
                          attempts=task.attempts)
            else:
                task.status = "FAILED"
                task.last_error = error
                failed += 1
                self._log("failed_terminal", task, error=error,
                          attempts=task.attempts)
            task.updated_at_utc = self._now()
        return {"enabled": True, "ran": ran, "succeeded": succeeded,
                "failed": failed}

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for task in self.tasks.values():
            counts[task.status] = counts.get(task.status, 0) + 1
        failures = [{"task_id": t.task_id, "kind": t.kind,
                     "attempts": t.attempts, "error": t.last_error}
                    for t in self.tasks.values() if t.status == "FAILED"]
        return {"enabled": self.enabled, "enabled_by": self.enabled_by,
                "total": len(self.tasks), "by_status": counts,
                "failures": failures,
                "tasks": [{"task_id": t.task_id, "kind": t.kind,
                           "status": t.status, "attempts": t.attempts,
                           "usage": t.usage} for t in self.tasks.values()]}


# ---------------------------------------------------------- 周报模板
REQUIRED_SECTIONS = [
    "研究任务数量",
    "实验登记状态",
    "失败任务与错误原因",
    "数据质量问题",
    "资源使用情况",
    "安全门禁状态",
    "下一阶段待审批事项",
]


def collect_safety_gates(*, standards_path: str | Path, hash_path: str | Path,
                         c5_path: str | Path, live_ok_path: str | Path,
                         scheduler_enabled: bool) -> dict:
    """只读采集安全门禁状态（不修改任何文件）。"""
    from validator import load_sealed_standards, ValidationBlocked
    gates: dict[str, str] = {}
    try:
        load_sealed_standards(standards_path, hash_path)
        gates["validation_standards"] = "SEALED_OK"
    except (ValidationBlocked, OSError) as exc:
        gates["validation_standards"] = f"BLOCKED: {exc}"
    try:
        text = Path(c5_path).read_text(encoding="utf-8")
        gates["c5_execution_gate"] = (
            "CLOSED (EXECUTION_APPROVED=False)"
            if "EXECUTION_APPROVED = False" in text else "OPEN_OR_UNKNOWN")
    except OSError as exc:
        gates["c5_execution_gate"] = f"UNKNOWN: {exc}"
    gates["live_trading_gate"] = (
        "OPEN (.live-ok exists) - LIVE BLOCKED PENDING REVIEW"
        if Path(live_ok_path).exists() else "CLOSED (no .live-ok)")
    gates["scheduler"] = "ENABLED" if scheduler_enabled else "DISABLED (default)"
    gates["autonomous_research"] = "NOT_APPROVED (Stage 2 pending)"
    return gates


def build_weekly_report(*, week_label: str, tasks_summary: dict,
                        registry_summary: dict, data_quality_issues: list[str],
                        resource_usage: dict, safety_gates: dict,
                        pending_approvals: list[str]) -> str:
    """周报 Markdown（DRAFT，不发送）。七节缺一不可，缺数据写“无/未知”，
    不得编造数字。调用方须保证传入的数字来自登记库/日志的真实汇总。"""
    generated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lines = [
        f"# 研究周报（草稿）—— {week_label}",
        "",
        f"生成时间（UTC）：{generated}；状态：DRAFT，未发送；",
        "自主研究权限：未批准。本周报只汇总基础设施与登记状态，",
        "不含任何策略收益结论。",
        "",
        "## 1. 研究任务数量",
        "",
        f"- 任务总数：{tasks_summary.get('total', '未知')}",
        f"- 按状态：{tasks_summary.get('by_status', '未知')}",
        f"- 调度器：{'启用' if tasks_summary.get('enabled') else '关闭（默认）'}",
        "",
        "## 2. 实验登记状态",
        "",
        f"- 登记库摘要：{registry_summary}",
        "- 计数器硬上限：每周假设 ≤3、正式实验 ≤20；超限登记会被拒绝。",
        "",
        "## 3. 失败任务与错误原因",
        "",
    ]
    failures = tasks_summary.get("failures", [])
    if failures:
        for f in failures:
            lines.append(
                f"- {f.get('task_id')}（{f.get('kind')}）：尝试 "
                f"{f.get('attempts')} 次，错误：{f.get('error')}")
    else:
        lines.append("- 无终态失败任务。")
    lines += [
        "",
        "## 4. 数据质量问题",
        "",
    ]
    if data_quality_issues:
        lines += [f"- {issue}" for issue in data_quality_issues]
    else:
        lines.append("- 无新数据质量问题（快照质量门全部通过）。")
    lines += [
        "",
        "## 5. 资源使用情况",
        "",
        f"- 资源汇总：{resource_usage}",
        "- 单实验上限：2 核 / 2GiB / 30 分钟；Codex 任务上限：20 分钟 / 2GiB / 每周 ≤40 次。",
        "",
        "## 6. 安全门禁状态",
        "",
    ]
    for name, status in safety_gates.items():
        lines.append(f"- {name}：{status}")
    lines += [
        "",
        "## 7. 下一阶段待审批事项",
        "",
    ]
    if pending_approvals:
        lines += [f"- {item}" for item in pending_approvals]
    else:
        lines.append("- 无。")
    lines.append("")
    return "\n".join(lines)
