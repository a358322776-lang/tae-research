"""TAE-B1 v0.1 引擎：B/C 序列状态机 + 入场/出场模拟 + 统计。

规则唯一来源：rules-v0.1-frozen.md。口径选择（冻结文件未明说处，
本实现的选择，报告中同样列出）：
 P1. 突破须为穿越：前根收盘在带内侧、本根收盘在带外侧（否则 trailing
    窗口新算出的旧带会每根都"突破"）。用检测根当根的带同时衡量两根收盘。
 P2. 回踩期间（b0 之后、收复之前）任何一根 15m 收盘穿越带另一沿即作废，
    无论回踩触及与否（突破失败语义）。
 P3. 同根多带突破：每方向每根只开一个序列，取最贴近现价的带
   （多头取 bhi 最大、空头取 blo 最小）。
 P4. 单仓位模型：序列检测与仓位过滤分离。Phase A 检测全部序列与入场；
    Phase B 按时间顺序用基线（T0×EMA50）出场决定重叠与冷却过滤，
    敏感性 6 档只重算同一批入场的出场，不产生各自的后续序列。
 P5. 止损检查用 5m bar（止损市价单的现实粒度），EMA/SMA 出场用 15m 收盘；
    出场判定从含入场 fill 的 15m bar 的下一根开始；同根内止损天然优先
    （5m 检查先于该 15m 收盘检查）。
 P6. 止损执行价统一为止损价逆势 0.05%（基线滑点），T0/T1/T2 只改变触发
    时机（触及/穿透 0.05%/0.1%），不改变执行价公式。
 P7. EMA/SMA 出场按 taker 0.05% 计费（市价收盘出场，保守于 maker 0.02%）。
 P8. 资金费：结算点 (fill bar open, exit bar close]，名义 = 入场名义，
    多头付正费率、空头收正费率（与净 R 审计同款）。
 P9. 窗口归属按 bar OPEN 时间：open ≤ 2025-10-17T02:00Z 为样本外
    （与 robustness 缓存切分一致），其余为样本内；序列按 b0 open、交易按 fill open。
 P10. 冷却与重叠过滤以入场 fill 时间为准；冷却时长 2h（entry 后 2h 内
    同方向新入场跳过）。
"""
import bisect
import json
import sys

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
from b1_lib import (atr_series, ema50_series, sma20_series, is_signal_bar,
                    BOUNDARY_MS)  # noqa: E402

B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/data_cache"
FEE = 0.0005
STOP_SLIP = 0.0005
TIER_PEN = {"T0": 0.0, "T1": 0.0005, "T2": 0.001}
COMBOS = [(t, e) for t in ("T0", "T1", "T2") for e in ("EMA50", "SMA20")]


class Data:
    def __init__(self):
        d15 = np.load(f"{B1}/stitched_15m.npz")
        d5 = np.load(f"{B1}/stitched_5m.npz")
        self.t15, self.o15 = d15["t"], d15["ohlc"]
        self.t5, self.o5 = d5["t"], d5["ohlc"]
        self.c15 = self.o15[:, 3]
        self.atr15 = atr_series(self.o15)
        self.ema50 = ema50_series(self.c15)
        self.sma20 = sma20_series(self.c15)
        fr = []
        with open(f"{B1}/stitched_funding.csv") as fh:
            next(fh)
            for line in fh:
                ts, rate = line.strip().split(",")
                fr.append((int(ts), float(rate)))
        self.fund_ts = [x[0] for x in fr]
        self.fund_pre = np.cumsum([0.0] + [x[1] for x in fr])

    def funding_sum(self, t0, t1):
        """结算点 in (t0, t1] 的费率和。"""
        i = bisect.bisect_right(self.fund_ts, t0)
        j = bisect.bisect_right(self.fund_ts, t1)
        return float(self.fund_pre[j] - self.fund_pre[i])


