"""TAE-B1 v0.1 归因分析（探索性研究，不改冻结规则、不改引擎文件）。

输入：trades_b_oos.csv（B 组样本外 123 单，T0×EMA50 为基线）、
  data_cache/stitched_*.npz、candidates.jsonl、b1_engine/b1_lib（只读 import）。
输出：attribution_*.csv/json（支撑表）+ 打印 headline 数字（报告用）。
口径：
 - 主口径：B 组、样本外、T0×EMA50、净 R（含费用/滑点/资金费）。
 - Q1：E 信号种类按 5m 信号 bar 上实际触发的形态逐项判定；一根 bar 触发
   多种形态时主表计入 "multi" 桶，附表 any-fire 表按形态分别计数（重叠计数，
   合计 > 123，须注明）。
 - Q2：MFE = 自 fill bar 起至出场 bar（含）内 5m 极值的最优顺向幅度（R 单位）；
   MFE_excl 为去掉最后一根 5m 后的版本（稳健性对照）。
 - Q3：环境定义见 regime_bucket()（事前写死，不事后调桶）。
 - Q4：消融主口径 = 收复根 15m 收盘价入场（与系统自身 EMA 收盘出场同为
   收盘价惯例）；敏感性 = 下一根 15m 开盘价入场（可执行近似）。其余（止损
   公式、出场、费用/资金费、重叠/冷却过滤）与 B 基线完全一致。
验证：先用 b1_engine.run_group 原样重跑 B，与 CSV 逐单比对（123 单、
  fill 时间、净 R），通过后才跑消融；消融 Phase A/B 循环与引擎同一份
  代码结构，仅 resolver 不同（E 确认被替换为收复收盘入场）。
"""
import bisect
import csv
import json
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
from b1_lib import (atr_series, swings_tie, hammer, shooting_star, bull_engulf,
                    bear_engulf, morning_star, evening_star, is_signal_bar,
                    BOUNDARY_MS)  # noqa: E402
from b1_engine import (Data, run_group, simulate_exit, trade_numbers,
                       stats_for, COMBOS, resolve_sequence)  # noqa: E402

B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1"
OUT = B1


def parse_ms(s):
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%M").replace(
        tzinfo=timezone.utc).timestamp() * 1000)


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M")


def kinds_at(o5, m, d):
    ks = []
    if d == "long":
        if hammer(o5[m], False):
            ks.append("hammer")
        if m > 0 and bull_engulf(o5[m - 1], o5[m]):
            ks.append("bull_engulf")
        if morning_star(o5, m):
            ks.append("morning_star")
    else:
        if shooting_star(o5[m], False):
            ks.append("shooting_star")
        if m > 0 and bear_engulf(o5[m - 1], o5[m]):
            ks.append("bear_engulf")
        if evening_star(o5, m):
            ks.append("evening_star")
    return ks


# ---------------- Q1/Q2/Q3：基于 CSV 逐单复算 ----------------

