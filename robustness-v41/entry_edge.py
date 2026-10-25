#!/usr/bin/env python3
"""ETH v4.1 入场优势研究（entry-edge study）——只研究入场，不组装新策略、不动止损出场。

首页声明：本研究未组装新策略、未动止损出场参数；止损/出场只出现在"止损距离单位"
换算中，不讨论任何改动方案。入场优势用价格漂移度量（ATR 单位为主，止损距离
单位为辅），不用带止损/出场的已实现 R 论证入场优势。

入场定义（与 v4.1 逐字一致，复用 v41_engine 语义，不另写信号定义）：
- 1H 严版大趋势：最后 3 摆动高/低逐级同向、每级 >= 0.5×ATR(1H)；
- 关键带同侧测试：近 96 根 15m 内按来向计数，两次到达间须离开带 >= 0.5×ATR；
- Teo 六种信号 K（5m）：多=hammer/bull_engulf/morning_star，
  空=shooting_star/bear_engulf/evening_star（公式逐字抄自 tae-scanner-tradfi.py，
  不 import 该扫描器模块，避免执行其模块级代码）；
- 完整入场 = 趋势 + 带测试>=2 + K（引擎 run_paper 语义；本研究另计"全部信号棒"
  与"持仓过滤后 341 单信号棒"两个口径，后者用于桥接归因结论）。

预设可信标准（写于结果之前，事后不改）：
- 主检验族：15 个部件 × 2 个主 horizon（+5、+10）= 30 个检验；
  Bonferroni alpha = 0.05/30 = 0.001667；同时报告 BH-FDR。
- 某部件有可信证据，当且仅当同时满足（同一 horizon）：
  (1) Bonferroni 校正后 CI（99.833% bootstrap 百分位区间）不含 0，且均值为正；
  (2) 在至少 2 个时间段（S1/S2/S3）同号显著（段内 95% CI 不含 0、同号）；
  (3) 经济量级：该 horizon 均值漂移 >= 0.3 ATR（带/完整部件另报止损距离单位，
      0.3 止损距离为更严的参照条）；
  (4) 样本量：全窗口 n >= 50，段内 n >= 30；随机基线超额 > 0（Welch t p < 0.05）。
- 达标则 verdict 为"入场层面有可信证据（具体部件）"，否则为"无可信证据"。
- 时段切分：S1 2020-01-01→2021-12-31，S2 2022-01-01→2023-12-31，
  S3 2024-01-01→2025-10-17。Regime 切分（仅探索、事后显著只进"待验证线索"）：
  波动率高低（ATR15 相对全窗口中位数）、趋势持续高低（同向趋势连续根数相对
  中位数），仅测 +5 horizon、仅测 full/trend/band2/any_K 四个部件。
- 漂移单位：主单位 ATR(15m)；带/完整部件另算止损距离单位（止损=带沿外 1×ATR，
  与引擎一致）。漂移起点为信号棒收盘（归因用 fill 棒收盘，桥接行会同时给出
  fill 口径以复现归因 ≈0 的结论）。
- 事件去重：趋势用"趋势起始棒"；带用"接触 episode 起始棒"（contacts_sided
  在当前棒新起一个接触）；K 用"每 15m 棒每类型一次"；组合每棒一次。
  同一棒多带同侧取测试次数最大者；双侧同棒取次数高者（平手取多，事前定死）。

复现：python3 entry_edge.py（依赖 numpy；数据取 data_cache/ 现成缓存）。
随机种子：20261025。
"""
import csv
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, ".")
from v41_engine import (WARM, atr_series, contacts_sided, find_levels_np,
                        swings_tf, strict_dir)

SEED = 20261025
D = "."
HORIZONS = (1, 3, 5, 10)
PRIMARY_H = (5, 10)
N_BOOT = 10000
N_BASE = 5000
SEG_BOUNDS = [  # (name, start_ms, end_ms_exclusive)
    ("S1", 1577836800000, 1640995200000),
    ("S2", 1640995200000, 1704067200000),
    ("S3", 1704067200000, 1760666400000 + 900000),
]
BONF_ALPHA = 0.05 / 30.0