def run_group(D, candidates, fix_doji):
    """Phase A：序列检测与入场；Phase B：仓位过滤与 6 档出场模拟。
    candidates: dict j -> list[(dir, blo, bhi)]。返回 (trades, counts)。"""
    t15, o15, t5, o5 = D.t15, D.o15, D.t5, D.o5
    c15 = D.c15
    n15 = len(t15)
    counts = {"seq_started": 0, "voided": 0, "expired": 0, "e_timeout": 0,
              "coincident_void": 0, "missed": 0, "lev_skip": 0, "invalid": 0,
              "filled_entries": 0, "skipped_overlap": 0, "skipped_cooldown": 0,
              "accepted": 0, "unresolved": 0}
    seq_counts = {"oos": dict(counts), "ins": dict(counts)}

    def window_of(open_ms):
        return "oos" if open_ms <= BOUNDARY_MS else "ins"

    # ---- Phase A ----
    active = []  # {dir,blo,bhi,b0,touched,extreme}
    entries = []  # filled entry dicts（未经过仓位过滤）
    for j in range(399, n15):
        cj, hj, lj = float(c15[j]), float(o15[j][1]), float(o15[j][2])
        # 1. 更新已有序列
        nxt = []
        for s in active:
            d = s["dir"]
            if d == "long":
                if cj < s["blo"]:
                    counts["voided"] += 1
                    seq_counts[window_of(int(t15[s["b0"]]))]["voided"] += 1
                    continue
                if not s["touched"]:
                    if lj <= s["bhi"] and hj >= s["blo"]:
                        s["touched"] = True
                        s["extreme"] = lj
                if s["touched"]:
                    s["extreme"] = min(s["extreme"], lj)
                    if cj > s["bhi"]:
                        resolve_sequence(D, s, j, entries, counts, seq_counts, fix_doji)
                        continue
                if j >= s["b0"] + 48:
                    counts["expired"] += 1
                    seq_counts[window_of(int(t15[s["b0"]]))]["expired"] += 1
                    continue
            else:
                if cj > s["bhi"]:
                    counts["voided"] += 1
                    seq_counts[window_of(int(t15[s["b0"]]))]["voided"] += 1
                    continue
                if not s["touched"]:
                    if lj <= s["bhi"] and hj >= s["blo"]:
                        s["touched"] = True
                        s["extreme"] = hj
                if s["touched"]:
                    s["extreme"] = max(s["extreme"], hj)
                    if cj < s["blo"]:
                        resolve_sequence(D, s, j, entries, counts, seq_counts, fix_doji)
                        continue
                if j >= s["b0"] + 48:
                    counts["expired"] += 1
                    seq_counts[window_of(int(t15[s["b0"]]))]["expired"] += 1
                    continue
            nxt.append(s)
        active = nxt
        # 2. 新突破（每方向每根一个，取最贴近现价的带）
        for d in ("long", "short"):
            cands = [c for c in candidates.get(j, []) if c[0] == d]
            if not cands:
                continue
            if d == "long":
                blo, bhi = max(cands, key=lambda c: c[2])[1:]
            else:
                blo, bhi = min(cands, key=lambda c: c[1])[1:]
            overlap = any(s["dir"] == d and not (bhi < s["blo"] or blo > s["bhi"])
                          for s in active)
            if overlap:
                continue
            active.append({"dir": d, "blo": blo, "bhi": bhi, "b0": j,
                           "touched": False, "extreme": None})
            counts["seq_started"] += 1
            seq_counts[window_of(int(t15[j]))]["seq_started"] += 1
    # ---- Phase B ----
    entries.sort(key=lambda e: (e["fill_close_ms"], e["b0"], e["dir"]))
    trades = []
    open_until = -10**18
    cool_until = {"long": -10**18, "short": -10**18}
    for e in entries:
        ft = e["fill_close_ms"]
        if ft < open_until:
            counts["skipped_overlap"] += 1
            continue
        if ft < cool_until[e["dir"]]:
            counts["skipped_cooldown"] += 1
            continue
        outs = {}
        for tier, ex in COMBOS:
            outs[(tier, ex)] = simulate_exit(D, e, tier, ex)
        base = outs[("T0", "EMA50")]
        if base is None:
            # 基线未决 = 持仓至数据结束，后续入场一律视为重叠跳过
            counts["unresolved"] += 1
            open_until = float("inf")
            continue
        counts["accepted"] += 1
        e["outs"] = outs
        e["base"] = base
        trades.append(e)
        open_until = base["exit_close_ms"]
        if base["reason"] == "stop":
            cool_until[e["dir"]] = base["exit_close_ms"] + 2 * 3600 * 1000
    return trades, counts, seq_counts