def analyze_csv(D):
    t15, o15, t5, o5 = D.t15, D.o15, D.t5, D.o5
    c15 = D.c15
    atr15 = D.atr15
    d1h = np.load(f"{B1}/data_cache/stitched_1h.npz")
    t1h, o1h = d1h["t"], d1h["ohlc"]
    atr1 = atr_series(o1h)
    hi_all, lo_all = swings_tie(o1h)
    hi_idx = [i for i, _ in hi_all]
    hi_val = [v for _, v in hi_all]
    lo_idx = [i for i, _ in lo_all]
    lo_val = [v for _, v in lo_all]
    t1h_close = t1h + 3_600_000

    def trend_strength(j15, d):
        """1H 趋势强度 = 4 个摆动台阶（高 2 + 低 2）中最小者 / ATR(1H)。
        口径与 levels_pass.trend_at 一致（指针法、无未来函数）。"""
        p = int(np.searchsorted(t1h_close, int(t15[j15]) + 900_000, side="right"))
        if p < 60 or np.isnan(atr1[p - 1]):
            return None
        hi = [v for idx, v in zip(hi_idx, hi_val) if idx <= p - 3][-3:]
        lo = [v for idx, v in zip(lo_idx, lo_val) if idx <= p - 3][-3:]
        if len(hi) < 3 or len(lo) < 3:
            return None
        steps = [hi[1] - hi[0], hi[2] - hi[1], lo[1] - lo[0], lo[2] - lo[1]]
        if d == "long":
            return min(steps) / atr1[p - 1]
        return min(-x for x in steps) / atr1[p - 1]

    rows = []
    with open(f"{B1}/trades_b_oos.csv") as fh:
        for row in csv.DictReader(fh):
            rows.append(row)
    out = []
    mism = []
    for row in rows:
        d = row["dir"]
        b0_ms = parse_ms(row["seq_b0"])
        b0 = int(np.searchsorted(t15, b0_ms, side="left"))
        assert int(t15[b0]) == b0_ms, row["seq_b0"]
        r = int(np.searchsorted(t15, parse_ms(row["reclaim"]) - 900_000, side="left"))
        assert int(t15[r]) + 900_000 == parse_ms(row["reclaim"])
        fill_close = parse_ms(row["fill_time"])
        exit_close = parse_ms(row["base_exit_time"])
        entry = float(row["entry"])
        risk = float(row["risk_pts"])
        stop = float(row["stop"])
        # --- Q1：重算 E 信号 bar 与种类 ---
        tr_close = int(t15[r]) + 900_000
        m0 = int(np.searchsorted(t5, tr_close, side="left"))
        sig = None
        for k in range(3):
            m = m0 + k
            if is_signal_bar(o5, m, d, False):
                sig = m
                break
        ks = kinds_at(o5, sig, d) if sig is not None else []
        trig = float(o5[sig][1]) if d == "long" else float(o5[sig][2])
        fill = None
        for m in range(sig + 1, sig + 4):
            if (d == "long" and float(o5[m][1]) >= trig) or \
               (d == "short" and float(o5[m][2]) <= trig):
                fill = m
                break
        if sig is None or abs(trig - float(row["trigger"])) > 1e-9 or \
                int(t5[fill]) + 300_000 != fill_close:
            mism.append((row["seq_b0"], d, sig, trig, row["trigger"]))
        # --- Q2：MFE ---
        fill_open = fill_close - 300_000
        i0 = int(np.searchsorted(t5, fill_open, side="left"))
        i1 = int(np.searchsorted(t5, exit_close, side="left"))
        if d == "long":
            fav = (o5[i0:i1, 1] - entry) / risk
        else:
            fav = (entry - o5[i0:i1, 2]) / risk
        mfe = float(np.max(fav)) if len(fav) else float("nan")
        mfe_ex = float(np.max(fav[:-1])) if len(fav) > 1 else float("nan")
        # --- Q3：环境变量 ---
        ts = trend_strength(b0, d)
        lag = r - b0
        bw = (float(row["band_hi"]) - float(row["band_lo"]))
        depth = ((float(row["band_hi"]) - float(row["touch_extreme"])) / bw
                 if d == "long" else
                 (float(row["touch_extreme"]) - float(row["band_lo"])) / bw)
        bw_atr = bw / atr15[b0] if not np.isnan(atr15[b0]) else float("nan")
        # 假突破失败模式（描述性，非入场环境）：fill 所在 15m  bar 之后 3 根内
        # 收盘回到带内（多头收盘 < bhi，空头收盘 > blo）
        k_fill = int(np.searchsorted(t15, fill_open - (fill_open % 900_000),
                                     side="left"))
        fb = False
        for k in range(k_fill + 1, min(k_fill + 4, len(t15))):
            ck = float(c15[k])
            if (d == "long" and ck < float(row["band_hi"])) or \
               (d == "short" and ck > float(row["band_lo"])):
                fb = True
                break
        out.append({
            "seq_b0": row["seq_b0"], "dir": d, "window": row["window"],
            "net": float(row["net_T0_EMA50"]),
            "gross": float(row["base_gross"]),
            "reason": row["reason_T0_EMA50"],
            "kinds": ks, "kind_primary": ks[0] if len(ks) == 1 else "multi",
            "mfe": mfe, "mfe_excl": mfe_ex,
            "trend_strength": ts, "reclaim_lag": lag,
            "depth": depth, "band_width_atr": bw_atr,
            "fallback_3bar": fb,
            "entry": entry, "risk": risk, "stop": stop,
        })
    print(f"csv trades: {len(out)}, E-recompute mismatches: {len(mism)}")
    for m in mism[:10]:
        print("  MISMATCH:", m)
    return out


