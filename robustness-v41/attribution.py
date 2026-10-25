#!/usr/bin/env python3
"""ETH v4.1 失败归因（failure attribution）——归因，不调参。

诊断探针、非采纳建议：本脚本第 5 节的止损放宽 / EMA 延迟 / 无止损重算
仅用于度量各部件的责任份额，绝不是改进方案，更不是 v4.2。

口径（与稳健性验证报告一致）：
- 样本外主力：2020-01-01→2025-10-17T02:00Z，T0 触及档已成交 341 单；
  样本内 46 单只作对照。fill_i = signal_i + 1，exit_i / reason 取自
  trades_*_exec.json 的 fills.T0。
- MFE/MAE：持仓内价格路径的极值（15m high/low，fill bar 到 exit bar 全含），
  以止损距离为单位换算成 R。注意：EMA 出场单 exit bar 的极值可能超过出场价
  （价格到过但未在该价出场），故 MFE 是路径描述，不是"本可落袋"的收益。
- 止损打穿幅度：用 exit bar 内 5m 极值度量（5m 缺失时退回 15m）。
- 出场后路径：从 exit_i+1 起算的 5/10/20 根 15m（不含出场根本身）。
- 漂移：以 fill bar 收盘为起点，fill_i+k 根收盘的 signed 收益（R 计），
  不论该单是否已出场——测的是信号本身的方向预测力，不是已实现盈亏。
- 探针费用：复用 v41_engine.net_r（入场 maker 0.02%、出场 taker 0.05%），
  资金费不计（样本外资金费合计仅 -1.18R，约 -0.0035R/单，可忽略）；
  对照基线为 T0_s0 扣除 funding_r 后的均值，保证口径可比。

预设判定标准（写于结果之前，事后不改）：
- H1 入场无优势：P(MFE>=1R) < 35%，且 +3/+5/+10 根漂移均值无显著正值
  （95% CI 含 0 或为负），且信号漂移不明显优于随机基线。
- H2 止损太紧：止损单中 10 根内回撤回开仓价（>=0R）的比例 >= 40%，
  或止损打穿中位数 <= 0.2R（多为擦过）。
- H3 EMA 出场过早：EMA 单中 10 根内延续 >= 1R 的比例 >= 30%，
  或延续中位数 >= 0.5R。

复现：python3 attribution.py（依赖 numpy；数据取 data_cache/ 现成缓存）。
随机种子：20261025（随机基线与 Bootstrap）。
"""
import json
import sys

import numpy as np

sys.path.insert(0, ".")
from v41_engine import ema50_series, net_r, scan_exit_from  # noqa: E402

SEED = 20261025
RNG = np.random.default_rng(SEED)
D = "."
OOS, INS = "oos", "insample"


class NS:
    pass


def load_ns(window):
    z15 = np.load(f"{D}/data_cache/{window}_15m.npz")
    z5 = np.load(f"{D}/data_cache/{window}_5m.npz")
    ns = NS()
    ns.t15 = z15["t"]
    ohlc = z15["ohlc"]
    ns.o15, ns.h15, ns.l15, ns.c15 = ohlc[:, 0], ohlc[:, 1], ohlc[:, 2], ohlc[:, 3]
    o5 = z5["ohlc"]
    ns.t5 = z5["t"]
    ns.o5, ns.h5, ns.l5, ns.c5 = o5[:, 0], o5[:, 1], o5[:, 2], o5[:, 3]
    ns.ema = ema50_series(ns.c15)
    m5 = {int(t): i for i, t in enumerate(ns.t5)}

    def m5_bars(t15):
        idx = [m5.get(int(t15 + k * 300_000)) for k in range(3)]
        if any(v is None for v in idx):
            return None
        return idx

    ns.m5_bars = m5_bars
    return ns


def signed_r(s, price, entry, risk):
    return s * (price - entry) / risk


def boot_ci(x, n=2000, seed=SEED):
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n, len(x)))
    means = x[idx].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def summarize(x):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return {"n": 0}
    return {"n": int(len(x)), "mean": float(x.mean()), "median": float(np.median(x)),
            "sd": float(x.std(ddof=1)) if len(x) > 1 else 0.0,
            "min": float(x.min()), "max": float(x.max()),
            "ci95": boot_ci(x)}


