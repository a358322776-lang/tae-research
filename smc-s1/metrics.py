"""指标：净 R、PF、回撤、置信区间、评估门（D5）。

纯函数。置信区间用正态近似（z=1.96），并在文档中注明：正式
评估要求 n≥200 且须同时检查时间相关性；小样本区间仅供参考，
不得据此宣称显著。
"""

from __future__ import annotations

import math
import statistics


def trade_stats(net_rs: list[float]) -> dict:
    n = len(net_rs)
    if n == 0:
        return {"n": 0, "win_rate": None, "mean_net_r": None,
                "profit_factor": None, "max_drawdown_r": 0.0,
                "ci95": None, "lag1_autocorr": None}
    wins = [r for r in net_rs if r > 0]
    losses = [r for r in net_rs if r < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    pf = (gross_profit / gross_loss) if gross_loss > 0 else None
    equity = 0.0
    peak = 0.0
    mdd = 0.0
    for r in net_rs:
        equity += r
        peak = max(peak, equity)
        mdd = max(mdd, peak - equity)
    mean = sum(net_rs) / n
    ci = None
    if n >= 2:
        sd = statistics.stdev(net_rs)
        half = 1.96 * sd / math.sqrt(n)
        ci = (mean - half, mean + half)
    return {"n": n, "win_rate": len(wins) / n, "mean_net_r": mean,
            "profit_factor": pf, "max_drawdown_r": mdd, "ci95": ci,
            "lag1_autocorr": lag1_autocorr(net_rs)}


def lag1_autocorr(series: list[float]) -> float | None:
    """一阶自相关（时间相关性检查）；n<3 或零方差时为 None。"""
    if len(series) < 3:
        return None
    mean = sum(series) / len(series)
    num = sum((series[i] - mean) * (series[i - 1] - mean)
              for i in range(1, len(series)))
    den = sum((x - mean) ** 2 for x in series)
    if den == 0:
        return None
    return num / den


def evaluation_gate(n_completed_trades: int, segment: str) -> dict:
    """D5 评估门：训练段笔数决定允许的动作。

    <100：不允许参数筛选；100–199：仅探索；≥200：正式统计评估
    （须检查置信区间与时间相关性）。样本不足即 INCONCLUSIVE。
    """
    if segment == "final_test":
        return {"status": "blocked",
                "reason": "final test performance is frozen until B3"}
    if n_completed_trades < 100:
        return {"status": "insufficient",
                "verdict": "INCONCLUSIVE",
                "allowed": "none: no parameter screening",
                "reason": f"only {n_completed_trades} completed trades (<100)"}
    if n_completed_trades < 200:
        return {"status": "exploration-only",
                "verdict": None,
                "allowed": "exploration only: no formal claims",
                "reason": f"{n_completed_trades} trades in [100, 200)"}
    return {"status": "formal",
            "verdict": None,
            "allowed": "formal statistical evaluation with CI and "
                       "time-correlation checks",
            "reason": f"{n_completed_trades} trades (>=200)"}
