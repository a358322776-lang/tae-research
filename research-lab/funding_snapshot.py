"""资金费率快照最小管道验证（Stage 1 第三项第 4 条授权）。

仅采集少量公开历史资金费率数据，验证时间戳、完整性、版本、哈希
与数据质量。明确不恢复 CA-1 / P4 研究，不执行资金费率策略回测，
不计算任何资金费率策略收益。本模块只建管道：取数 -> 质量检查 ->
只读冻结 -> 哈希复核；快照本地-only，永不进仓。

复用 data_engine 的只读取数（主机白名单 + 拒签名参数），其余逻辑
独立实现，不改动已验收的 data_engine.py。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.parse
from pathlib import Path

from data_engine import fetch_json, FetchError, MIRROR_FUNDING

FUND_FORMAT_VERSION = "funding-snapshot-v1"
STEP_MS = 8 * 3600_000
MAX_GAP_MS = 24 * 3600_000


def fetch_funding(symbol: str, limit: int = 20, timeout: int = 15) -> list:
    """取公开 fundingRate 原始列表。limit clamp 到 1..100（最小必要）。"""
    if not symbol or not symbol.isalnum():
        raise FetchError(f"invalid symbol: {symbol!r}")
    if not 1 <= limit <= 100:
        raise FetchError(f"limit out of range 1..100: {limit}")
    query = urllib.parse.urlencode({"symbol": symbol, "limit": limit})
    data = fetch_json(f"{MIRROR_FUNDING}?{query}", timeout=timeout)
    if not isinstance(data, list):
        raise FetchError("fundingRate response is not a list")
    return data


def validate_funding_records(records: list, symbol: str,
                             now_ms: int | None = None) -> dict:
    """质量检查：字段、符号、数值、时间单调、无重复、无未来、缺口<=24h。

    缺口 >8h 但 <=24h 不判失败，记入 missing_steps（缺失的 8h 结算点）
    与 notes，供人工判断完整性；缺口 >24h 判失败（与 C5 覆盖规则一致）。
    返回 {passed, checks, issues, notes, n_records, normalized, missing_steps}。
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    checks: list[dict] = []
    issues: list[str] = []
    notes: list[str] = []
    normalized: list[dict] = []
    missing_steps: list[int] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    if not records:
        record("non_empty", False, "0 records")
        return {"passed": False, "checks": checks, "issues": ["empty record list"],
                "notes": notes, "n_records": 0, "normalized": normalized,
                "missing_steps": missing_steps}

    prev_time: int | None = None
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            issues.append(f"record {idx}: not an object")
            continue
        sym = rec.get("symbol")
        if sym != symbol:
            issues.append(f"record {idx}: symbol {sym!r} != {symbol!r}")
        try:
            funding_time = int(rec["fundingTime"])
        except (KeyError, TypeError, ValueError):
            issues.append(f"record {idx}: bad fundingTime {rec.get('fundingTime')!r}")
            continue
        try:
            rate = float(rec["fundingRate"])
        except (KeyError, TypeError, ValueError):
            issues.append(f"record {idx}: bad fundingRate {rec.get('fundingRate')!r}")
            continue
        if not math.isfinite(rate):
            issues.append(f"record {idx}: non-finite fundingRate {rate}")
            continue
        if funding_time > now_ms:
            issues.append(f"record {idx}: future fundingTime {funding_time} > now {now_ms}")
        if prev_time is not None:
            if funding_time <= prev_time:
                issues.append(
                    f"record {idx}: fundingTime not strictly increasing "
                    f"({prev_time} -> {funding_time})")
            elif funding_time - prev_time > MAX_GAP_MS:
                issues.append(
                    f"record {idx}: gap {funding_time - prev_time}ms > 24h")
            else:
                # 8h 网格对齐比较：镜像 fundingTime 带 0-5ms 抖动，
                # 直接按毫秒算步长会把抖动误判为缺失结算点。先量化到
                # 8h 网格再算缺失步数；容差 60s。
                q_prev = round(prev_time / STEP_MS) * STEP_MS
                q_cur = round(funding_time / STEP_MS) * STEP_MS
                if q_cur == q_prev:
                    issues.append(
                        f"record {idx}: same 8h settlement slot as previous "
                        f"({prev_time} -> {funding_time})")
                elif q_cur - q_prev > STEP_MS:
                    missing = q_prev + STEP_MS
                    while missing < q_cur:
                        missing_steps.append(missing)
                        missing += STEP_MS
                    notes.append(
                        f"record {idx}: gap {funding_time - prev_time}ms, "
                        f"{len(missing_steps)} settlement step(s) missing")
        prev_time = funding_time
        normalized.append({"symbol": symbol, "fundingTime": funding_time,
                           "fundingRate": rate})

    record("fields_and_symbol", not issues, f"{len(normalized)}/{len(records)} normalized")
    record("strictly_increasing", not any("strictly increasing" in i for i in issues),
           "fundingTime strictly increasing")
    record("no_future", not any("future" in i for i in issues), "all fundingTime <= now")
    record("gap_within_24h", not any("gap " in i and "> 24h" in i for i in issues),
           f"missing_steps={len(missing_steps)}")
    passed = all(c["passed"] for c in checks) and not issues
    return {"passed": passed, "checks": checks, "issues": issues,
            "notes": notes, "n_records": len(normalized),
            "normalized": normalized, "missing_steps": missing_steps}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def next_funding_id(state_dir: str | Path, date_str: str) -> str:
    """FUND-YYYYMMDD-NNN：按当日已有资金费快照数顺延，永不复用。"""
    root = Path(state_dir) / "funding-snapshots"
    existing = sorted(p.name for p in root.glob(f"FUND-{date_str}-*")) if root.exists() else []
    return f"FUND-{date_str}-{len(existing) + 1:03d}"