def per_trade(ns, tr):
    """返回逐笔归因字段。fill_i = signal_i + 1（限价下一根成交）。"""
    f = tr["fills"]["T0"]
    fill_i, exit_i = tr["signal_i"] + 1, f["exit_i"]
    s = 1 if tr["dir"] == "long" else -1
    entry, sl, risk = tr["entry"], tr["sl"], tr["risk"]
    o = {"signal_time": tr["signal_time"], "dir": tr["dir"], "entry": entry,
         "sl": sl, "risk": risk, "fill_i": fill_i, "exit_i": exit_i,
         "exit_px": f["exit_px"], "reason": f["reason"],
         "net_s0_exfund": f["s0"] - f["funding_r"]}
    h, l, c = ns.h15, ns.l15, ns.c15
    seg_h = h[fill_i:exit_i + 1]
    seg_l = l[fill_i:exit_i + 1]
    if s == 1:
        o["mfe"] = float(np.max((seg_h - entry) / risk))
        o["mae"] = float(np.min((seg_l - entry) / risk))
    else:
        o["mfe"] = float(np.max((entry - seg_l) / risk))
        o["mae"] = float(np.min((entry - seg_h) / risk))
    # 止损打穿幅度（exit bar 内 5m 极值；缺失退回 15m）
    o["stop_overshoot"] = None
    if f["reason"] == "stop":
        trio = ns.m5_bars(int(ns.t15[exit_i]))
        if trio is not None:
            if s == 1:
                o["stop_overshoot"] = float((sl - min(ns.l5[j] for j in trio)) / risk)
            else:
                o["stop_overshoot"] = float((max(ns.h5[j] for j in trio) - sl) / risk)
        else:
            o["stop_overshoot"] = float((sl - l[exit_i]) / risk) if s == 1 else \
                float((h[exit_i] - sl) / risk)
    # 漂移：fill_i+k 根收盘
    for k in (1, 3, 5, 10):
        j = fill_i + k
        o[f"drift_{k}"] = float(signed_r(s, c[j], entry, risk)) if j < len(c) else None
    # 出场后路径（exit_i+1 起，W 根）
    for W in (5, 10, 20):
        seg = slice(exit_i + 1, min(exit_i + 1 + W, len(c)))
        hh, ll = h[seg], l[seg]
        if len(hh) == 0:
            o[f"post_fav_{W}"] = None
            o[f"post_adv_{W}"] = None
            continue
        if f["reason"] == "stop":
            # 止损单：顺势回撤相对开仓价；逆势继续相对开仓价
            o[f"post_fav_{W}"] = float(np.max((hh - entry) / risk)) if s == 1 else \
                float(np.max((entry - ll) / risk))
            o[f"post_adv_{W}"] = float(np.min((ll - entry) / risk)) if s == 1 else \
                float(np.min((entry - hh) / risk))
        else:
            # EMA 单：延续相对出场价
            ex = f["exit_px"]
            o[f"post_fav_{W}"] = float(np.max((hh - ex) / risk)) if s == 1 else \
                float(np.max((ex - ll) / risk))
            o[f"post_adv_{W}"] = float(np.min((ll - ex) / risk)) if s == 1 else \
                float(np.min((ex - hh) / risk))
    return o


def analyze(ns, exec_json):
    trades = [t for t in json.load(open(exec_json))
              if t["fills"]["T0"]["status"] == "filled"]
    rows = [per_trade(ns, t) for t in trades]
    return trades, rows


def agg(rows, key, mask=None):
    vals = [r[key] for r in rows if r[key] is not None and (mask is None or mask(r))]
    return vals


def prop(vals, thr):
    vals = [v for v in vals if v is not None]
    return float(np.mean([v >= thr for v in vals])) if vals else None


def random_baseline(ns, risk_pcts, n=5000):
    c = ns.c15
    bars = RNG.integers(200, len(c) - 30, size=n)
    dirs = RNG.choice([1, -1], size=n)
    risks = RNG.choice(risk_pcts, size=n)  # 止损距离 % 抽样
    out = {k: [] for k in (1, 3, 5, 10)}
    for b, s, rp in zip(bars, dirs, risks):
        entry = c[b]
        risk = entry * rp / 100.0
        for k in out:
            out[k].append(float(s * (c[b + k] - entry) / risk))
    return out


