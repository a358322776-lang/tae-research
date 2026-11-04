"""最终测试集格式定义与校验（B1）。

仅标准库，仅定义格式与纯函数校验。B1 范围：规格模板、
manifest 格式、summary 格式——不含任何真实数据。

明确不在 B1 内（B2/B3，未批）：只读访问器、访问日志、
验证器切分扫描、目录密封、任何真实测试数据的创建/冻结、
任何测试集访问权限的开放。本模块不读、不写任何数据文件，
不提供访问测试集的入口。
"""

from __future__ import annotations

import hashlib
import json
import re

FORMAT_VERSION = "test-set-formats-v1"

# summary 只允许计数类字段；以下键出现即视为携带原始数据，拒绝。
RAW_DATA_KEYS = frozenset({
    "bars", "data", "prices", "rows", "klines", "records", "ohlc",
    "timestamps", "samples",
})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FormatError(ValueError):
    """格式校验失败。"""


def canonical_json(obj: dict) -> bytes:
    """规范序列化：排序键、紧凑分隔，供哈希使用。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def hash_dict(obj: dict) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()


def spec_template() -> dict:
    """规格模板：全部实质字段为占位符，status 明确标注未冻结。

    冻结规格（B3）须单独批准；模板永远不得声称已冻结。
    """
    return {
        "format_version": FORMAT_VERSION,
        "test_set_id": "final-v1",
        "status": "TEMPLATE-NOT-FROZEN",
        "universe": ["TBD"],
        "windows": {
            "train": {"start_ms": None, "end_ms": None},
            "validation": {"start_ms": None, "end_ms": None},
            "final_test": {"start_ms": None, "end_ms": None},
        },
        "fields": ["open", "high", "low", "close", "volume"],
        "exclusion_rules": ["TBD"],
        "freeze_timestamp_ms": None,
        "new_data_rule": ("冻结后产生的新数据自动划入最终测试集，"
                          "不得用于训练/验证；实际划入动作须冻结"
                          "事件批准。"),
    }


def validate_spec(spec: dict, *, is_template: bool) -> None:
    """校验规格。模板模式下 freeze 时间戳必须为空且 status 须为
    TEMPLATE-NOT-FROZEN；非模板模式不在 B1 内，拒绝。"""
    if not is_template:
        raise FormatError("non-template spec validation is B3 scope")
    required = {"format_version", "test_set_id", "status", "universe",
                "windows", "fields", "exclusion_rules",
                "freeze_timestamp_ms", "new_data_rule"}
    missing = required - set(spec)
    if missing:
        raise FormatError(f"spec missing fields: {sorted(missing)}")
    if spec["format_version"] != FORMAT_VERSION:
        raise FormatError("spec format_version mismatch")
    if spec["status"] != "TEMPLATE-NOT-FROZEN":
        raise FormatError("template spec must not claim frozen status")
    if spec["freeze_timestamp_ms"] is not None:
        raise FormatError("template spec must not carry a freeze timestamp")
    for name, window in spec["windows"].items():
        if set(window) != {"start_ms", "end_ms"}:
            raise FormatError(f"window {name} must have start_ms/end_ms")
        if window["start_ms"] is not None or window["end_ms"] is not None:
            raise FormatError(
                f"template window {name} must not carry real dates")


def manifest_template(spec_sha256: str) -> dict:
    """manifest 模板：文件列表为空（B3 之前无数据文件可列）。"""
    return {
        "format_version": FORMAT_VERSION,
        "test_set_id": "final-v1",
        "spec_sha256": spec_sha256,
        "files": [],
    }


def validate_manifest(manifest: dict) -> None:
    required = {"format_version", "test_set_id", "spec_sha256", "files"}
    missing = required - set(manifest)
    if missing:
        raise FormatError(f"manifest missing fields: {sorted(missing)}")
    if manifest["format_version"] != FORMAT_VERSION:
        raise FormatError("manifest format_version mismatch")
    if not _SHA256_RE.match(manifest["spec_sha256"]):
        raise FormatError("manifest spec_sha256 must be 64 hex chars")
    seen: set[str] = set()
    for entry in manifest["files"]:
        if set(entry) != {"path", "sha256", "rows"}:
            raise FormatError("manifest file entry must have path/sha256/rows")
        if entry["path"] in seen:
            raise FormatError(f"duplicate manifest path: {entry['path']}")
        seen.add(entry["path"])
        if not _SHA256_RE.match(entry["sha256"]):
            raise FormatError(f"bad file sha256 for {entry['path']}")
        if not isinstance(entry["rows"], int) or entry["rows"] < 0:
            raise FormatError(f"rows must be a non-negative int: {entry}")


def summary_template() -> dict:
    """summary 模板：仅计数区间，全部为空占位。"""
    return {
        "format_version": FORMAT_VERSION,
        "test_set_id": "final-v1",
        "bar_count_range": [None, None],
        "symbol_count": None,
        "window_start_ms": None,
        "window_end_ms": None,
    }


def validate_summary(summary: dict) -> None:
    required = {"format_version", "test_set_id", "bar_count_range",
                "symbol_count", "window_start_ms", "window_end_ms"}
    missing = required - set(summary)
    if missing:
        raise FormatError(f"summary missing fields: {sorted(missing)}")
    if summary["format_version"] != FORMAT_VERSION:
        raise FormatError("summary format_version mismatch")
    raw = RAW_DATA_KEYS & set(summary)
    if raw:
        raise FormatError(f"summary must not carry raw data: {sorted(raw)}")
    lo, hi = summary["bar_count_range"]
    if (lo is not None and hi is not None) and lo > hi:
        raise FormatError("bar_count_range lower bound exceeds upper bound")