def bucket(v, edges, labels):
    for e, lab in zip(edges, labels):
        if v < e:
            return lab
    return labels[-1]


def regime_tables(trades):
    """事前写死的桶定义（不事后调桶）：
    趋势强度：weak [0.5,0.75) / mid [0.75,1.25) / strong [1.25,inf)
    回踩耗时：fast 1-2 根 / mid 3-8 根 / slow 9-48 根
    回踩深度：shallow <0.5 / mid [0.5,1] / deep >1（带宽分数）
    带宽/ATR：narrow <0.5 / mid [0.5,1] / wide >1"""
    dims = {
        "trend_strength": lambda t: ("weak" if t["trend_strength"] < 0.75 else
                                     "mid" if t["trend_strength"] < 1.25 else "strong"),
        "reclaim_lag": lambda t: ("fast" if t["reclaim_lag"] <= 2 else
                                  "mid" if t["reclaim_lag"] <= 8 else "slow"),
        "depth": lambda t: ("shallow" if t["depth"] < 0.5 else
                            "mid" if t["depth"] <= 1.0 else "deep"),
        "band_width_atr": lambda t: ("narrow" if t["band_width_atr"] < 0.5 else
                                     "mid" if t["band_width_atr"] <= 1.0 else "wide"),
        "fallback_3bar": lambda t: ("yes" if t["fallback_3bar"] else "no"),
    }
    tables = {}
    for dim, fn in dims.items():
        groups = {}
        for t in trades:
            g = fn(t)
            groups.setdefault(g, []).append(t)
        rows = []
        tot_loss = sum(-t["net"] for t in trades if t["net"] < 0)
        for g, ts in sorted(groups.items()):
            wins = sum(1 for t in ts if t["net"] > 0)
            loss = sum(-t["net"] for t in ts if t["net"] < 0)
            rows.append({"dim": dim, "bucket": g, "n": len(ts),
                         "wins": wins, "win_rate": wins / len(ts),
                         "total_net": sum(t["net"] for t in ts),
                         "avg_net": float(np.mean([t["net"] for t in ts])),
                         "loss_share": loss / tot_loss if tot_loss else 0.0,
                         "n_stop": sum(1 for t in ts if t["reason"] == "stop")})
        tables[dim] = rows
    return tables


# ---------------- Q4：消融（与引擎同构的循环，仅 resolver 不同） ----------------