def probe_scan(ns, tr, mult=None, delay=None, no_stop=False):
    """诊断探针。返回 (exit_px, reason) 或 None（未出场）。
    起点：fill bar 内成交 5m 根之后的剩余 5m 根（与引擎执行器修正同口径）。"""
    f = tr["fills"]["T0"]
    fill_i = tr["signal_i"] + 1
    s = 1 if tr["dir"] == "long" else -1
    entry, risk = tr["entry"], tr["risk"]
    sl = tr["sl"] if mult is None else (
        entry - mult * risk if s == 1 else entry + mult * risk)
    pos = {"dir": tr["dir"], "sl": sl, "entry": entry, "risk": risk}
    if no_stop:
        for j in range(fill_i + 1, len(ns.c15)):
            if np.isnan(ns.ema[j]):
                continue
            if (s == 1 and ns.c15[j] < ns.ema[j]) or (s == -1 and ns.c15[j] > ns.ema[j]):
                return (float(ns.c15[j]), "ema50_close")
        return None
    if delay is not None:
        # 仅对原 EMA 出场单：延迟 d 根，延迟期内止损先判
        base_i = f["exit_i"]
        for j in range(base_i + 1, base_i + 1 + delay):
            if j >= len(ns.c15):
                return None
            trio = ns.m5_bars(int(ns.t15[j]))
            if trio is not None:
                for k in trio:
                    if (s == 1 and ns.l5[k] <= sl) or (s == -1 and ns.h5[k] >= sl):
                        return (sl, "stop")
        j = base_i + delay
        if j >= len(ns.c15):
            return None
        return (float(ns.c15[j]), "ema_delayed")
    trio = ns.m5_bars(int(ns.t15[fill_i]))
    start_5m = None
    if trio is not None:
        fill5 = None
        for k, j in enumerate(trio):
            if (s == 1 and ns.l5[j] <= entry) or (s == -1 and ns.h5[j] >= entry):
                fill5 = k
                break
        start_5m = trio[fill5:] if fill5 is not None else trio
    ex = scan_exit_from(ns, pos, fill_i, start_5m=start_5m)
    return None if ex is None else (float(ex[1]), ex[2])


