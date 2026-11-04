"""统一实验登记：计数器与只追加门禁（registry-schema-v1）。

只用 Python 标准库。SQLite 为准，Markdown 副本由周报生成（不在此模块）。
硬上限（已批准值，见 tae-b1/approvals/approval-2026-11-04-v11-stage1.md）：
  每轮假设 <= 3 个；每周正式实验 <= 20 次。
超限时登记函数直接抛 RegistryLimitError，调用方不得绕过。
attempts / knowledge / audit_log 的只追加由数据库触发器强制（见 schema）。
本模块不读、不写任何交易接口，不接触密钥与冻结目录。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("registry-schema-v1.sql")

MAX_HYPOTHESES_PER_ROUND = 3
MAX_FORMAL_EXPERIMENTS_PER_ROUND = 20
SCREEN_PASS_TOTAL = 6
SCREEN_KEYS = (
    "economic_logic",
    "data_available",
    "cost_estimable",
    "complexity_ok",
    "substantive_difference",
)

_ID_PATTERNS = {
    "round": re.compile(r"^ROUND-\d{4}-W\d{2}$"),
    "hypothesis": re.compile(r"^HYP-\d{8}-\d{2}$"),
    "experiment": re.compile(r"^EXP-\d{8}-\d{3}$"),
    "knowledge": re.compile(r"^KNOW-\d{8}-\d{3}$"),
}


class RegistryError(Exception):
    """登记通用错误（ID 格式、必填缺失等）。"""


class RegistryLimitError(RegistryError):
    """触及已批准硬上限。"""


class DuplicateError(RegistryError):
    """指纹完全重复：不得登记为新实验。"""


def _utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """按 schema v1 初始化空库。已存在的库不做迁移，只建缺失表。"""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def _check_id(kind: str, value: str) -> None:
    if not _ID_PATTERNS[kind].match(value):
        raise RegistryError(f"invalid {kind} id: {value!r}")


def ensure_round(conn: sqlite3.Connection, round_id: str, week_start: str) -> None:
    _check_id("round", round_id)
    conn.execute(
        "INSERT OR IGNORE INTO rounds(round_id, week_start, created_at)"
        " VALUES (?, ?, ?)",
        (round_id, week_start, _utcnow_iso()),
    )
    conn.execute(
        "INSERT OR IGNORE INTO multiplicity"
        "(round_id, updated_at) VALUES (?, ?)",
        (round_id, _utcnow_iso()),
    )
    conn.commit()


def screen_score(scores: dict) -> int:
    """SCREEN 五项打分：缺项、超范围、实质区别为 0 均直接判不合格。"""
    if set(scores) != set(SCREEN_KEYS):
        raise RegistryError(f"screen scores must have exactly keys {SCREEN_KEYS}")
    for key, value in scores.items():
        if value not in (0, 1, 2):
            raise RegistryError(f"screen score {key} must be 0, 1 or 2")
    if scores["substantive_difference"] == 0:
        raise RegistryError("substantive_difference == 0: cannot enter SPEC")
    total = sum(scores.values())
    if total < SCREEN_PASS_TOTAL:
        raise RegistryError(f"screen total {total} < {SCREEN_PASS_TOTAL}: cannot enter SPEC")
    return total


def fingerprint(mechanism: str, universe: str, frequency: str,
                entry_hash: str, exit_hash: str, cost_version: str) -> str:
    raw = "|".join([mechanism.strip(), universe.strip(), frequency.strip(),
                    entry_hash.strip(), exit_hash.strip(), cost_version.strip()])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def register_hypothesis(conn: sqlite3.Connection, *, hypothesis_id: str,
                         round_id: str, title: str, mechanism: str,
                         distinction_statement: str, fp: str,
                         screen_scores: dict, builds_on: str = "",
                         differs_from: str = "") -> None:
    """登记假设。超 3 个/轮、指纹完全重复、SCREEN 不合格均拒绝。"""
    _check_id("hypothesis", hypothesis_id)
    _check_id("round", round_id)
    if not distinction_statement.strip():
        raise RegistryError("distinction_statement is required")
    total = screen_score(screen_scores)
    with conn:  # 事务内计数 + 写入，单写者下计数器不超限
        count = conn.execute(
            "SELECT COUNT(*) FROM hypotheses WHERE round_id = ?", (round_id,)
        ).fetchone()[0]
        if count >= MAX_HYPOTHESES_PER_ROUND:
            raise RegistryLimitError(
                f"round {round_id} already has {count} hypotheses "
                f"(limit {MAX_HYPOTHESES_PER_ROUND})"
            )
        dup = conn.execute(
            "SELECT hypothesis_id FROM hypotheses WHERE fingerprint = ?", (fp,)
        ).fetchone()
        if dup:
            raise DuplicateError(
                f"fingerprint already registered as {dup[0]}: not a new hypothesis"
            )
        conn.execute(
            "INSERT INTO hypotheses(hypothesis_id, round_id, title, mechanism,"
            " distinction_statement, fingerprint, screen_scores_json,"
            " screen_total, builds_on, differs_from, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (hypothesis_id, round_id, title, mechanism, distinction_statement,
             fp, json.dumps(screen_scores, sort_keys=True), total,
             builds_on, differs_from, _utcnow_iso()),
        )
        conn.execute(
            "UPDATE multiplicity SET total_hypotheses = total_hypotheses + 1,"
            " updated_at = ? WHERE round_id = ?",
            (_utcnow_iso(), round_id),
        )


def register_experiment(conn: sqlite3.Connection, *, experiment_id: str,
                        hypothesis_id: str, round_id: str, spec_hash: str,
                        snapshot_id: str, cost_model_version: str,
                        seed: int) -> None:
    """登记正式实验。超 20 次/周直接拒绝。"""
    _check_id("experiment", experiment_id)
    _check_id("round", round_id)
    with conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM experiments WHERE round_id = ?", (round_id,)
        ).fetchone()[0]
        if count >= MAX_FORMAL_EXPERIMENTS_PER_ROUND:
            raise RegistryLimitError(
                f"round {round_id} already has {count} formal experiments "
                f"(limit {MAX_FORMAL_EXPERIMENTS_PER_ROUND})"
            )
        conn.execute(
            "INSERT INTO experiments(experiment_id, hypothesis_id, round_id,"
            " spec_hash, snapshot_id, cost_model_version, seed, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (experiment_id, hypothesis_id, round_id, spec_hash, snapshot_id,
             cost_model_version, seed, _utcnow_iso()),
        )
        conn.execute(
            "UPDATE multiplicity SET total_experiments = total_experiments + 1,"
            " updated_at = ? WHERE round_id = ?",
            (_utcnow_iso(), round_id),
        )


def log_attempt(conn: sqlite3.Connection, *, experiment_id: str, kind: str,
                result_hash: str | None = None, n_trades: int | None = None,
                mean_net_R: float | None = None) -> int:
    """追加一次运行记录（含复现运行）。返回 attempt_id。历史行不可改、不可删。"""
    if kind not in ("formal", "reproduction"):
        raise RegistryError("attempt kind must be 'formal' or 'reproduction'")
    with conn:
        cur = conn.execute(
            "INSERT INTO attempts(experiment_id, kind, run_at, result_hash,"
            " n_trades, mean_net_R, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (experiment_id, kind, _utcnow_iso(), result_hash, n_trades,
             mean_net_R, _utcnow_iso()),
        )
        conn.execute(
            "UPDATE multiplicity SET total_attempts = total_attempts + 1,"
            " updated_at = ? WHERE round_id = (SELECT round_id FROM"
            " experiments WHERE experiment_id = ?)",
            (_utcnow_iso(), experiment_id),
        )
        return cur.lastrowid


def add_knowledge(conn: sqlite3.Connection, *, knowledge_id: str, kind: str,
                  conclusion: str, evidence_refs: str, confidence: str) -> None:
    """追加知识条目。更正只能追加新条目，不得 UPDATE/DELETE 旧条目。"""
    _check_id("knowledge", knowledge_id)
    if kind not in ("mechanism", "failure_pattern", "cost_fact", "data_fact"):
        raise RegistryError(f"invalid knowledge kind: {kind}")
    if confidence not in ("high", "medium", "low"):
        raise RegistryError("confidence must be high, medium or low")
    now = _utcnow_iso()
    with conn:
        conn.execute(
            "INSERT INTO knowledge(knowledge_id, kind, conclusion,"
            " evidence_refs, confidence, last_reviewed, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (knowledge_id, kind, conclusion, evidence_refs, confidence, now, now),
        )


def audit(conn: sqlite3.Connection, *, actor: str, action: str,
          result: str, detail: str = "") -> None:
    """追加审计日志。"""
    with conn:
        conn.execute(
            "INSERT INTO audit_log(ts, actor, action, result, detail)"
            " VALUES (?, ?, ?, ?, ?)",
            (_utcnow_iso(), actor, action, result, detail),
        )


def round_counts(conn: sqlite3.Connection, round_id: str) -> dict:
    """返回某轮计数器（周报与调度器直接读此函数，不得手写数字）。"""
    row = conn.execute(
        "SELECT total_hypotheses, total_experiments, total_attempts"
        " FROM multiplicity WHERE round_id = ?",
        (round_id,),
    ).fetchone()
    if row is None:
        return {"hypotheses": 0, "experiments": 0, "attempts": 0}
    return {"hypotheses": row[0], "experiments": row[1], "attempts": row[2]}


def find_by_fingerprint(conn: sqlite3.Connection, fp: str) -> list[str]:
    """精确指纹查重：返回已登记的假设 ID（空 = 无重复）。"""
    return [r[0] for r in conn.execute(
        "SELECT hypothesis_id FROM hypotheses WHERE fingerprint = ?", (fp,))]


def find_by_mechanism(conn: sqlite3.Connection, mechanism: str) -> list[str]:
    """近似重复初筛：同机制已登记假设，供 SCREEN 人工/书面区别审查。"""
    return [r[0] for r in conn.execute(
        "SELECT hypothesis_id FROM hypotheses WHERE mechanism = ?", (mechanism,))]