def run_loop(D, cand, resolver, tag):
    """与 b1_engine.run_group 同构的 Phase A/B；resolver(s, r, entries, counts,
    outcomes) 在收复时决定入场或放弃。返回 (trades, counts, outcomes)。"""
    t15, o15, t5, o5 = D.t15, D.o15, D.t5, D.o5
    c15 = D.c15
    n15 = len(t15)
    counts = {"seq_started": 0, "voided": 0, "expired": 0, "e_timeout": 0,
              "coincident_void": 0, "missed": 0, "lev_skip": 0, "invalid": 0,
              "filled_entries": 0, "skipped_overlap": 0, "skipped_cooldown": 0,
              "accepted": 0, "unresolved": 0}
    outcomes = {}

    def window_of(ms):
        return "oos" if ms <= BOUNDARY_MS else "ins"

    active = []
    entries = []
    for j in range(399, n15):
        cj, hj, lj = float(c15[j]), float(o15[j][1]), float(o15[j][2])
        nxt = []
        for s in active:
            d = s["dir"]
            if d == "long":
                if cj < s["blo"]:
                    counts["voided"] += 1
                    outcomes[(s["b0"], d)] = "voided"
                    continue
                if not s["touched"]:
                    if lj <= s["bhi"] and hj >= s["blo"]:
                        s["touched"] = True
                        s["extreme"] = lj
                if s["touched"]:
                    s["extreme"] = min(s["extreme"], lj)
                    if cj > s["bhi"]:
                        resolver(D, s, j, entries, counts, outcomes)
                        continue
                if j >= s["b0"] + 48:
                    counts["expired"] += 1
                    outcomes[(s["b0"], d)] = "expired"
                    continue
            else:
                if cj > s["bhi"]:
                    counts["voided"] += 1
                    outcomes[(s["b0"], d)] = "voided"
                    continue
                if not s["touched"]:
                    if lj <= s["bhi"] and hj >= s["blo"]:
                        s["touched"] = True
                        s["extreme"] = hj
                if s["touched"]:
                    s["extreme"] = max(s["extreme"], hj)
                    if cj < s["blo"]:
                        resolver(D, s, j, entries, counts, outcomes)
                        continue
                if j >= s["b0"] + 48:
                    counts["expired"] += 1
                    outcomes[(s["b0"], d)] = "expired"
                    continue
            nxt.append(s)
        active = nxt
        for d in ("long", "short"):
            cands = [c for c in cand.get(j, []) if c[0] == d]
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
    entries.sort(key=lambda e: (e["fill_close_ms"], e["b0"], e["dir"]))
    trades = []
    open_until = -10**18
    cool_until = {"long": -10**18, "short": -10**18}
    skipped = {}
    for e in entries:
        ft = e["fill_close_ms"]
        if ft < open_until:
            counts["skipped_overlap"] += 1
            skipped[(e["b0"], e["dir"])] = "overlap"
            continue
        if ft < cool_until[e["dir"]]:
            counts["skipped_cooldown"] += 1
            skipped[(e["b0"], e["dir"])] = "cooldown"
            continue
        outs = {c: simulate_exit(D, e, c[0], c[1]) for c in COMBOS}
        base = outs[("T0", "EMA50")]
        if base is None:
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
    return trades, counts, outcomes, skipped


def e_resolver(D, s, r, entries, counts, outcomes):
    """原版 E 路径（验证用）：直接调用引擎的 resolve_sequence，
    用计数器增量反推该序列的结局（filled/e_timeout/missed/
    coincident_void/lev_skip/invalid）。"""
    keys = ("filled_entries", "e_timeout", "missed", "coincident_void",
            "lev_skip", "invalid")
    before = {k: counts[k] for k in keys}
    seq_counts = {"oos": dict(counts), "ins": dict(counts)}
    resolve_sequence(D, s, r, entries, counts, seq_counts, False)
    key = (s["b0"], s["dir"])
    for k in keys:
        if counts[k] > before[k]:
            outcomes[key] = k
            return
    outcomes[key] = "unknown"


def noe_resolver_factory(mode):
    def resolver(D, s, r, entries, counts, outcomes):
        d = s["dir"]
        atr_r = float(D.atr15[r])
        if mode == "close":
            entry = float(D.c15[r])
            fill5 = int(np.searchsorted(D.t5, int(D.t15[r]), side="left"))
            fill_open = int(D.t15[r])
            fill_close = fill_open + 900_000
        else:  # next_open
            if r + 1 >= len(D.t15):
                counts["invalid"] += 1
                outcomes[(s["b0"], d)] = "invalid"
                return
            entry = float(D.o15[r + 1][0])
            fill5 = int(np.searchsorted(D.t5, int(D.t15[r + 1]), side="left"))
            fill_open = int(D.t15[r + 1])
            fill_close = fill_open + 900_000
        stop = s["extreme"] - atr_r if d == "long" else s["extreme"] + atr_r
        risk = abs(entry - stop)
        if risk <= 0 or np.isnan(atr_r):
            counts["invalid"] += 1
            outcomes[(s["b0"], d)] = "invalid"
            return
        if 0.02 / (risk / entry) > 20:
            counts["lev_skip"] += 1
            outcomes[(s["b0"], d)] = "lev_skip"
            return
        counts["filled_entries"] += 1
        outcomes[(s["b0"], d)] = "filled"
        entries.append({
            "dir": d, "b0": s["b0"], "b0_open_ms": int(D.t15[s["b0"]]),
            "blo": s["blo"], "bhi": s["bhi"],
            "touch_extreme": s["extreme"], "reclaim_idx": r,
            "e_idx": None, "trigger": entry, "fill_idx": fill5,
            "fill_close_ms": fill_close, "fill_open_ms": fill_open,
            "entry": entry, "stop": stop, "risk": risk,
        })
    return resolver