def main():
    ns_o = load_ns(OOS)
    ns_i = load_ns(INS)
    tr_o, rows_o = analyze(ns_o, f"{D}/data_cache/trades_oos_exec.json")
    tr_i, rows_i = analyze(ns_i, f"{D}/data_cache/trades_insample_exec.json")
    stop_o = [r for r in rows_o if r["reason"] == "stop"]
    ema_o = [r for r in rows_o if r["reason"] == "ema50_close"]
    stop_i = [r for r in rows_i if r["reason"] == "stop"]
    ema_i = [r for r in rows_i if r["reason"] == "ema50_close"]

    out = {"window_oos": "2020-01-01->2025-10-17T02:00Z",
           "window_insample": "2025-10-17->2026-10-22T02:00Z",
           "n_oos": len(rows_o), "n_stop_oos": len(stop_o), "n_ema_oos": len(ema_o),
           "n_insample": len(rows_i), "n_stop_ins": len(stop_i), "n_ema_ins": len(ema_i)}
    # --- H1: MFE/MAE ---
    for name, rows, sub in (("oos", rows_o, None), ("oos_stop", rows_o, lambda r: r["reason"] == "stop"),
                            ("oos_ema", rows_o, lambda r: r["reason"] == "ema50_close"),
                            ("insample", rows_i, None)):
        sel = [r for r in rows if sub is None or sub(r)]
        mfe = [r["mfe"] for r in sel]
        mae = [r["mae"] for r in sel]
        out[f"mfe_{name}"] = summarize(mfe)
        out[f"mae_{name}"] = summarize(mae)
        out[f"mfe_ge_{name}"] = {t: prop(mfe, t) for t in (0.5, 1.0, 2.0)}
    # --- H1: 漂移 + 随机基线 ---
    risk_pcts = [t["stop_dist_pct"] for t in tr_o]
    base = random_baseline(ns_o, risk_pcts)
    for k in (1, 3, 5, 10):
        out[f"drift_oos_{k}"] = summarize(agg(rows_o, f"drift_{k}"))
        out[f"drift_ins_{k}"] = summarize(agg(rows_i, f"drift_{k}"))
        out[f"drift_rand_{k}"] = summarize(base[k])
    # --- H2: 止损后路径 ---
    for W in (5, 10, 20):
        fav = agg(stop_o, f"post_fav_{W}")
        adv = agg(stop_o, f"post_adv_{W}")
        out[f"stop_retrace_{W}"] = summarize(fav)
        out[f"stop_retrace_ge_{W}"] = {t: prop(fav, t) for t in (0.0, 0.5, 1.0)}
        out[f"stop_adv_{W}"] = summarize(adv)
    over = [r["stop_overshoot"] for r in stop_o if r["stop_overshoot"] is not None]
    out["stop_overshoot"] = summarize(over)
    out["stop_overshoot_le02"] = prop(over, 0.0) and float(np.mean([v <= 0.2 for v in over]))
    out["stop_overshoot_gt05"] = float(np.mean([v > 0.5 for v in over])) if over else None
    # --- H3: EMA 出场后延续 ---
    for W in (5, 10, 20):
        fav = agg(ema_o, f"post_fav_{W}")
        out[f"ema_cont_{W}"] = summarize(fav)
        out[f"ema_cont_ge_{W}"] = {t: prop(fav, t) for t in (0.5, 1.0)}
    real = [r["net_s0_exfund"] for r in ema_o]
    # 已实现毛 R（扣除费用前近似：net + fee；直接用 gross = (exit-entry)/risk）
    gross = []
    for r in ema_o:
        s = 1 if r["dir"] == "long" else -1
        gross.append(float(s * (r["exit_px"] - r["entry"]) / r["risk"]))
    out["ema_realized_gross"] = summarize(gross)
    # --- 探针（诊断探针、非采纳建议）---
    base_mean = float(np.mean([r["net_s0_exfund"] for r in rows_o]))
    out["baseline_net_exfund_mean"] = base_mean
    probes = {}
    for label, kw in (("stop_x1.5", {"mult": 1.5}), ("stop_x2", {"mult": 2.0})):
        vals, unresolved = [], 0
        for tr in tr_o:
            ex = probe_scan(ns_o, tr, **kw)
            if ex is None:
                unresolved += 1
                continue
            px, reason = ex
            g, fee = net_r({"entry": tr["entry"], "sl": tr["sl"], "risk": tr["risk"],
                            "dir": tr["dir"]}, px, reason)
            vals.append(g - fee)
        probes[label] = {"n": len(vals), "unresolved": unresolved,
                         "mean": float(np.mean(vals)) if vals else None}
    for d in (1, 2):
        vals, unresolved = [], 0
        for tr, r in zip(tr_o, rows_o):
            if r["reason"] != "ema50_close":
                continue
            ex = probe_scan(ns_o, tr, delay=d)
            if ex is None:
                unresolved += 1
                continue
            px, reason = ex
            g, fee = net_r({"entry": tr["entry"], "sl": tr["sl"], "risk": tr["risk"],
                            "dir": tr["dir"]}, px, reason)
            vals.append(g - fee)
        sub_base = float(np.mean([r["net_s0_exfund"] for r in ema_o]))
        probes[f"ema_delay_{d}"] = {"n": len(vals), "unresolved": unresolved,
                                    "mean": float(np.mean(vals)) if vals else None,
                                    "ema_subset_baseline": sub_base}
    vals, unresolved = [], 0
    for tr in tr_o:
        ex = probe_scan(ns_o, tr, no_stop=True)
        if ex is None:
            unresolved += 1
            continue
        px, reason = ex
        g, fee = net_r({"entry": tr["entry"], "sl": tr["sl"], "risk": tr["risk"],
                        "dir": tr["dir"]}, px, reason)
        vals.append(g - fee)
    probes["no_stop"] = {"n": len(vals), "unresolved": unresolved,
                         "mean": float(np.mean(vals)) if vals else None}
    out["probes"] = probes

    json.dump(out, open(f"{D}/attribution_summary.json", "w"), indent=1, ensure_ascii=False)
    import csv
    with open(f"{D}/attribution_trades.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["window", "signal_time", "dir", "entry", "sl", "risk", "fill_i", "exit_i",
                    "exit_px", "reason", "net_s0_exfund", "mfe", "mae", "stop_overshoot",
                    "drift_1", "drift_3", "drift_5", "drift_10",
                    "post_fav_5", "post_fav_10", "post_fav_20",
                    "post_adv_5", "post_adv_10", "post_adv_20"])
        for win, rows in (("oos", rows_o), ("insample", rows_i)):
            for r in rows:
                w.writerow([win, r["signal_time"], r["dir"], r["entry"], r["sl"], r["risk"],
                            r["fill_i"], r["exit_i"], r["exit_px"], r["reason"],
                            round(r["net_s0_exfund"], 4), round(r["mfe"], 4), round(r["mae"], 4),
                            None if r["stop_overshoot"] is None else round(r["stop_overshoot"], 4),
                            r["drift_1"], r["drift_3"], r["drift_5"], r["drift_10"],
                            r["post_fav_5"], r["post_fav_10"], r["post_fav_20"],
                            r["post_adv_5"], r["post_adv_10"], r["post_adv_20"]])
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