# ------------------------------------------------------------------ K patterns
# Formulas copied verbatim from hidden_files/tae-scanner-tradfi.py
# (bull_engulf ~L227, bear_engulf, hammer, shooting_star, morning_star,
# evening_star, _is_signal_bar) — semantics identical, module not imported.
def _body(o, c):
    return abs(o - c)


def hammer(o, h, l, c):
    body = _body(o, c)
    rng = h - l
    if rng <= 0:
        return False
    return (min(o, c) - l) >= 2 * body and body <= 0.3 * rng


def shooting_star(o, h, l, c):
    body = _body(o, c)
    rng = h - l
    if rng <= 0:
        return False
    return (h - max(o, c)) >= 2 * body and body <= 0.3 * rng


def bull_engulf(po, pc, qo, qc):
    return (pc < po and qc > qo and qo <= pc * 1.001 and qc >= po * 0.999)


def bear_engulf(po, pc, qo, qc):
    return (pc > po and qc < qo and qo >= pc * 0.999 and qc <= po * 1.001)


def morning_star(a, b, c):
    body_a = a[0] - a[1]
    if body_a <= 0:
        return False
    if abs(b[0] - b[1]) > 0.5 * body_a:
        return False
    if c[1] <= c[0]:
        return False
    return c[1] > (a[0] + a[1]) / 2


def evening_star(a, b, c):
    body_a = a[1] - a[0]
    if body_a <= 0:
        return False
    if abs(b[0] - b[1]) > 0.5 * body_a:
        return False
    if c[1] >= c[0]:
        return False
    return c[1] < (a[0] + a[1]) / 2


LONG_K = ("hammer", "bull_engulf", "morning_star")
SHORT_K = ("shooting_star", "bear_engulf", "evening_star")


def k_types_at(j, o5, h5, l5, c5):
    """5m bar j 上的 K 类型集合（long 侧 / short 侧分开）。"""
    out_long, out_short = set(), set()
    if hammer(o5[j], h5[j], l5[j], c5[j]):
        out_long.add("hammer")
    if shooting_star(o5[j], h5[j], l5[j], c5[j]):
        out_short.add("shooting_star")
    if j >= 1:
        if bull_engulf(o5[j - 1], c5[j - 1], o5[j], c5[j]):
            out_long.add("bull_engulf")
        if bear_engulf(o5[j - 1], c5[j - 1], o5[j], c5[j]):
            out_short.add("bear_engulf")
    if j >= 2:
        a = (o5[j - 2], c5[j - 2])
        b = (o5[j - 1], c5[j - 1])
        c = (o5[j], c5[j])
        if morning_star(a, b, c):
            out_long.add("morning_star")
        if evening_star(a, b, c):
            out_short.add("evening_star")
    return out_long, out_short


# ------------------------------------------------------------------ data
def load_window(window):
    z15 = np.load(f"{D}/data_cache/{window}_15m.npz")
    z1h = np.load(f"{D}/data_cache/{window}_1h.npz")
    z5 = np.load(f"{D}/data_cache/{window}_5m.npz")
    o15, h15, l15, c15 = (z15["ohlc"][:, k] for k in range(4))
    o1h, h1h, l1h, c1h = (z1h["ohlc"][:, k] for k in range(4))
    o5, h5, l5, c5 = (z5["ohlc"][:, k] for k in range(4))
    return {"t15": z15["t"], "o15": o15, "h15": h15, "l15": l15, "c15": c15,
            "t1h": z1h["t"], "h1h": h1h, "l1h": l1h, "c1h": c1h,
            "t5": z5["t"], "o5": o5, "h5": h5, "l5": l5, "c5": c5}