def write_funding_snapshot(state_dir: str | Path, snapshot_id: str,
                           symbol: str, records: list, source_url: str,
                           fetched_at_utc: str,
                           now_ms: int | None = None) -> dict:
    """写资金费快照：先质量检查，通过后写 data.json + manifest.json 并设只读。

    目录已存在即拒绝（永不覆盖）。ledger 写入 funding-ledger.jsonl（只追加）。
    """
    quality = validate_funding_records(records, symbol, now_ms=now_ms)
    if not quality["passed"]:
        raise ValueError(
            f"funding quality check failed, snapshot refused: {quality['issues']}")
    snap_dir = Path(state_dir) / "funding-snapshots" / snapshot_id
    if snap_dir.exists():
        raise FileExistsError(
            f"funding snapshot dir already exists, refuse overwrite: {snap_dir}")
    snap_dir.mkdir(parents=True)
    normalized = quality["normalized"]
    data = {
        "format_version": FUND_FORMAT_VERSION,
        "snapshot_id": snapshot_id,
        "symbol": symbol,
        "source_url": source_url,
        "fetched_at_utc": fetched_at_utc,
        "n_records": len(normalized),
        "first_funding_time": normalized[0]["fundingTime"],
        "last_funding_time": normalized[-1]["fundingTime"],
        "records": normalized,
    }
    data_path = snap_dir / "data.json"
    data_path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    manifest = {
        "format_version": FUND_FORMAT_VERSION,
        "snapshot_id": snapshot_id,
        "symbol": symbol,
        "source_url": source_url,
        "fetched_at_utc": fetched_at_utc,
        "n_records": len(normalized),
        "first_funding_time": data["first_funding_time"],
        "last_funding_time": data["last_funding_time"],
        "data_sha256": _sha256_file(data_path),
        "data_bytes": data_path.stat().st_size,
        "quality_passed": True,
        "missing_steps": quality["missing_steps"],
        "notes": quality["notes"],
        "scope_note": (
            "仅最小规模数据管道验证样本：不得用于恢复 CA-1/P4 研究，"
            "不得执行资金费率策略回测，不得直接用作策略收益证据。"),
    }
    manifest_path = snap_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True),
                             encoding="utf-8")
    os.chmod(data_path, 0o444)
    os.chmod(manifest_path, 0o444)
    append_funding_ledger(state_dir, manifest)
    return manifest


def verify_funding_snapshot(snap_dir: str | Path) -> dict:
    """复核：重算哈希、比对 manifest、重跑质量检查（now 取末笔 +8h）。"""
    snap_dir = Path(snap_dir)
    data_path = snap_dir / "data.json"
    manifest_path = snap_dir / "manifest.json"
    if not data_path.exists() or not manifest_path.exists():
        return {"ok": False, "reason": "missing data.json or manifest.json"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = json.loads(data_path.read_text(encoding="utf-8"))
    actual_sha = _sha256_file(data_path)
    hash_ok = actual_sha == manifest["data_sha256"]
    quality = validate_funding_records(
        data["records"], manifest["symbol"],
        now_ms=data["records"][-1]["fundingTime"] + STEP_MS)
    ok = (hash_ok and quality["passed"]
          and manifest["n_records"] == len(data["records"])
          and manifest["first_funding_time"] == data["records"][0]["fundingTime"]
          and manifest["last_funding_time"] == data["records"][-1]["fundingTime"])
    return {"ok": ok, "hash_ok": hash_ok, "actual_sha256": actual_sha,
            "manifest_sha256": manifest["data_sha256"],
            "quality_passed": quality["passed"],
            "quality_issues": quality["issues"],
            "n_records": len(data["records"]),
            "snapshot_id": manifest["snapshot_id"]}


def append_funding_ledger(state_dir: str | Path, manifest: dict) -> None:
    """资金费版本记录：只追加 JSONL 行，永不改写历史行。"""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "snapshot_id": manifest["snapshot_id"],
        "fetched_at_utc": manifest["fetched_at_utc"],
        "symbol": manifest["symbol"],
        "n_records": manifest["n_records"],
        "data_sha256": manifest["data_sha256"],
        "quality_passed": manifest["quality_passed"],
    }, sort_keys=True)
    with (state_dir / "funding-ledger.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
