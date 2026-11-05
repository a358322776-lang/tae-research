"""资金费记录门禁（B2-FIX）：三项检查，程序化、可测试。

只查三项——重复时间戳、8h 网格对齐（容差 60s，含已知的
-5ms~+47ms 时间戳抖动）、异常值（|rate| > 0.01 报错）。
不查结算完整性：完整性仍由统一模型 check_funding_coverage
负责，本模块不得重复、不得与之冲突（缺口语义 coverage_gap
保持不变）。

空记录列表按空 vacuously 通过门禁（无重复、无错位、无异常），
覆盖缺口仍由统一模型判定；records=None 时 price_trade 跳过
门禁，保持 funding_status="unknown" 语义。
"""

from __future__ import annotations

GRID_MS = 8 * 3600 * 1000
TOLERANCE_MS = 60_000
MAX_ABS_RATE = 0.01


class FundingGateError(ValueError):
    """资金费记录未通过三项检查。"""


def check_funding_records(
        records: list[tuple[int, float]]) -> dict:
    """三项检查；通过返回摘要，失败抛 FundingGateError。"""
    seen: set[int] = set()
    max_abs_rate = 0.0
    max_jitter_ms = 0
    for ts, rate in records:
        if ts in seen:
            raise FundingGateError(f"duplicate funding timestamp: {ts}")
        seen.add(ts)
        r = ts % GRID_MS
        jitter = min(r, GRID_MS - r)
        max_jitter_ms = max(max_jitter_ms, jitter)
        if jitter > TOLERANCE_MS:
            raise FundingGateError(
                f"funding timestamp off 8h grid by {jitter}ms "
                f"(tolerance {TOLERANCE_MS}ms): {ts}")
        if abs(rate) > MAX_ABS_RATE:
            raise FundingGateError(
                f"anomalous funding rate |{rate}| > {MAX_ABS_RATE} at {ts}")
        max_abs_rate = max(max_abs_rate, abs(rate))
    return {"n": len(records), "max_abs_rate": max_abs_rate,
            "max_jitter_ms": max_jitter_ms,
            "grid_tolerance_ms": TOLERANCE_MS}
