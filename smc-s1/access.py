"""最终测试集隔离：段访问控制 + 只追加访问日志（B2-FIX）。

诚实口径（必读）：本模块在 API 层执行隔离——只有经
SegmentStore 才能拿到段边界，且 final_test 一律拒绝；它不
是文件系统级隔离：同一 UID 的进程仍可直接读取缓存文件，
本模块不宣称、也不提供那种保证。真正的强制隔离（只读访问
器、密封目录）属 B2/B3，尚未建设。

日志：每次访问尝试（含被拒）追加一条 JSONL，哈希链串联；
verify_log 校验链完整，任何篡改（改字段、删行、插行）均
报错。日志只追加，写后不可改；默认路径在 gitignored 的
research-lab/state/ 目录下。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = (_REPO_ROOT / "research-lab" / "state"
                    / "smc-s1-access-log.jsonl")

_GENESIS = "GENESIS"
_ALLOWED = ("train", "validation")


class FinalTestBlocked(Exception):
    """最终测试段在冻结前禁止一切读取与绩效计算，无解锁开关。"""


def _entry_hash(prev_hash: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + "\n" + canonical).encode("utf-8")
                          ).hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SegmentStore:
    """由 split-manifest 结构定义三段；只放行 train/validation。"""

    def __init__(self, manifest: dict, log_path: Path | None = None,
                 caller: str = "smc-s1") -> None:
        try:
            split = manifest["split_15m"]
            self._segments = {
                name: (int(split[name]["start_idx"]),
                       int(split[name]["end_idx"]))
                for name in ("train", "validation", "final_test")
            }
        except (KeyError, TypeError) as exc:
            raise ValueError("manifest lacks split_15m segment bounds") \
                from exc
        self.manifest_version = manifest.get("format_version", "unknown")
        self.log_path = Path(log_path) if log_path is not None \
            else DEFAULT_LOG_PATH
        self.caller = caller

    @classmethod
    def from_file(cls, manifest_path: Path, log_path: Path | None = None,
                  caller: str = "smc-s1") -> "SegmentStore":
        manifest = json.loads(Path(manifest_path).read_text(
            encoding="utf-8"))
        return cls(manifest, log_path=log_path, caller=caller)

    def _log(self, segment: str, purpose: str, result: str) -> None:
        prev_hash = _GENESIS
        if self.log_path.exists():
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = [ln for ln in f if ln.strip()]
            if lines:
                prev_hash = json.loads(lines[-1])["entry_hash"]
        payload = {"ts": _utcnow_iso(), "segment": segment,
                   "purpose": purpose, "result": result,
                   "manifest_version": self.manifest_version,
                   "caller": self.caller}
        entry = dict(payload)
        entry["prev_hash"] = prev_hash
        entry["entry_hash"] = _entry_hash(prev_hash, payload)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")

    def open_segment(self, name: str, purpose: str) -> tuple[int, int]:
        """返回 (start_idx, end_idx)。final_test 一律拒绝，无后门。"""
        if not purpose or not purpose.strip():
            raise ValueError("purpose is required for segment access")
        if name == "final_test":
            self._log(name, purpose, "denied")
            raise FinalTestBlocked(
                "final_test segment is blocked until freeze (B3); "
                "no unlock switch exists")
        if name not in self._segments:
            self._log(name, purpose, "error")
            raise ValueError(f"unknown segment: {name}")
        bounds = self._segments[name]
        self._log(name, purpose, "granted")
        return bounds

    def slice_for(self, name: str, purpose: str,
                  n_total: int) -> slice:
        """段切片；段边界超出数据总量时报错（清单/数据不一致）。"""
        start, end = self.open_segment(name, purpose)
        if end > n_total or start < 0:
            raise ValueError(
                f"segment {name} bounds [{start}, {end}) exceed "
                f"data length {n_total}")
        return slice(start, end)


def verify_log(log_path: Path) -> list[dict]:
    """校验访问日志哈希链；篡改、缺字段、断链均报错。返回全部条目。"""
    path = Path(log_path)
    if not path.exists():
        raise ValueError(f"access log not found: {path}")
    entries: list[dict] = []
    prev_hash = _GENESIS
    required = {"ts", "segment", "purpose", "result",
                "manifest_version", "caller", "prev_hash", "entry_hash"}
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            entry = json.loads(line)
            if set(entry) != required:
                raise ValueError(
                    f"log line {lineno}: fields mismatch: "
                    f"{sorted(set(entry))}")
            if entry["prev_hash"] != prev_hash:
                raise ValueError(
                    f"log line {lineno}: hash chain broken "
                    f"(prev_hash mismatch)")
            payload = {k: entry[k] for k in required
                       - {"prev_hash", "entry_hash"}}
            if _entry_hash(prev_hash, payload) != entry["entry_hash"]:
                raise ValueError(
                    f"log line {lineno}: entry hash mismatch (tampered)")
            entries.append(entry)
            prev_hash = entry["entry_hash"]
    return entries
