"""独立验证器（Stage 1 第四项，G4）。

只用 Python 标准库，与任何回测引擎无共享代码：成本/资金费/回撤等
参考算术在此独立重写（与 engine_verification.py 的重写有意重复，
避免“同一份参考代码的 bug 同时污染引擎与验证器”）。

验证器只“检查”，不“修复”、不“运行策略”：它接收引擎函数的输出
或数据，返回 {passed, findings}；任何一项失败即整项不通过。
验证标准来自密封文件 validation-standards-v1.json：文件内容被改
而哈希记录未同步更新时，验证器拒绝运行（见 load_sealed_standards）。
这只能做到“改动可发现”，不是访问控制——root 仍可同时改两处，
但改动会留在 git 历史里。这一点如实记录，不夸大。

覆盖（用户 2026-11-04 12:43 授权第一条）：
1. 训练/验证/最终测试集时间边界；
2. 数据时间戳、可用时间、信号时间；
3. 未来函数与标签重叠；
4. OHLC 字段顺序与类型契约（含 D-ENG-1 回归）；
5. 成交时序、手续费、滑点、资金费率；
6. 基准比较与结果复现；
7. 最终测试数据与验证标准的防篡改（哈希密封 + 复核）。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path


class ValidationBlocked(Exception):
    """密封标准或密封目录被篡改：拒绝验证，不给出通过结论。"""


class ContractError(ValueError):
    """OHLC 字段契约违反（类型/顺序/数值非法）。"""


# ---------------------------------------------------------- 密封标准
def load_sealed_standards(standards_path: str | Path,
                          hash_path: str | Path) -> dict:
    """读验证标准并校验 SHA256 记录；不符即拒绝（不降级为警告）。"""
    standards_path = Path(standards_path)
    recorded = Path(hash_path).read_text(encoding="utf-8").strip().split()[0]
    actual = hashlib.sha256(standards_path.read_bytes()).hexdigest()
    if actual != recorded:
        raise ValidationBlocked(
            f"validation standards tampered: recorded {recorded}, "
            f"actual {actual}; refusing to validate")
    return json.loads(standards_path.read_text(encoding="utf-8"))


def seal_directory(directory: str | Path, manifest_path: str | Path) -> dict:
    """为目录内全部文件写哈希清单（最终测试集保护：改动可发现）。"""
    directory = Path(directory)
    entries = {}
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        entries[str(path.relative_to(directory))] = hashlib.sha256(
            path.read_bytes()).hexdigest()
    manifest = {"files": entries}
    Path(manifest_path).write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                   encoding="utf-8")
    return manifest


def verify_sealed_directory(directory: str | Path,
                            manifest_path: str | Path) -> dict:
    """复核密封目录：返回 changed / missing / added 列表与是否通过。"""
    directory = Path(directory)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    recorded = manifest["files"]
    current = {}
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        if path.resolve() == Path(manifest_path).resolve():
            continue
        current[str(path.relative_to(directory))] = hashlib.sha256(
            path.read_bytes()).hexdigest()
    changed = sorted(k for k in recorded if k in current and current[k] != recorded[k])
    missing = sorted(k for k in recorded if k not in current)
    added = sorted(k for k in current if k not in recorded)
    return {"passed": not (changed or missing or added),
            "changed": changed, "missing": missing, "added": added}


# ---------------------------------------------------------- OHLC 契约
@dataclass(frozen=True)
class Bar:
    """一根已收盘 K 线：字段名显式，位置元组只在边界处转换。

    任何“行数组 -> 策略输入”的转换必须经过 Bar.from_* + to_leg_day，
    不得直接把原始行元组传给按另一种顺序解包的函数——D-ENG-1 的教训。
    """
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    close_time: int | None = None

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in
                   (self.open, self.high, self.low, self.close, self.volume)):
            raise ContractError(f"non-finite price/volume in bar: {self}")
        if self.open <= 0 or self.high <= 0 or self.low <= 0 or self.close <= 0:
            raise ContractError(f"non-positive price in bar: {self}")
        if self.volume < 0:
            raise ContractError(f"negative volume in bar: {self}")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close) \
                or self.high < self.low:
            raise ContractError(
                f"high/low does not contain open/close: {self}")

    @classmethod
    def from_ohlc_row(cls, row, *, order: str = "OHLC") -> "Bar":
        """行数组 -> Bar。order 必须显式声明，默认 OHLC。

        OHLC: (open_time?, open, high, low, close, ...)，open_time 可缺省
        （此时 open_time=0 且调用方须另行校验时间）。
        OLHC: (open, low, high, close) 仅用于 C5 腿函数约定等历史接口，
        须在调用处写明，不得默认。
        """
        if order == "OHLC":
            if len(row) == 4:
                # (open, high, low, close)，无时间列，open_time 置 0，
                # 调用方须另行校验时间（见 check_bars）。
                return cls(open_time=0, open=float(row[0]), high=float(row[1]),
                           low=float(row[2]), close=float(row[3]))
            if len(row) >= 6 and float(row[0]) > 1e12:
                # 含毫秒时间戳的行：(open_time, open, high, low, close, ...)。
                return cls(open_time=int(row[0]), open=float(row[1]),
                           high=float(row[2]), low=float(row[3]),
                           close=float(row[4]),
                           volume=float(row[5]) if len(row) > 5 else 0.0)
            raise ContractError(
                "ambiguous OHLC row length/order: use 4-col (open, high, "
                "low, close), klines 12-col via from_klines_row, or named "
                f"dict via from_dict; got {row!r}")
        if order == "OLHC":
            if len(row) < 4:
                raise ContractError(f"OLHC row too short: {row!r}")
            return cls(open_time=0, open=float(row[0]), low=float(row[1]),
                       high=float(row[2]), close=float(row[3]))
        raise ContractError(f"unknown row order: {order!r}")

    @classmethod
    def from_klines_row(cls, row) -> "Bar":
        """币安 klines 12 列行：[open_time, open, high, low, close, volume,
        close_time, quote_volume, n_trades, taker_buy_base, taker_buy_quote, ignore]。"""
        if len(row) < 7:
            raise ContractError(f"klines row too short: {row!r}")
        return cls(open_time=int(row[0]), open=float(row[1]),
                   high=float(row[2]), low=float(row[3]), close=float(row[4]),
                   volume=float(row[5]), close_time=int(row[6]))

    @classmethod
    def from_dict(cls, d: dict) -> "Bar":
        """字典行：必须用字段名，不得用位置。"""
        try:
            return cls(open_time=int(d["open_time"]), open=float(d["open"]),
                       high=float(d["high"]), low=float(d["low"]),
                       close=float(d["close"]),
                       volume=float(d.get("volume", 0.0)),
                       close_time=(int(d["close_time"])
                                   if d.get("close_time") is not None else None))
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(f"dict bar missing/invalid fields: {d!r}") from exc

    def to_leg_day(self) -> tuple:
        """腿函数约定 (open, low, high, close)：唯一允许的元组出口。"""
        return (self.open, self.low, self.high, self.close)

    def to_ohlc_tuple(self) -> tuple:
        """标准 OHLC 元组 (open, high, low, close)。"""
        return (self.open, self.high, self.low, self.close)


def check_bars(bars: list[Bar], step_ms: int | None = None,
               cutoff_ms: int | None = None) -> dict:
    """时间戳/缺口/重复/未来 bar 检查。返回 {passed, findings}。"""
    findings: list[str] = []
    if not bars:
        return {"passed": False, "findings": ["empty bar list"]}
    times = [b.open_time for b in bars]
    if times != sorted(times):
        findings.append("open_time not sorted")
    if len(set(times)) != len(times):
        findings.append("duplicate open_time")
    if step_ms is not None:
        for prev, cur in zip(times, times[1:]):
            if cur - prev != step_ms:
                findings.append(f"gap/step mismatch: {prev} -> {cur} (step {step_ms})")
    if cutoff_ms is not None:
        for b in bars:
            if b.open_time > cutoff_ms:
                findings.append(f"bar after cutoff: open_time {b.open_time} > {cutoff_ms}")
            if b.close_time is not None and b.close_time > cutoff_ms:
                findings.append(f"bar close_time after cutoff: {b.close_time} > {cutoff_ms}")
    return {"passed": not findings, "findings": findings}


def audit_day_builder(build_days, bars: list[Bar]) -> dict:
    """D-ENG-1 类边界审计：引擎的 days 构造器必须等于 Bar 契约转换。

    build_days: callable(list[Bar]) -> list[tuple]，引擎实际用的构造方式。
    参考：[b.to_leg_day() for b in bars]。任一元素不等即判缺陷。
    """
    reference = [b.to_leg_day() for b in bars]
    try:
        engine_days = build_days(bars)
    except Exception as exc:  # noqa: BLE001 - 构造失败本身就是 findings
        return {"passed": False, "findings": [f"day builder raised: {exc!r}"],
                "engine_days": None, "reference_days": reference}
    findings = []
    if len(engine_days) != len(reference):
        findings.append(
            f"day count mismatch: engine {len(engine_days)} vs reference {len(reference)}")
    for idx, (got, ref) in enumerate(zip(engine_days, reference)):
        if tuple(got) != ref:
            findings.append(
                f"day {idx}: engine {tuple(got)} != contract {ref} "
                f"(field-order mismatch, D-ENG-1 class)")
    return {"passed": not findings, "findings": findings,
            "engine_days": engine_days, "reference_days": reference}


# ---------------------------------------------------------- 时间边界
def check_split(train: tuple[int, int], validation: tuple[int, int],
                test: tuple[int, int]) -> dict:
    """训练/验证/最终测试时间边界：严格有序、互不重叠。"""
    findings = []
    for name, (start, end) in (("train", train), ("validation", validation),
                               ("test", test)):
        if start >= end:
            findings.append(f"{name} interval empty/reversed: {(start, end)}")
    if train[1] > validation[0]:
        findings.append("train overlaps validation")
    if validation[1] > test[0]:
        findings.append("validation overlaps test")
    if train[1] > test[0]:
        findings.append("train overlaps test")
    return {"passed": not findings, "findings": findings}


def check_event_within_split(event_start: int, event_end: int,
                             segment: tuple[int, int]) -> dict:
    """事件窗口（含持有期）不得横跨数据集边界。"""
    seg_start, seg_end = segment
    ok = seg_start <= event_start and event_end <= seg_end
    return {"passed": ok,
            "findings": [] if ok else [
                f"event {(event_start, event_end)} straddles segment "
                f"{segment} boundary"]}


def check_availability(signal_close_ms: int, execution_ms: int,
                       data_available_ms: int) -> dict:
    """成交不得早于信号 bar 收盘、不得早于数据可用时间。"""
    findings = []
    if execution_ms < signal_close_ms:
        findings.append(
            f"execution {execution_ms} before signal bar close {signal_close_ms}")
    if execution_ms < data_available_ms:
        findings.append(
            f"execution {execution_ms} before data available {data_available_ms}")
    return {"passed": not findings, "findings": findings}


def check_no_label_overlap(feature_end_ms: int, label_start_ms: int) -> dict:
    """标签窗口不得在特征窗口结束前开始（标签泄漏）。"""
    ok = label_start_ms >= feature_end_ms
    return {"passed": ok,
            "findings": [] if ok else [
                f"label starts {label_start_ms} before features end "
                f"{feature_end_ms}"]}


# ---------------------------------------------------------- 静态扫描（辅助，非证明）
_RISKY_PATTERNS = [
    (re.compile(r"\[\s*[A-Za-z_]\w*\s*\+\s*1\s*\]"), "future index [x+1]"),
    (re.compile(r"\.shift\(\s*-"), "pandas shift(-1) (future)"),
    (re.compile(r"np\.roll\s*\("), "np.roll (wraps future into past)"),
    (re.compile(r"\[\s*:\s*-1\s*\]"), "slice [:-1] paired with future use? review"),
    (re.compile(r"iloc\[\s*:\s*,\s*-1\s*\]"), "iloc future column? review"),
]


def static_scan(source: str) -> dict:
    """源码风险模式扫描：只产 REVIEW 级 findings，绝不单独判通过/不通过。

    D-ENG-1 不含上述任何模式——静态扫描测不到它，须靠 audit_day_builder
    这类行为级边界审计。扫描结果只用于提示人工复核点。
    """
    findings = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.split("#", 1)[0]
        for pattern, label in _RISKY_PATTERNS:
            if pattern.search(stripped):
                findings.append(f"line {lineno}: {label}: {line.strip()[:120]}")
    return {"passed": True, "findings": findings,
            "note": "static scan is advisory only; absence of findings proves nothing"}


# ---------------------------------------------------------- 成交/成本/资金费
def expected_stop_exit_px(stop: float, direction: int,
                          adverse_cost: float) -> float:
    """止损成交价参考：多头 stop*(1-cost)，空头 stop*(1+cost)。"""
    if direction == 1:
        return stop * (1 - adverse_cost)
    if direction == -1:
        return stop * (1 + adverse_cost)
    raise ValueError(f"bad direction: {direction}")


def check_stop_exit(stop: float, direction: int, exit_px: float,
                    adverse_cost: float, tol: float = 1e-9) -> dict:
    """止损成交价须等于止损价经不利成本调整后的值（容差内）。"""
    expected = expected_stop_exit_px(stop, direction, adverse_cost)
    ok = abs(exit_px - expected) <= tol
    return {"passed": ok,
            "findings": [] if ok else [
                f"stop exit {exit_px} != expected {expected} "
                f"(stop {stop}, dir {direction}, cost {adverse_cost})"]}


def check_fee_r(fee_r: float, stop_distance_pct: float, fee_rate: float,
                sides: int = 2, tol: float = 1e-12) -> dict:
    """手续费（R 单位）= sides * fee_rate / stop_distance_pct。"""
    expected = sides * fee_rate / stop_distance_pct
    ok = abs(fee_r - expected) <= tol
    return {"passed": ok,
            "findings": [] if ok else [
                f"fee_r {fee_r} != expected {expected}"]}


def funding_exact_sum(records: list[tuple[int, float]], t0: int, t1: int) -> float:
    """(t0, t1] 内结算费率精确和（独立重写）。"""
    return sum(r for (t, r) in records if t0 < t <= t1)


def check_funding_interval(records: list[tuple[int, float]], t0: int, t1: int,
                           lo: float, hi: float, tol: float = 1e-12) -> dict:
    """资金费区间须包含全部前缀和极值（stop 日不确定性的正确界定）。

    records 为窗口内按时间排序的 (t, rate)；前缀和从 t0 起累积。
    """
    window = [(t, r) for (t, r) in records if t0 < t <= t1]
    prefixes, run = [], 0.0
    for _, r in window:
        run += r
        prefixes.append(run)
    if not prefixes:
        return {"passed": abs(lo) <= tol and abs(hi) <= tol,
                "findings": ["empty funding window"] if (lo or hi) else []}
    p_lo, p_hi = min(prefixes), max(prefixes)
    ok = lo <= p_lo + tol and hi >= p_hi - tol and lo <= hi
    return {"passed": ok,
            "findings": [] if ok else [
                f"funding interval [{lo}, {hi}] does not contain prefix "
                f"extremes [{p_lo}, {p_hi}]"]}


def check_drawdown(equity: list[float], reported_mdd: float,
                   tol: float = 1e-12) -> dict:
    """回撤参考：峰值后最大跌幅（绝对值，独立重写）。"""
    peak, dd = -math.inf, 0.0
    for v in equity:
        peak = max(peak, v)
        dd = max(dd, peak - v)
    ok = abs(dd - reported_mdd) <= tol
    return {"passed": ok,
            "findings": [] if ok else [f"mdd {reported_mdd} != recomputed {dd}"]}


# ---------------------------------------------------------- 基准与复现
def check_reproducibility(fn, *args, **kwargs) -> dict:
    """同一输入两次运行须逐项相等（确定性）。"""
    first = fn(*args, **kwargs)
    second = fn(*args, **kwargs)
    ok = first == second
    return {"passed": ok,
            "findings": [] if ok else [f"non-deterministic: {first!r} != {second!r}"]}


def benchmark_return(closes: list[float]) -> float:
    """买入持有收益参考：末收/首收 - 1（仅收盘价，无未来数据）。"""
    if len(closes) < 2 or closes[0] <= 0:
        raise ValueError("benchmark needs >=2 positive closes")
    return closes[-1] / closes[0] - 1


def check_benchmark(closes: list[float], reported: float,
                    tol: float = 1e-12) -> dict:
    """报告的基准收益须等于同期收盘价重算值。"""
    expected = benchmark_return(closes)
    ok = abs(reported - expected) <= tol
    return {"passed": ok,
            "findings": [] if ok else [
                f"benchmark {reported} != recomputed {expected}"]}