def resolve_sequence(D, s, r, entries, counts, seq_counts, fix_doji):
    """收复根 r 处的 E 确认 + 入场挂单。r 为 15m 下标。"""
    t15, o15, t5, o5 = D.t15, D.o15, D.t5, D.o5
    d = s["dir"]
    w = "oos" if int(t15[s["b0"]]) <= BOUNDARY_MS else "ins"
    tr_close = int(t15[r]) + 900_000
    m0 = int(np.searchsorted(t5, tr_close, side="left"))
    sig = None
    for k in range(3):
        m = m0 + k
        if m >= len(t5):
            break
        if is_signal_bar(o5, m, d, fix_doji):
            if k == 2:
                # 第 3 根 5m 收盘即下一根 15m 收盘：远沿穿越则作废（保守）
                if r + 1 < len(t15):
                    c_next = float(D.c15[r + 1])
                    if (d == "long" and c_next < s["blo"]) or \
                       (d == "short" and c_next > s["bhi"]):
                        counts["coincident_void"] += 1
                        seq_counts[w]["coincident_void"] += 1
                        return
            sig = m
            break
    if sig is None:
        counts["e_timeout"] += 1
        seq_counts[w]["e_timeout"] += 1
        return
    trig = float(o5[sig][1]) if d == "long" else float(o5[sig][2])
    fill = None
    for m in range(sig + 1, sig + 4):
        if m >= len(t5):
            break
        if (d == "long" and float(o5[m][1]) >= trig) or \
           (d == "short" and float(o5[m][2]) <= trig):
            fill = m
            break
    if fill is None:
        counts["missed"] += 1
        seq_counts[w]["missed"] += 1
        return
    atr_r = float(D.atr15[r])
    if d == "long":
        stop = s["extreme"] - atr_r
    else:
        stop = s["extreme"] + atr_r
    entry = trig
    risk = abs(entry - stop)
    if risk <= 0 or np.isnan(atr_r):
        counts["invalid"] += 1
        seq_counts[w]["invalid"] += 1
        return
    lev = 0.02 / (risk / entry)
    if lev > 20:
        counts["lev_skip"] += 1
        seq_counts[w]["lev_skip"] += 1
        return
    counts["filled_entries"] += 1
    seq_counts[w]["filled_entries"] += 1
    entries.append({
        "dir": d, "b0": s["b0"], "b0_open_ms": int(t15[s["b0"]]),
        "blo": s["blo"], "bhi": s["bhi"],
        "touch_extreme": s["extreme"], "reclaim_idx": r,
        "e_idx": sig, "trigger": trig, "fill_idx": fill,
        "fill_close_ms": int(t5[fill]) + 300_000,
        "fill_open_ms": int(t5[fill]),
        "entry": entry, "stop": stop, "risk": risk,
    })


def simulate_exit(D, e, tier, exit_type):
    """返回 None（未决）或 {exit_close_ms, exit_px, reason}。
    止损用 5m bar 检查；EMA/SMA 用 15m 收盘检查（从含 fill 的 15m bar 下一根起）。"""
    t15, o15, t5, o5 = D.t15, D.o15, D.t5, D.o5
    d, stop = e["dir"], e["stop"]
    pen = TIER_PEN[tier]
    if d == "long":
        thr = stop * (1 - pen)
        ex_px_stop = stop * (1 - STOP_SLIP)
    else:
        thr = stop * (1 + pen)
        ex_px_stop = stop * (1 + STOP_SLIP)
    f_open = int(t5[e["fill_idx"]])
    cont_open = f_open - (f_open % 900_000)
    k0 = int(np.searchsorted(t15, cont_open, side="left"))
    if k0 >= len(t15) or int(t15[k0]) != cont_open:
        return None
    for k in range(k0 + 1, len(t15)):
        mk = int(np.searchsorted(t5, int(t15[k]), side="left"))
        for m in range(mk, min(mk + 3, len(t5))):
            if d == "long" and float(o5[m][2]) <= thr:
                return {"exit_close_ms": int(t5[m]) + 300_000,
                        "exit_px": ex_px_stop, "reason": "stop"}
            if d == "short" and float(o5[m][1]) >= thr:
                return {"exit_close_ms": int(t5[m]) + 300_000,
                        "exit_px": ex_px_stop, "reason": "stop"}
        ref = D.ema50[k] if exit_type == "EMA50" else D.sma20[k]
        if np.isnan(ref):
            continue
        ck = float(D.c15[k])
        if (d == "long" and ck < ref) or (d == "short" and ck > ref):
            return {"exit_close_ms": int(t15[k]) + 900_000,
                    "exit_px": ck, "reason": exit_type}
    return None


def trade_numbers(D, e, out):
    """单笔单档的 R 分解。返回 dict（gross/fee/funding/net）。"""
    d, entry, stop, risk = e["dir"], e["entry"], e["stop"], e["risk"]
    sd = risk / entry
    if d == "long":
        gross = (out["exit_px"] - entry) / risk
    else:
        gross = (entry - out["exit_px"]) / risk
    fee_r = 2 * FEE / sd
    fsum = D.funding_sum(e["fill_open_ms"], out["exit_close_ms"])
    fund_cost = fsum / sd if d == "long" else -fsum / sd
    return {"gross": gross, "fee": fee_r, "funding": fund_cost,
            "net": gross - fee_r - fund_cost}


def stats_for(trades_with_nums):
    """trades_with_nums: list of net R（按入场时间顺序）。返回统计 dict。"""
    import math
    n = len(trades_with_nums)
    if n == 0:
        return {"n": 0}
    wins = [x for x in trades_with_nums if x > 0]
    losses = [x for x in trades_with_nums if x < 0]
    curve, peak, dd = 0.0, 0.0, 0.0
    for x in trades_with_nums:
        curve += x
        peak = max(peak, curve)
        dd = min(dd, curve - peak)
    gp = sum(wins)
    gl = abs(sum(losses))
    return {"n": n, "wins": len(wins), "win_rate": len(wins) / n,
            "avg_net": float(np.mean(trades_with_nums)),
            "total_net": float(sum(trades_with_nums)),
            "max_dd": float(dd),
            "profit_factor": float(gp / gl) if gl > 0 else float("inf")}