def build_trend(d):
    """每根 15m 棒的 1H 严版趋势方向（引擎 run_paper 同语义）。"""
    n = len(d["t15"])
    atr1h = atr_series(d["h1h"], d["l1h"], d["c1h"])
    q1h = np.searchsorted(d["t1h"] + 3_600_000, d["t15"] + 900_000,
                          side="right") - 1
    trend = np.full(n, 0, dtype=np.int8)  # 0 None, 1 long, -1 short
    # Speed: strict_dir depends only on q (qualifying 1h bar); compute once
    # per unique q instead of once per 15m bar (identical results).
    q_trend = {}
    for q in np.unique(q1h[WARM:]):
        q = int(q)
        if q < 59:
            q_trend[q] = 0
            continue
        a1h = atr1h[q]
        if np.isnan(a1h):
            q_trend[q] = 0
            continue
        hi, lo = swings_tf(d["h1h"][q - 99:q + 1], d["l1h"][q - 99:q + 1])
        td = strict_dir(hi, lo, a1h)
        q_trend[q] = 1 if td == "long" else (-1 if td == "short" else 0)
    for i in range(WARM, n):
        trend[i] = q_trend[int(q1h[i])]
    return trend


def collect_events(d, trend, limit=None):
    """单遍采集全部部件事件。返回 dict：部件名 -> 事件列表。
    每个事件：(bar_i, dir_sign, entry_close, atr15, risk_or_nan,
              test_count_or_None, persistence, atr_pct_rank_base)。"""
    n = len(d["t15"])
    t15, h15, l15, c15 = d["t15"], d["h15"], d["l15"], d["c15"]
    o5, h5, l5, c5, t5 = d["o5"], d["h5"], d["l5"], d["c5"], d["t5"]
    atr15 = atr_series(h15, l15, c15)
    m5 = {int(t): j for j, t in enumerate(t5)}
    med_atr = float(np.nanmedian(atr15[WARM:n - 10]))
    ev = {k: [] for k in (
        "trend_onset", "trend_onset_long", "trend_onset_short",
        "band_test1", "band_test2", "band_test3p",
        "band_test1_long", "band_test1_short",
        "band_test2_long", "band_test2_short",
        "band_test3p_long", "band_test3p_short",
        "hammer", "bull_engulf", "morning_star",
        "shooting_star", "bear_engulf", "evening_star", "any_K",
        "trend_band", "trend_K", "band_K", "full")}
    # persistence: 同向趋势连续根数（含本棒）
    persist = np.zeros(n, dtype=np.int32)
    for i in range(1, n):
        persist[i] = persist[i - 1] + 1 if trend[i] != 0 and trend[i] == trend[i - 1] else 0
    med_persist = float(np.median(persist[WARM:n - 10][persist[WARM:n - 10] > 0]))
    last = (n - 10) if limit is None else min(limit, n - 10)
    t0 = time.time()
    for i in range(WARM, last):
        if i % 20000 == 0:
            print(f"  bar {i}/{last} ({time.time()-t0:.0f}s)", flush=True)
        a = atr15[i]
        if np.isnan(a):
            continue
        price = c15[i]
        td = int(trend[i])
        # ---- trend onset ----
        if td != 0 and trend[i - 1] != td:
            ev["trend_onset"].append((i, td, price, a, np.nan, None, persist[i], med_atr))
            ev["trend_onset_long" if td == 1 else "trend_onset_short"].append(
                (i, td, price, a, np.nan, None, persist[i], med_atr))
        # ---- band events (engine semantics: side by price/contacts, not kind) ----
        hw = h15[i - 95:i + 1]
        lw = l15[i - 95:i + 1]
        levels = find_levels_np(h15[i - 399:i + 1], l15[i - 399:i + 1],
                                c15[i - 399:i + 1], a)
        band_ev = {}  # side -> (count, risk)
        for lv in levels:
            blo, bhi = lv["band"]
            touching = lw[-1] <= bhi and hw[-1] >= blo
            if not touching:
                continue
            ct = contacts_sided(hw, lw, blo, bhi, a)
            for side, cond in ((1, price >= blo), (-1, price <= bhi)):
                if not cond:
                    continue
                side_ct = [r for r, s in ct if (s == "above") == (side == 1)]
                if not side_ct:
                    continue
                # episode dedup: record only bars where a contact episode
                # STARTS (relative index 95 == current bar); continuation
                # bars of the same episode are skipped.
                if side_ct[-1] != 95:
                    continue
                cnt = len(side_ct)
                risk = abs(price - (blo - a)) if side == 1 else abs(price - (bhi + a))
                if side not in band_ev or cnt > band_ev[side][0]:
                    band_ev[side] = (cnt, risk)
        # note: contacts_sided start indices are relative to the 96-bar window;
        # a start at 95 == current bar == new episode. The check above keeps
        # only episodes starting at the current bar.
        for side, (cnt, risk) in band_ev.items():
            bucket = "band_test1" if cnt == 1 else ("band_test2" if cnt == 2 else "band_test3p")
            ev[bucket].append((i, side, price, a, risk, cnt, persist[i], med_atr))
            ev[f"{bucket}_{'long' if side == 1 else 'short'}"].append(
                (i, side, price, a, risk, cnt, persist[i], med_atr))
        # ---- K events (last 3 5m constituents of this 15m bar) ----
        idx3 = [m5.get(int(t15[i] + k * 300_000)) for k in range(3)]
        k_long, k_short = set(), set()
        if all(v is not None for v in idx3):
            for j in idx3:
                kl, ks = k_types_at(j, o5, h5, l5, c5)
                k_long |= kl
                k_short |= ks
        for kname in k_long:
            ev[kname].append((i, 1, price, a, np.nan, None, persist[i], med_atr))
        for kname in k_short:
            ev[kname].append((i, -1, price, a, np.nan, None, persist[i], med_atr))
        if k_long or k_short:
            for side, ks in ((1, k_long), (-1, k_short)):
                if ks:
                    ev["any_K"].append((i, side, price, a, np.nan, None, persist[i], med_atr))
        # ---- combos (one event per bar per combo) ----
        for side in (1, -1):
            has_band2 = side in band_ev and band_ev[side][0] >= 2
            has_k = (k_long if side == 1 else k_short)
            band_risk = band_ev[side][1] if has_band2 else np.nan
            if td == side and has_band2:
                ev["trend_band"].append((i, side, price, a, band_risk, band_ev[side][0],
                                         persist[i], med_atr))
            if td == side and has_k:
                ev["trend_K"].append((i, side, price, a, np.nan, None, persist[i], med_atr))
            if has_band2 and has_k:
                ev["band_K"].append((i, side, price, a, band_risk, band_ev[side][0],
                                     persist[i], med_atr))
            if td == side and has_band2 and has_k:
                ev["full"].append((i, side, price, a, band_risk, band_ev[side][0],
                                   persist[i], med_atr))
    return ev, med_atr, med_persist