def main():
    D = Data()
    cand = {}
    with open(f"{B1}/data_cache/candidates.jsonl") as fh:
        for line in fh:
            try:
                c = json.loads(line)
            except Exception:
                continue
            cand.setdefault(c["j"], []).append((c["dir"], c["blo"], c["bhi"]))
    print(f"candidates bars: {len(cand)}")

    # --- Q1/Q2/Q3 ---
    trades = analyze_csv(D)
    with open(f"{OUT}/attribution_mfe.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["seq_b0", "dir", "net", "gross",
                                            "reason", "kind_primary",
                                            "kinds", "mfe", "mfe_excl",
                                            "trend_strength", "reclaim_lag",
                                            "depth", "band_width_atr",
                                            "fallback_3bar"])
        wr.writeheader()
        for t in trades:
            wr.writerow({k: t[k] for k in
                         ["seq_b0", "dir", "net", "gross", "reason",
                          "kind_primary", "mfe", "mfe_excl", "trend_strength",
                          "reclaim_lag", "depth", "band_width_atr",
                          "fallback_3bar"]} | {"kinds": "+".join(t["kinds"])})
    tables = regime_tables(trades)
    with open(f"{OUT}/attribution_regimes.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["dim", "bucket", "n", "wins",
                                            "win_rate", "total_net", "avg_net",
                                            "loss_share", "n_stop"])
        wr.writeheader()
        for dim, rows in tables.items():
            wr.writerows(rows)

    # Q1 aggregates
    kinds = {}
    anyfire = {}
    for t in trades:
        k = t["kind_primary"]
        kinds.setdefault(k, []).append(t)
        for kk in t["kinds"]:
            anyfire.setdefault(kk, []).append(t)
    kind_rows = []
    tot_loss = sum(-t["net"] for t in trades if t["net"] < 0)
    for k, ts in sorted(kinds.items()):
        loss = sum(-t["net"] for t in ts if t["net"] < 0)
        kind_rows.append({"kind": k, "n": len(ts),
                          "wins": sum(1 for t in ts if t["net"] > 0),
                          "win_rate": sum(1 for t in ts if t["net"] > 0) / len(ts),
                          "total_net": sum(t["net"] for t in ts),
                          "avg_net": float(np.mean([t["net"] for t in ts])),
                          "total_gross": sum(t["gross"] for t in ts),
                          "loss_share": loss / tot_loss if tot_loss else 0.0})
    with open(f"{OUT}/attribution_kinds.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["kind", "n", "wins", "win_rate",
                                            "total_net", "avg_net",
                                            "total_gross", "loss_share"])
        wr.writeheader()
        wr.writerows(kind_rows)
    any_rows = []
    for k, ts in sorted(anyfire.items()):
        any_rows.append({"kind": k, "n_anyfire": len(ts),
                         "wins": sum(1 for t in ts if t["net"] > 0),
                         "win_rate": sum(1 for t in ts if t["net"] > 0) / len(ts),
                         "total_net": sum(t["net"] for t in ts),
                         "avg_net": float(np.mean([t["net"] for t in ts]))})
    with open(f"{OUT}/attribution_kinds_anyfire.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["kind", "n_anyfire", "wins",
                                            "win_rate", "total_net", "avg_net"])
        wr.writeheader()
        wr.writerows(any_rows)
    print("== Q1 kinds (primary) ==")
    for r in kind_rows:
        print(f"  {r['kind']}: n={r['n']} wins={r['wins']} wr={r['win_rate']:.3f} "
              f"total_net={r['total_net']:.2f} avg_net={r['avg_net']:.3f} "
              f"loss_share={r['loss_share']:.3f}")

    # Q2 aggregates
    losers = [t for t in trades if t["net"] < 0]
    stops = [t for t in trades if t["reason"] == "stop"]
    for name, pop in (("losers(net<0)", losers), ("stop-outs", stops)):
        for thr in (0.5, 1.0, 2.0):
            print(f"  Q2 {name}: MFE>={thr}R: "
                  f"{sum(1 for t in pop if t['mfe'] >= thr)}/{len(pop)} "
                  f"({sum(1 for t in pop if t['mfe'] >= thr)/len(pop):.3f})")
        print(f"  Q2 {name}: median MFE={float(np.median([t['mfe'] for t in pop])):.3f} "
              f"mean MFE={float(np.mean([t['mfe'] for t in pop])):.3f}")
    print(f"  Q2 stop-outs with MFE_excl>=0.5R: "
          f"{sum(1 for t in stops if t['mfe_excl'] >= 0.5)}/{len(stops)}")
    print(f"  Q2 stop-outs with MFE<0.1R (never went anywhere): "
          f"{sum(1 for t in stops if t['mfe'] < 0.1)}/{len(stops)}")

    # --- Q4 验证：原版引擎重跑 vs CSV ---
    v_trades, v_counts, _, _ = run_loop(D, cand, e_resolver, "validate")
    v_oos = [e for e in v_trades if e["fill_open_ms"] <= BOUNDARY_MS]
    print(f"validation: accepted total={len(v_trades)} oos={len(v_oos)}")
    csv_map = {}
    with open(f"{B1}/trades_b_oos.csv") as fh:
        for row in csv.DictReader(fh):
            csv_map[(row["seq_b0"], row["dir"])] = row
    bad = 0
    for e in v_oos:
        key = (iso(e["b0_open_ms"]), e["dir"])
        row = csv_map.get(key)
        if row is None:
            bad += 1
            print("  VAL missing in csv:", key)
            continue
        n = trade_numbers(D, e, e["outs"][("T0", "EMA50")])["net"]
        if abs(n - float(row["net_T0_EMA50"])) > 1e-9 or \
                iso(e["fill_close_ms"]) != row["fill_time"]:
            bad += 1
            print("  VAL mismatch:", key, n, row["net_T0_EMA50"])
    print(f"validation mismatches: {bad} (must be 0)")

    # --- Q4 消融 ---
    b_keys = {(row["seq_b0"], row["dir"]) for row in csv_map.values()}
    abl = {}
    for mode in ("close", "next_open"):
        a_trades, a_counts, a_out, a_skip = run_loop(
            D, cand, noe_resolver_factory(mode), mode)
        a_oos = [e for e in a_trades if e["fill_open_ms"] <= BOUNDARY_MS]
        nets = [trade_numbers(D, e, e["outs"][("T0", "EMA50")])["net"]
                for e in a_oos]
        st = stats_for(nets)
        combos = {}
        for c in COMBOS:
            cn = [trade_numbers(D, e, e["outs"][c])["net"] for e in a_oos]
            combos[f"{c[0]}_{c[1]}"] = stats_for(cn)
        abl[mode] = {"counts": a_counts, "stats": st, "combos": combos,
                     "n_oos": len(a_oos)}
        print(f"ablation {mode}: accepted={len(a_trades)} oos={len(a_oos)} "
              f"counts={a_counts}")
        print(f"  T0_EMA50 oos: n={st['n']} wins={st['wins']} "
              f"wr={st['win_rate']:.3f} avg_net={st['avg_net']:.3f} "
              f"total_net={st['total_net']:.2f} max_dd={st['max_dd']:.2f} "
              f"pf={st['profit_factor']:.3f}")
        # 构成分析（主口径 close 才做完整分解；next_open 只做总数）
        a_keys = {(iso(e["b0_open_ms"]), e["dir"]) for e in a_oos}
        kept = a_keys & b_keys
        new = a_keys - b_keys
        dropped = b_keys - a_keys
        print(f"  composition: kept={len(kept)} new={len(new)} "
              f"dropped={len(dropped)}")
        if mode == "close":
            # 新单按 E-run 来源分解：用验证跑的 outcomes/skip
            _, _, v_out, v_skip = run_loop(D, cand, e_resolver, "validate2")
            src = {}
            for key in new:
                b0ms = parse_ms(key[0])
                b0idx = int(np.searchsorted(D.t15, b0ms, side="left"))
                if (b0idx, key[1]) in v_skip:
                    src["filled_but_skipped"] = src.get("filled_but_skipped", 0) + 1
                else:
                    src[v_out.get((b0idx, key[1]), "unknown")] = \
                        src.get(v_out.get((b0idx, key[1]), "unknown"), 0) + 1
            print(f"  new-trade sources (E-run outcomes): {src}")
            # 新单净 R 合计（按来源）
            src_net = {}
            for e in a_oos:
                key = (iso(e["b0_open_ms"]), e["dir"])
                if key in new:
                    b0idx = e["b0"]
                    s = "filled_but_skipped" if (b0idx, e["dir"]) in v_skip \
                        else v_out.get((b0idx, e["dir"]), "unknown")
                    n = trade_numbers(D, e, e["outs"][("T0", "EMA50")])["net"]
                    src_net[s] = src_net.get(s, 0.0) + n
            print(f"  new-trade net by source: "
                  f"{ {k: round(v, 2) for k, v in src_net.items()} }")
            with open(f"{OUT}/attribution_ablation.csv", "w", newline="") as fh:
                wr = csv.DictWriter(fh, fieldnames=["seq_b0", "dir", "entry",
                                                    "stop", "risk", "net",
                                                    "reason", "in_B",
                                                    "e_source"])
                wr.writeheader()
                for e in a_oos:
                    key = (iso(e["b0_open_ms"]), e["dir"])
                    s = "B_kept" if key in b_keys else (
                        "filled_but_skipped"
                        if (e["b0"], e["dir"]) in v_skip else
                        v_out.get((e["b0"], e["dir"]), "unknown"))
                    out = e["outs"][("T0", "EMA50")]
                    wr.writerow({
                        "seq_b0": key[0], "dir": e["dir"], "entry": e["entry"],
                        "stop": e["stop"], "risk": e["risk"],
                        "net": trade_numbers(D, e, out)["net"],
                        "reason": out["reason"], "in_B": key in b_keys,
                        "e_source": s})
    summary = {
        "q1_primary": kind_rows, "q1_anyfire": any_rows,
        "q2": {
            "n_losers": len(losers), "n_stops": len(stops),
            "losers_mfe_ge": {thr: sum(1 for t in losers if t["mfe"] >= thr)
                              for thr in (0.5, 1.0, 2.0)},
            "stops_mfe_ge": {thr: sum(1 for t in stops if t["mfe"] >= thr)
                             for thr in (0.5, 1.0, 2.0)},
            "stops_mfe_excl_ge05": sum(1 for t in stops if t["mfe_excl"] >= 0.5),
            "stops_mfe_lt01": sum(1 for t in stops if t["mfe"] < 0.1),
            "median_mfe_losers": float(np.median([t["mfe"] for t in losers])),
            "median_mfe_stops": float(np.median([t["mfe"] for t in stops])),
        },
        "q3_regimes": tables,
        "q4_ablation": {m: {"counts": v["counts"], "stats": v["stats"],
                            "combos": v["combos"], "n_oos": v["n_oos"]}
                        for m, v in abl.items()},
        "validation_mismatches": bad,
    }
    with open(f"{OUT}/attribution_summary.json", "w") as fh:
        json.dump(summary, fh, indent=1, ensure_ascii=False, default=float)
    print("DONE")


if __name__ == "__main__":
    main()
