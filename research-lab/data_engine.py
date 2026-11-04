"""数据快照与只读连通性：质量检查、哈希 manifest、只读冻结、版本记录。

仅用 Python 标准库。本轮不安装任何依赖（ccxt / pyarrow / duckdb 的安装
须另行申请，见实施方案 v1.1 §9 与用户 2026-11-04 12:26 授权第 6 条）。
不读、不写任何交易接口签名路径，不接触 API Key，不访问账户/持仓/下单类路径。
只访问公开行情接口（klines / fundingRate / ping），无 key、无签名、无 query 签名参数。
快照数据文件只写本地-only 目录 research-lab/state/，永不进仓；
进仓的只有代码、测试与验收记录（含哈希与计数，不含原始行情）。
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

FORMAT_VERSION = "snapshot-v1"
MIRROR_KLINES = "https://www.binance.com/fapi/v1/klines"
MIRROR_FUNDING = "https://www.binance.com/fapi/v1/fundingRate"
FAPI_PING = "https://fapi.binance.com/fapi/v1/ping"
MIRROR_PING = "https://www.binance.com/fapi/v1/ping"

# 只读探针只允许这三个主机。测试用的本地服务器须显式传入 allowed_hosts。
ALLOWED_HOSTS = {"www.binance.com", "fapi.binance.com"}
_USER_AGENT = "muse-research-lab/1.0 (read-only public-market snapshot probe)"

INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class FetchError(Exception):
    """公开接口只读取数失败（状态码 / 超时 / 非法 URL 均归为此类，不重试）。"""


def _check_url(url: str, allowed_hosts: set[str]) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise FetchError(f"only https allowed: {url}")
    if parsed.hostname not in allowed_hosts:
        raise FetchError(f"host not allowlisted: {parsed.hostname}")
    query = urllib.parse.parse_qs(parsed.query)
    for banned in ("signature", "apiKey", "apikey", "timestamp", "recvWindow"):
        if banned in query:
            raise FetchError(f"signed/auth query parameter rejected: {banned}")
    if parsed.username or parsed.password:
        raise FetchError("credentials in URL rejected")
    return parsed


def fetch_json(url: str, timeout: int = 15,
               allowed_hosts: set[str] | None = None) -> object:
    """单次只读 GET，返回解析后的 JSON。不重试、不跟随签名、不带任何密钥。"""
    _check_url(url, allowed_hosts or ALLOWED_HOSTS)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"request failed for {url}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FetchError(f"non-JSON response for {url}") from exc


def fetch_klines(base_url: str, symbol: str, interval: str, limit: int,
                 timeout: int = 15,
                 allowed_hosts: set[str] | None = None) -> list:
    """取公开 klines 原始数组。limit  clamp 到 1..500（最小必要原则）。"""
    if interval not in INTERVAL_MS:
        raise FetchError(f"unsupported interval: {interval}")
    if not 1 <= limit <= 500:
        raise FetchError(f"limit out of range 1..500: {limit}")
    if not symbol.isalnum() or not symbol:
        raise FetchError(f"invalid symbol: {symbol!r}")
    query = urllib.parse.urlencode(
        {"symbol": symbol, "interval": interval, "limit": limit})
    data = fetch_json(f"{base_url}?{query}", timeout=timeout,
                      allowed_hosts=allowed_hosts)
    if not isinstance(data, list):
        raise FetchError("klines response is not a list")
    return data


def probe(url: str, timeout: int = 15,
          allowed_hosts: set[str] | None = None) -> dict:
    """最小只读探针：只记录状态码、耗时、字节数，不保存响应体（不含行情）。"""
    _check_url(url, allowed_hosts or ALLOWED_HOSTS)
    started = time.monotonic()
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return {"url": url, "status": resp.status,
                    "latency_ms": round((time.monotonic() - started) * 1000, 1),
                    "body_bytes": len(body), "error": None,
                    "fetched_at_utc": fetched_at}
    except urllib.error.HTTPError as exc:
        return {"url": url, "status": exc.code,
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "body_bytes": len(exc.read() or b""), "error": f"HTTP {exc.code}",
                "fetched_at_utc": fetched_at}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"url": url, "status": None,
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "body_bytes": 0, "error": str(exc),
                "fetched_at_utc": fetched_at}


def _to_float(value: object, field: str, issues: list[str]) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        issues.append(f"non-numeric {field}: {value!r}")
        return None


def _to_int(value: object, field: str, issues: list[str]) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        issues.append(f"non-integer {field}: {value!r}")
        return None


def validate_bars(bars: list, interval: str,
                  now_ms: int | None = None) -> dict:
    """数据质量检查（C5 '缺 High/Low 不得默认为未触发' 规则的通用化）。

    检查：形状、数值、high/low 包含关系、close_time 步长、时间单调、
    重复、缺口、仅收盘 bar。返回 {passed, checks, gaps, duplicates, issues}。
    任何一项失败即 passed=False；调用方不得用失败数据建快照。
    """
    step = INTERVAL_MS[interval]
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    checks: list[dict] = []
    issues: list[str] = []
    gaps: list[int] = []
    duplicates: list[int] = []
    normalized: list[dict] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    if not bars:
        record("non_empty", False, "0 bars")
        return {"passed": False, "checks": checks, "gaps": gaps,
                "duplicates": duplicates, "issues": ["empty bar list"],
                "n_bars": 0, "normalized": normalized}

    seen: dict[int, int] = {}
    prev_open: int | None = None
    for idx, bar in enumerate(bars):
        if not isinstance(bar, (list, tuple)) or len(bar) < 11:
            issues.append(f"bar {idx}: bad shape len={len(bar) if isinstance(bar, (list, tuple)) else 'n/a'}")
            continue
        open_time = _to_int(bar[0], "open_time", issues)
        close_time = _to_int(bar[6], "close_time", issues)
        o = _to_float(bar[1], "open", issues)
        h = _to_float(bar[2], "high", issues)
        lo = _to_float(bar[3], "low", issues)
        c = _to_float(bar[4], "close", issues)
        vol = _to_float(bar[5], "volume", issues)
        if None in (open_time, close_time, o, h, lo, c, vol):
            continue
        assert open_time is not None and close_time is not None
        assert o is not None and h is not None and lo is not None
        assert c is not None and vol is not None
        if h < max(o, c) or lo > min(o, c) or h < lo:
            issues.append(f"bar {idx} open_time={open_time}: high/low does not contain open/close")
        if close_time != open_time + step - 1:
            issues.append(
                f"bar {idx} open_time={open_time}: close_time {close_time} != open_time+step-1")
        if close_time >= now_ms:
            issues.append(f"bar {idx} open_time={open_time}: unclosed/future bar (close_time >= now)")
        if vol < 0:
            issues.append(f"bar {idx}: negative volume")
        if open_time in seen:
            duplicates.append(open_time)
        seen[open_time] = idx
        if prev_open is not None and open_time <= prev_open:
            issues.append(f"bar {idx}: open_time not strictly increasing")
        prev_open = open_time
        normalized.append({
            "open_time": open_time, "open": o, "high": h, "low": lo,
            "close": c, "volume": vol, "close_time": close_time,
            "quote_volume": _to_float(bar[7], "quote_volume", issues),
            "n_trades": _to_int(bar[8], "n_trades", issues),
        })

    opens = sorted(seen)
    for prev, cur in zip(opens, opens[1:]):
        expected = prev + step
        while expected < cur:
            gaps.append(expected)
            expected += step

    record("shape_and_numeric", not issues, f"{len(normalized)}/{len(bars)} bars normalized")
    record("no_duplicates", not duplicates, f"duplicates={duplicates}")
    record("no_gaps", not gaps, f"gaps={gaps}")
    record("high_low_contains", not any("high/low" in i for i in issues),
           "high>=max(open,close), low<=min(open,close)")
    record("only_closed_bars", not any("unclosed" in i for i in issues),
           "all close_time < now")
    passed = all(c["passed"] for c in checks) and not issues
    return {"passed": passed, "checks": checks, "gaps": gaps,
            "duplicates": duplicates, "issues": issues,
            "n_bars": len(normalized), "normalized": normalized}


def drop_unclosed_bars(bars: list, now_ms: int) -> tuple[list, int]:
    """丢弃未收盘 bar（close_time >= now）。仅在取数层调用；
    质量检查本身仍拒绝未收盘 bar（规则不放宽），被丢弃数须记入 manifest。"""
    closed = [b for b in bars if int(b[6]) < now_ms]
    return closed, len(bars) - len(closed)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def next_snapshot_id(state_dir: str | Path, date_str: str) -> str:
    """SNAP-YYYYMMDD-NNN：按当日已有快照目录数顺延，永不复用已用 ID。"""
    snap_root = Path(state_dir) / "snapshots"
    existing = sorted(p.name for p in snap_root.glob(f"SNAP-{date_str}-*")) if snap_root.exists() else []
    return f"SNAP-{date_str}-{len(existing) + 1:03d}"


def write_snapshot(state_dir: str | Path, snapshot_id: str, symbol: str,
                   interval: str, bars: list, source_url: str,
                   fetched_at_utc: str,
                   extra_manifest: dict | None = None) -> dict:
    """写快照：先质量检查，通过后写 data.json + manifest.json 并设只读。

    快照目录已存在即拒绝（永不覆盖）。data.json 存归一化 bar；
    manifest 含 SHA256、来源、窗口、质量结论与“历史可交易集合未声明”注记。
    """
    quality = validate_bars(bars, interval)
    if not quality["passed"]:
        raise ValueError(f"quality check failed, snapshot refused: {quality['issues']}")
    snap_dir = Path(state_dir) / "snapshots" / snapshot_id
    if snap_dir.exists():
        raise FileExistsError(f"snapshot dir already exists, refuse overwrite: {snap_dir}")
    snap_dir.mkdir(parents=True)
    data = {
        "format_version": FORMAT_VERSION,
        "snapshot_id": snapshot_id,
        "symbol": symbol,
        "interval": interval,
        "source_url": source_url,
        "fetched_at_utc": fetched_at_utc,
        "n_bars": quality["n_bars"],
        "first_open_time": quality["normalized"][0]["open_time"],
        "last_open_time": quality["normalized"][-1]["open_time"],
        "bars": quality["normalized"],
    }
    data_path = snap_dir / "data.json"
    data_path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    manifest = {
        "format_version": FORMAT_VERSION,
        "snapshot_id": snapshot_id,
        "symbol": symbol,
        "interval": interval,
        "source_url": source_url,
        "fetched_at_utc": fetched_at_utc,
        "n_bars": quality["n_bars"],
        "first_open_time": data["first_open_time"],
        "last_open_time": data["last_open_time"],
        "data_sha256": _sha256_file(data_path),
        "data_bytes": data_path.stat().st_size,
        "quality_passed": True,
        "gaps": quality["gaps"],
        "duplicates": quality["duplicates"],
        "tradable_pool_note": (
            "历史可交易集合未声明：本快照仅为连通性验证样本，"
            "不得用作历史可交易集合证据，不得直接代表历史可交易币种集合。"),
    }
    if extra_manifest:
        manifest.update(extra_manifest)
    manifest_path = snap_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True),
                             encoding="utf-8")
    # 只读冻结：文件 0o444。目录保持可写以便追加审计记录时不误伤快照本身
    # 的不可变语义由“目录已存在即拒绝覆盖”与哈希复核共同保证。
    os.chmod(data_path, 0o444)
    os.chmod(manifest_path, 0o444)
    append_ledger(state_dir, manifest)
    return manifest


def verify_snapshot(snap_dir: str | Path) -> dict:
    """复核快照：重算哈希、比对 manifest、重跑质量检查。任一项不符即失败。"""
    snap_dir = Path(snap_dir)
    data_path = snap_dir / "data.json"
    manifest_path = snap_dir / "manifest.json"
    if not data_path.exists() or not manifest_path.exists():
        return {"ok": False, "reason": "missing data.json or manifest.json"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = json.loads(data_path.read_text(encoding="utf-8"))
    actual_sha = _sha256_file(data_path)
    hash_ok = actual_sha == manifest["data_sha256"]
    # 重建原始数组形式跑质量检查（归一化 bar -> 12 列数组的等价重建）。
    bars = [[b["open_time"], b["open"], b["high"], b["low"], b["close"],
             b["volume"], b["close_time"], b["quote_volume"], b["n_trades"],
             0, 0, 0] for b in data["bars"]]
    # 仅收盘检查须用“快照之后”的 now：用 last close_time 之后 1 步作为 now，
    # 避免历史快照在日后复核时被误判为未来 bar。
    step = INTERVAL_MS[manifest["interval"]]
    quality = validate_bars(bars, manifest["interval"],
                            now_ms=data["bars"][-1]["close_time"] + step)
    ok = (hash_ok and quality["passed"]
          and manifest["n_bars"] == len(data["bars"])
          and manifest["first_open_time"] == data["bars"][0]["open_time"]
          and manifest["last_open_time"] == data["bars"][-1]["open_time"])
    return {"ok": ok, "hash_ok": hash_ok,
            "actual_sha256": actual_sha,
            "manifest_sha256": manifest["data_sha256"],
            "quality_passed": quality["passed"],
            "quality_issues": quality["issues"],
            "n_bars": len(data["bars"]),
            "snapshot_id": manifest["snapshot_id"]}


def append_ledger(state_dir: str | Path, manifest: dict) -> None:
    """版本记录：只追加 JSONL 行，永不改写历史行。"""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "snapshot_id": manifest["snapshot_id"],
        "fetched_at_utc": manifest["fetched_at_utc"],
        "symbol": manifest["symbol"],
        "interval": manifest["interval"],
        "n_bars": manifest["n_bars"],
        "data_sha256": manifest["data_sha256"],
        "quality_passed": manifest["quality_passed"],
    }, sort_keys=True)
    with (state_dir / "snapshot-ledger.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def file_modes(snap_dir: str | Path) -> dict:
    """返回快照文件的权限位（供验收记录：应为只读 0o444）。"""
    result = {}
    for name in ("data.json", "manifest.json"):
        path = Path(snap_dir) / name
        if path.exists():
            result[name] = oct(stat.S_IMODE(path.stat().st_mode))
    return result