# ------------------------------------------------------------------ stats
def boot_ci(x, n_boot=N_BOOT, seed=SEED, level=0.95):
    """Chunked bootstrap percentile CI (mean). Returns (lo, hi).
    Chunk capped at 5M elements so large-n components (any_K ~330k events)
    cannot spike memory."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    lo_q = (1 - level) / 2 * 100
    hi_q = (1 + level) / 2 * 100
    means = []
    done = 0
    chunk = max(1, int(5_000_000 // max(n, 1)))
    while done < n_boot:
        m = min(chunk, n_boot - done)
        idx = rng.integers(0, n, size=(m, n))
        means.append(x[idx].mean(axis=1))
        done += m
    means = np.concatenate(means)
    return (float(np.percentile(means, lo_q)), float(np.percentile(means, hi_q)))


def norm_p(mean, sd, n):
    """Two-sided normal-approx p-value for mean == 0."""
    if n < 2 or sd <= 0:
        return float("nan")
    from math import erf, sqrt
    z = abs(mean) / (sd / sqrt(n))
    return float(1 - erf(z / sqrt(2)))


def welch_p(a, b):
    """Two-sided Welch t-test p-value (normal approx) for mean(a) > mean(b) comparison."""
    from math import erf, sqrt
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return float("nan")
    ma, mb = a.mean(), b.mean()
    va, vb = a.var(ddof=1), b.var(ddof=1)
    se = sqrt(va / na + vb / nb)
    if se <= 0:
        return float("nan")
    z = abs(ma - mb) / se
    return float(1 - erf(z / sqrt(2)))


def bh_fdr(pvals):
    """Benjamini-Hochberg adjusted q-values (NaN-safe)."""
    p = np.asarray(pvals, dtype=float)
    out = np.full(len(p), np.nan)
    ok = ~np.isnan(p)
    q = p[ok]
    order = np.argsort(q)
    ranked = q[order]
    m = len(ranked)
    adj = ranked * m / (np.arange(1, m + 1))
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    adj = np.clip(adj, 0, 1)
    out[np.where(ok)[0][order]] = adj
    return out


def seg_of(t_ms):
    for name, s, e in SEG_BOUNDS:
        if s <= t_ms < e:
            return name
    return None


def drift_rows(events, d, horizon, unit="atr"):
    """Drift values for a list of events at one horizon."""
    c15 = d["c15"]
    vals = []
    for (i, s, entry, a, risk, cnt, pers, med_atr) in events:
        j = i + horizon
        if j >= len(c15):
            continue
        denom = a if unit == "atr" else risk
        if denom is None or (isinstance(denom, float) and np.isnan(denom)) or denom == 0:
            continue
        vals.append(float(s * (c15[j] - entry) / denom))
    return vals


# ------------------------------------------------------------------ main
PRIMARY_COMPONENTS = ["trend_onset", "band_test1", "band_test2", "band_test3p",
                      "hammer", "bull_engulf", "morning_star",
                      "shooting_star", "bear_engulf", "evening_star", "any_K",
                      "trend_band", "trend_K", "band_K", "full"]
REGIME_COMPONENTS = ["full", "trend_onset", "band_test2", "any_K"]


def summarize_vals(vals):
    x = np.asarray(vals, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n == 0:
        return {"n": 0}
    return {"n": int(n), "mean": float(x.mean()), "median": float(np.median(x)),
            "sd": float(x.std(ddof=1)) if n > 1 else 0.0,
            "min": float(x.min()), "max": float(x.max())}


def save_checkpoint(ev, med_atr, med_persist):
    """Persist collected events so a VM reboot during stats does not lose
    the ~16 min levels pass. One array per component (columns: bar_i, dir,
    entry, atr, risk, count, persist)."""
    arrs = {"med_atr": np.array([med_atr]), "med_persist": np.array([med_persist])}
    for k, v in ev.items():
        if v:
            arrs[k] = np.array(
                [[e[0], e[1], e[2], e[3], e[4],
                  -1 if e[5] is None else e[5], e[6], e[7]] for e in v], dtype=float)
        else:
            arrs[k] = np.empty((0, 8))
    np.savez(f"{D}/entry_edge_events.npz", **arrs)
    print("checkpoint saved", flush=True)


def load_checkpoint():
    z = np.load(f"{D}/entry_edge_events.npz")
    ev = {}
    for k in z.files:
        if k in ("med_atr", "med_persist"):
            continue
        a = z[k]
        ev[k] = [(int(r[0]), int(r[1]), float(r[2]), float(r[3]), float(r[4]),
                  None if int(r[5]) == -1 else int(r[5]), int(r[6]), float(r[7]))
                 for r in a] if len(a) else []
    return ev, float(z["med_atr"][0]), float(z["med_persist"][0])


def main():
    import sys
    args = sys.argv[1:]
    limit = int(args[0]) if args and args[0].isdigit() else None
    resume = "--resume" in args
    d = load_window("oos")
    n = len(d["t15"])
    print(f"OOS bars: {n}", flush=True)
    if resume:
        ev, med_atr, med_persist = load_checkpoint()
        print("resumed from checkpoint", flush=True)
    else:
        trend = build_trend(d)
        print("trend series done", flush=True)
        ev, med_atr, med_persist = collect_events(d, trend, limit=limit)
        save_checkpoint(ev, med_atr, med_persist)
    print(f"events: " + ", ".join(f"{k}={len(v)}" for k, v in ev.items()), flush=True)

    rng = np.random.default_rng(SEED)
    c15 = d["c15"]
    atr15 = atr_series(d["h15"], d["l15"], d["c15"])
    # ---- random baseline (ATR units): uniform bars, coin-flip direction ----
    base_idx = rng.integers(WARM, n - 10, size=N_BASE)
    base_dir = rng.choice([1, -1], size=N_BASE)
    baseline = {}
    for h in HORIZONS:
        vals = []
        for b, s in zip(base_idx, base_dir):
            if np.isnan(atr15[b]):
                continue
            vals.append(float(s * (c15[b + h] - c15[b]) / atr15[b]))
        baseline[h] = vals
    # ---- stop-distance baseline for band/full (sample empirical stop_dist_pct) ----
    import csv as _csv
    sd_pcts = []
    with open(f"{D}/trades_oos.csv") as fh:
        for row in _csv.DictReader(fh):
            sd_pcts.append(float(row["stop_dist_pct"]))
    sd_pcts = np.asarray(sd_pcts)
    base_sd = {}
    for h in HORIZONS:
        vals = []
        rp = rng.choice(sd_pcts, size=N_BASE)
        for b, s, r in zip(base_idx, base_dir, rp):
            risk = c15[b] * r / 100.0
            vals.append(float(s * (c15[b + h] - c15[b]) / risk))
        base_sd[h] = vals

    # ---- bridge: 341 filled-trade signal bars (from trades_oos.csv) ----
    t_to_i = {int(t): i for i, t in enumerate(d["t15"])}
    bridge = []
    bridge_fill = []
    with open(f"{D}/trades_oos.csv") as fh:
        for row in _csv.DictReader(fh):
            st = datetime.strptime(row["signal_time"], "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc)
            ms = int(st.timestamp() * 1000)
            i = t_to_i.get(ms)
            if i is None:
                continue
            s = 1 if row["dir"] == "long" else -1
            entry, risk = float(row["entry"]), float(row["sl"])
            risk = abs(entry - risk)
            bridge.append((i, s, entry, atr15[i], risk, None, 0, med_atr))
            bridge_fill.append((i + 1, s, entry, atr15[i], risk, None, 0, med_atr))
    print(f"bridge bars mapped: {len(bridge)}/341", flush=True)

    # ---- component table ----
    comp_rows = []
    pvals_primary = []
    pkeys = []
    for comp in PRIMARY_COMPONENTS:
        print(f"stats: {comp} (n={len(ev[comp])})", flush=True)
        events = ev[comp]
        for h in HORIZONS:
            vals = drift_rows(events, d, h, unit="atr")
            st = summarize_vals(vals)
            row = {"component": comp, "horizon": h, **st}
            if st["n"] >= 2:
                row["ci95"] = boot_ci(vals, level=0.95)
                row["ci_bonf"] = boot_ci(vals, level=1 - BONF_ALPHA)
                row["p_norm"] = norm_p(st["mean"], st["sd"], st["n"])
                row["baseline_mean"] = float(np.mean(baseline[h]))
                row["excess"] = st["mean"] - row["baseline_mean"]
                row["p_vs_base"] = welch_p(vals, baseline[h])
            comp_rows.append(row)
            if h in PRIMARY_H:
                pvals_primary.append(row.get("p_norm", float("nan")))
                pkeys.append((comp, h))
    qvals = bh_fdr(pvals_primary)
    for (comp, h), q in zip(pkeys, qvals):
        for row in comp_rows:
            if row["component"] == comp and row["horizon"] == h:
                row["q_fdr"] = float(q)
    # stop-distance-unit rows for band/full components
    for comp in ("band_test1", "band_test2", "band_test3p", "trend_band", "band_K", "full"):
        for h in HORIZONS:
            vals = drift_rows(ev[comp], d, h, unit="risk")
            st = summarize_vals(vals)
            row = {"component": comp + "_RISKUNIT", "horizon": h, **st}
            if st["n"] >= 2:
                row["ci95"] = boot_ci(vals, level=0.95)
                row["baseline_mean"] = float(np.mean(base_sd[h]))
                row["excess"] = st["mean"] - row["baseline_mean"]
            comp_rows.append(row)

    # ---- bridge rows (not in primary family) ----
    bridge_rows = []
    for label, evlist in (("full_position_filtered", bridge),
                          ("full_position_filtered_fillconv", bridge_fill)):
        for h in HORIZONS:
            vals = drift_rows(evlist, d, h, unit="risk")
            st = summarize_vals(vals)
            row = {"component": label, "horizon": h, **st}
            if st["n"] >= 2:
                row["ci95"] = boot_ci(vals, level=0.95)
            bridge_rows.append(row)

    # ---- segments (primary components, +5/+10) ----
    seg_rows = []
    for comp in PRIMARY_COMPONENTS:
        events = ev[comp]
        for h in PRIMARY_H:
            for sname, s0, s1 in SEG_BOUNDS:
                sel = [e for e in events if s0 <= d["t15"][e[0]] < s1]
                vals = drift_rows(sel, d, h, unit="atr")
                st = summarize_vals(vals)
                row = {"component": comp, "horizon": h, "segment": sname, **st}
                if st["n"] >= 2:
                    row["ci95"] = boot_ci(vals, level=0.95)
                seg_rows.append(row)
    # ---- per-direction secondary (+5/+10) ----
    dir_rows = []
    for comp in ("trend_onset_long", "trend_onset_short",
                 "band_test1_long", "band_test1_short",
                 "band_test2_long", "band_test2_short",
                 "band_test3p_long", "band_test3p_short"):
        for h in PRIMARY_H:
            vals = drift_rows(ev[comp], d, h, unit="atr")
            st = summarize_vals(vals)
            row = {"component": comp, "horizon": h, **st}
            if st["n"] >= 2:
                row["ci95"] = boot_ci(vals, level=0.95)
            dir_rows.append(row)
    # ---- regime splits (+5 only, exploratory) ----
    reg_rows = []
    for comp in REGIME_COMPONENTS:
        for h in (5,):
            for regime, sel in (
                    ("vol_high", [e for e in ev[comp] if e[3] > med_atr]),
                    ("vol_low", [e for e in ev[comp] if e[3] <= med_atr]),
                    ("persist_high", [e for e in ev[comp] if e[6] > med_persist]),
                    ("persist_low", [e for e in ev[comp] if e[6] <= med_persist])):
                vals = drift_rows(sel, d, h, unit="atr")
                st = summarize_vals(vals)
                row = {"component": comp, "horizon": h, "regime": regime, **st}
                if st["n"] >= 2:
                    row["ci95"] = boot_ci(vals, level=0.95)
                reg_rows.append(row)

    # ---- verdict gates ----
    gates = {}
    for comp in PRIMARY_COMPONENTS:
        for h in PRIMARY_H:
            row = next(r for r in comp_rows
                       if r["component"] == comp and r["horizon"] == h)
            n = row.get("n", 0)
            if n < 50:
                gates[f"{comp}@{h}"] = {"verdict": "insufficient_n", "n": n}
                continue
            bonf_ok = row["ci_bonf"][0] > 0
            segs = [r for r in seg_rows if r["component"] == comp and r["horizon"] == h]
            seg_ok = sum(1 for r in segs
                         if r.get("n", 0) >= 30 and r.get("ci95", (1, -1))[0] > 0) >= 2
            mag_ok = row["mean"] >= 0.3
            base_ok = row.get("p_vs_base", 1) < 0.05 and row.get("excess", 0) > 0
            gates[f"{comp}@{h}"] = {
                "verdict": ("CREDIBLE" if (bonf_ok and seg_ok and mag_ok and base_ok)
                            else "not_credible"),
                "n": n, "mean": row["mean"], "ci_bonf": row["ci_bonf"],
                "bonf_ok": bool(bonf_ok), "seg_ok": bool(seg_ok),
                "mag_ok": bool(mag_ok), "base_ok": bool(base_ok),
                "excess": row.get("excess"),
                "segments": {r["segment"]: {"n": r.get("n"), "mean": r.get("mean"),
                                            "ci95": r.get("ci95")} for r in segs}}
    credible = [k for k, v in gates.items() if v["verdict"] == "CREDIBLE"]
    # ---- power note: best component by |t| at +5/+10 ----
    best, best_t = None, 0.0
    for row in comp_rows:
        if row["component"] in PRIMARY_COMPONENTS and row["horizon"] in PRIMARY_H \
                and row.get("n", 0) >= 50 and row.get("sd", 0) > 0:
            import math
            t = abs(row["mean"]) / (row["sd"] / math.sqrt(row["n"]))
            if t > best_t:
                best_t, best = t, row
    power = {}
    if best is not None:
        import math
        n_needed = ((1.96 + 0.84) * best["sd"] / 0.3) ** 2
        power = {"best_component": best["component"], "best_horizon": best["horizon"],
                 "best_t": best_t, "best_sd": best["sd"],
                 "n_needed_for_0.3ATR_80pct": float(n_needed)}

    summary = {"n_bars": int(n), "family_tests": 30, "bonf_alpha": BONF_ALPHA,
               "med_atr": med_atr, "med_persist": med_persist,
               "event_counts": {k: len(v) for k, v in ev.items()},
               "bridge_mapped": len(bridge),
               "credible": credible, "gates": gates, "power": power}
    json.dump(summary, open(f"{D}/entry_edge_summary.json", "w"),
              indent=1, ensure_ascii=False)

    def dump_csv(path, rows, fields):
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow({f: (json.dumps(r[f], ensure_ascii=False)
                                if isinstance(r.get(f), (list, tuple, dict)) else r.get(f))
                            for f in fields})
    fields = ["component", "horizon", "n", "mean", "median", "sd", "min", "max",
              "ci95", "ci_bonf", "p_norm", "q_fdr", "baseline_mean", "excess", "p_vs_base"]
    dump_csv(f"{D}/entry_edge_components.csv", comp_rows, fields)
    dump_csv(f"{D}/entry_edge_segments.csv", seg_rows,
             ["component", "horizon", "segment", "n", "mean", "median", "sd", "ci95"])
    dump_csv(f"{D}/entry_edge_directions.csv", dir_rows,
             ["component", "horizon", "n", "mean", "median", "sd", "ci95"])
    dump_csv(f"{D}/entry_edge_regime.csv", reg_rows,
             ["component", "horizon", "regime", "n", "mean", "median", "sd", "ci95"])
    dump_csv(f"{D}/entry_edge_bridge.csv", bridge_rows,
             ["component", "horizon", "n", "mean", "median", "sd", "ci95"])
    print(json.dumps(summary, indent=1, ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main()
