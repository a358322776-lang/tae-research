"""TAE-B1 audit (read-only): sampling + Task2 level recheck + Task3 execution recheck.
Writes: audit-v0.1/sampling.csv, level_check.csv, exec_check.csv, audit_run.json.
Does NOT modify any production file. Reads engine outputs + stitched data only."""
import bisect
import csv
import json
import random
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/hidden_files")
from b1_engine import Data, simulate_exit, BOUNDARY_MS  # noqa: E402
from b1_lib import atr_series, swings_tie  # noqa: E402
from key_levels import find_levels  # noqa: E402

B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1"
OUT = f"{B1}/audit-v0.1"
SEED = 20261026

import os
os.makedirs(OUT, exist_ok=True)


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M")


# ---------- load data ----------
D = Data()
t15, o15, t5, o5 = D.t15, D.o15, D.t5, D.o5
c15 = o15[:, 3]
atr15 = D.atr15
entries = json.load(open("/tmp/audit_b_oos_entries.json"))
assert len(entries) == 123
rows_csv = list(csv.DictReader(open(f"{B1}/trades_b_oos.csv")))
# trade IDs B001..B123 in CSV (fill-time) order; verify fill times ascending
fills = [e["fill_close_ms"] for e in entries]
assert fills == sorted(fills), "entries not in fill order"
for i, e in enumerate(entries):
    e["tid"] = f"B{i+1:03d}"
    r = rows_csv[i]
    assert abs(e["entry"] - float(r["entry"])) < 1e-9
    e["csv"] = r

# 1h ATR + swings for trend (levels_pass replication, used for charts + context)
d1h = np.load(f"{B1}/data_cache/stitched_1h.npz")
t1h, o1h = d1h["t"], d1h["ohlc"]
tr1 = np.full(len(o1h), np.nan)
for i in range(1, len(o1h)):
    tr1[i] = max(o1h[i][1] - o1h[i][2], abs(o1h[i][1] - o1h[i - 1][3]),
                 abs(o1h[i][2] - o1h[i - 1][3]))
atr1 = np.full(len(o1h), np.nan)
for i in range(13, len(o1h)):
    atr1[i] = float(np.nanmean(tr1[i - 13:i + 1]))
hi_all, lo_all = swings_tie(o1h)
hi_idx = [i for i, _ in hi_all]
hi_val = [v for _, v in hi_all]
lo_idx = [i for i, _ in lo_all]
lo_val = [v for _, v in lo_all]
t1h_close = t1h + 3_600_000
t15_close = t15 + 900_000


def trend_at(j):
    p = int(np.searchsorted(t1h_close, t15_close[j], side="right"))
    if p < 60 or np.isnan(atr1[p - 1]):
        return None
    a = atr1[p - 1]
    thr = 0.5 * a
    hi = [v for idx, v in zip(hi_idx, hi_val) if idx <= p - 3][-3:]
    lo = [v for idx, v in zip(lo_idx, lo_val) if idx <= p - 3][-3:]
    if len(hi) < 3 or len(lo) < 3:
        return None
    hs = [hi[i + 1] - hi[i] for i in range(2)]
    ls = [lo[i + 1] - lo[i] for i in range(2)]
    if all(x >= thr for x in hs) and all(x >= thr for x in ls):
        return "long"
    if all(x <= -thr for x in hs) and all(x <= -thr for x in ls):
        return "short"
    return None


# ---------- sampling ----------
def year_of(e):
    return datetime.fromtimestamp(e["fill_open_ms"] / 1000, timezone.utc).year


def lag_of(e):
    return e["reclaim_idx"] - e["b0"]


def lag_bucket(lag):
    return "fast" if lag <= 2 else ("mid" if lag <= 10 else "slow")


for e in entries:
    e["year"] = year_of(e)
    e["lag"] = lag_of(e)
    e["lag_bucket"] = lag_bucket(e["lag"])
    e["net"] = float(e["csv"]["net_T0_EMA50"])
    e["win"] = e["net"] > 0

QUOTA = {2020: 6, 2021: 4, 2022: 6, 2023: 4, 2024: 5, 2025: 5}
rng = random.Random(SEED)
by_year = {}
for e in entries:
    by_year.setdefault(e["year"], []).append(e)
picked = []
notes = []
for y in sorted(QUOTA):
    pool = by_year[y][:]
    rng.shuffle(pool)
    sel = []
    winners = [e for e in pool if e["win"]]
    if winners and QUOTA[y] > 0:
        sel.append(winners[0])
    for e in pool:
        if len(sel) >= QUOTA[y]:
            break
        if e not in sel:
            sel.append(e)
    picked.extend(sel)
    notes.append(f"{y}: quota {QUOTA[y]}, picked {[e['tid'] for e in sel]}, "
                 f"winners_in_year={len(winners)}")


def bucket_counts(sel):
    c = {"fast": 0, "mid": 0, "slow": 0}
    for e in sel:
        c[e["lag_bucket"]] += 1
    return c


swaps = []
# repair: slow >= 4, mid >= 6, winners >= 6 (seeded swaps, same-year only)
for need_bucket, need_n in (("slow", 4), ("mid", 6)):
    while bucket_counts(picked)[need_bucket] < need_n:
        done = False
        for y in sorted(QUOTA):
            sel_y = [e for e in picked if e["year"] == y]
            unpicked = [e for e in by_year[y] if e not in picked
                        and e["lag_bucket"] == need_bucket]
            donors = [e for e in sel_y if e["lag_bucket"] not in (need_bucket,)
                      and not (e["win"] and sum(1 for x in sel_y if x["win"]) <= 1)]
            if unpicked and donors:
                out_e, in_e = donors[-1], unpicked[0]
                picked.remove(out_e)
                picked.append(in_e)
                swaps.append(f"swap for {need_bucket} coverage in {y}: "
                             f"out {out_e['tid']}({out_e['lag_bucket']}) "
                             f"in {in_e['tid']}({in_e['lag_bucket']})")
                done = True
                break
        if not done:
            swaps.append(f"WARNING: could not reach {need_bucket}>={need_n}")
            break
while sum(1 for e in picked if e["win"]) < 6:
    done = False
    for y in sorted(QUOTA):
        sel_y = [e for e in picked if e["year"] == y]
        unpicked_w = [e for e in by_year[y] if e not in picked and e["win"]]
        donors = [e for e in sel_y if not e["win"]]
        if unpicked_w and donors:
            out_e, in_e = donors[-1], unpicked_w[0]
            picked.remove(out_e)
            picked.append(in_e)
            swaps.append(f"swap for winner coverage in {y}: out {out_e['tid']} "
                         f"in {in_e['tid']}")
            done = True
            break
    if not done:
        swaps.append("WARNING: could not reach winners>=6")
        break
picked.sort(key=lambda e: e["fill_close_ms"])
bc = bucket_counts(picked)
print(f"sample n={len(picked)} winners={sum(1 for e in picked if e['win'])} "
      f"buckets={bc} dirs={ {d: sum(1 for e in picked if e['dir']==d) for d in ('long','short')} }", flush=True)
print("sample tids:", [e["tid"] for e in picked], flush=True)
for n in notes:
    print("  ", n, flush=True)
for s in swaps:
    print("  ", s, flush=True)

with open(f"{OUT}/sampling.csv", "w", newline="") as fh:
    wr = csv.writer(fh)
    wr.writerow(["sample_no", "trade_id", "fill_time", "dir", "year", "net_T0_EMA50",
                 "base_reason", "lag_bars", "lag_bucket", "band_lo", "band_hi",
                 "entry", "stop", "risk_pts"])
    for i, e in enumerate(picked, 1):
        wr.writerow([i, e["tid"], iso(e["fill_close_ms"]), e["dir"], e["year"],
                     f"{e['net']:.4f}", e["base"]["reason"], e["lag"],
                     e["lag_bucket"], e["blo"], e["bhi"], e["entry"],
                     e["stop"], e["risk"]])
json.dump({"seed": SEED, "quota": QUOTA, "notes": notes, "swaps": swaps,
           "tids": [e["tid"] for e in picked],
           "bucket_counts": bc,
           "winners": sum(1 for e in picked if e["win"])},
          open(f"{OUT}/sampling_meta.json", "w"), indent=1, ensure_ascii=False)
# save picked entries for chart script
json.dump(picked, open("/tmp/audit_picked.json", "w"))

# ---------- Task 2: level recheck ----------
# instrumented reimplementation of key_levels (exposes cluster + valid touches)
SWING_K = 2
CLUSTER_TOL = 0.35
LINE_EPS = 0.2
LINE_RAD = 0.6
HOLD_PUSH = 1.0
HOLD_HORIZON = 8
CLOSE_HORIZON = 4
MIN_TOUCH = 3
MAX_TOUCH = 9
STALE_BARS = 96


def swings_strict(candles):
    hi, lo = [], []
    for i in range(2, len(candles) - 2):
        h, l = candles[i]["h"], candles[i]["l"]
        if all(h > candles[j]["h"] for j in range(i - 2, i + 3) if j != i):
            hi.append((i, h))
        if all(l < candles[j]["l"] for j in range(i - 2, i + 3) if j != i):
            lo.append((i, l))
    return hi, lo


def held_res(candles, idx, price, band_top, a):
    after = candles[idx + 1: idx + 1 + HOLD_HORIZON]
    if not after:
        return False
    if any(c["c"] > band_top for c in candles[idx + 1: idx + 1 + CLOSE_HORIZON]):
        return False
    return price - min(c["l"] for c in after) >= HOLD_PUSH * a


def held_sup(candles, idx, price, band_bottom, a):
    after = candles[idx + 1: idx + 1 + HOLD_HORIZON]
    if not after:
        return False
    if any(c["c"] < band_bottom for c in candles[idx + 1: idx + 1 + CLOSE_HORIZON]):
        return False
    return max(c["h"] for c in after) - price >= HOLD_PUSH * a


def clusters_of(points, tol):
    pts = sorted(points, key=lambda x: x[1])
    out, cur = [], [pts[0]]
    for p in pts[1:]:
        if p[1] - cur[-1][1] <= tol:
            cur.append(p)
        else:
            out.append(cur)
            cur = [p]
    out.append(cur)
    return out


def instrumented_levels(candles, a):
    """Returns list of dicts with kind/line/band/touches/last_touch_idx/
    first_touch_idx/cluster_span_bars/all_cluster_members, mirroring key_levels."""
    hi, lo = swings_strict(candles)
    res = []
    for cl in clusters_of(hi, CLUSTER_TOL * a):
        band_all = (min(v for _, v in cl), max(v for _, v in cl))
        valid = [(i, v) for i, v in cl if held_res(candles, i, v, band_all[1], a)]
        if len(valid) < MIN_TOUCH:
            continue
        valid = valid[-MAX_TOUCH:]
        vals = [v for _, v in valid]
        last_i = max(i for i, _ in valid)
        if len(candles) - 1 - last_i > STALE_BARS:
            continue
        res.append({"kind": "resistance", "line": min(vals),
                    "band": (min(vals), max(vals)), "touches": len(valid),
                    "last_touch_idx": last_i,
                    "first_touch_idx": min(i for i, _ in valid),
                    "cluster_members": cl, "valid": valid})
    remaining = list(lo)
    while remaining:
        best_line, best_touch = None, []
        for _, cand in remaining:
            touch = [p for p in remaining if abs(p[1] - cand) <= LINE_EPS * a]
            if len(touch) > len(best_touch):
                best_line, best_touch = cand, touch
        if len(best_touch) < MIN_TOUCH:
            break
        members = [p for p in remaining if abs(p[1] - best_line) <= LINE_RAD * a]
        members.sort(key=lambda x: abs(x[1] - best_line))
        members = members[:MAX_TOUCH + 3]
        band_all = (min(v for _, v in members), max(v for _, v in members))
        valid = [(i, v) for i, v in members if held_sup(candles, i, v, band_all[0], a)]
        used = set(id(p) for p in members)
        remaining = [p for p in remaining if id(p) not in used]
        if len(valid) < MIN_TOUCH:
            continue
        valid = valid[-MAX_TOUCH:]
        vals = [v for _, v in valid]
        last_i = max(i for i, _ in valid)
        if len(candles) - 1 - last_i > STALE_BARS:
            continue
        res.append({"kind": "support", "line": best_line,
                    "band": (min(vals), max(vals)), "touches": len(valid),
                    "last_touch_idx": last_i,
                    "first_touch_idx": min(i for i, _ in valid),
                    "cluster_members": members, "valid": valid})
    # dedup (same rule as find_levels)
    lv = res
    lv.sort(key=lambda x: -x["touches"])
    kept = []
    for L in lv:
        dup = False
        for K in kept:
            lo_ = max(L["band"][0], K["band"][0])
            hi_ = min(L["band"][1], K["band"][1])
            if hi_ > lo_ and (hi_ - lo_) >= 0.5 * min(L["band"][1] - L["band"][0],
                                                     K["band"][1] - K["band"][0]):
                dup = True
                break
        if not dup:
            kept.append(L)
    kept.sort(key=lambda x: x["line"])
    return kept


def window_candles(j):
    return [{"o": float(r[0]), "h": float(r[1]), "l": float(r[2]), "c": float(r[3])}
            for r in o15[j - 399:j + 1]]


# band-width distribution over all 123 (for percentiles)
widths = []
for e in entries:
    a = float(atr15[e["b0"]])
    widths.append(((e["bhi"] - e["blo"]) / a, e["tid"]))
widths_sorted = sorted(w for w, _ in widths)
import bisect as _b
def pct(w):
    return _b.bisect_left(widths_sorted, w) / len(widths_sorted) * 100

level_rows = []
for e in picked:
    j = e["b0"]
    d = e["dir"]
    a = float(atr15[j])
    win = window_candles(j)
    real = find_levels(win, a)
    kind = "resistance" if d == "long" else "support"
    match = [L for L in real if L["kind"] == kind
             and abs(L["band"][0] - e["blo"]) < 1e-9
             and abs(L["band"][1] - e["bhi"]) < 1e-9]
    inst = instrumented_levels(win, a)
    imatch = [L for L in inst if L["kind"] == kind
              and abs(L["band"][0] - e["blo"]) < 1e-9
              and abs(L["band"][1] - e["bhi"]) < 1e-9]
    # pullback scan: first touch bar + touch-bar count in (b0, reclaim]
    r = e["reclaim_idx"]
    touch_idx = None
    n_touch_bars = 0
    for k in range(j + 1, r + 1):
        lk, hk = float(o15[k][2]), float(o15[k][1])
        if lk <= e["bhi"] and hk >= e["blo"]:
            n_touch_bars += 1
            if touch_idx is None:
                touch_idx = k
    atr_r = float(atr15[r])
    ex = e["touch_extreme"]
    if d == "long":
        depth_bhi = (e["bhi"] - ex) / atr_r
        beyond = (e["blo"] - ex) / atr_r  # >0 means dipped below band
        inside = ex >= e["blo"]
    else:
        depth_bhi = (ex - e["blo"]) / atr_r
        beyond = (ex - e["bhi"]) / atr_r
        inside = ex <= e["bhi"]
    w_atr = (e["bhi"] - e["blo"]) / a
    row = {
        "trade_id": e["tid"], "dir": d, "b0_time": iso(int(t15[j])),
        "band_lo": e["blo"], "band_hi": e["bhi"], "atr_b0": round(a, 4),
        "real_match": len(match) > 0,
        "inst_match": len(imatch) > 0,
        "band_dev_atr": 0.0 if match else None,
        "level_touches": imatch[0]["touches"] if imatch else "",
        "level_line": imatch[0]["line"] if imatch else "",
        "last_touch_age_bars": (399 - imatch[0]["last_touch_idx"]) if imatch else "",
        "first_touch_age_bars": (399 - imatch[0]["first_touch_idx"]) if imatch else "",
        "cluster_span_bars": (imatch[0]["last_touch_idx"] - imatch[0]["first_touch_idx"]) if imatch else "",
        "cluster_members_n": len(imatch[0]["cluster_members"]) if imatch else "",
        "band_width_atr": round(w_atr, 4),
        "band_width_pct123": round(pct(w_atr), 1),
        "reclaim_lag_bars": e["lag"],
        "first_touch_bar_offset": (touch_idx - j) if touch_idx is not None else "",
        "n_touch_bars": n_touch_bars,
        "touch_extreme": ex,
        "pullback_depth_atr": round(depth_bhi, 4),
        "beyond_band_atr": round(beyond, 4),
        "extreme_inside_band": inside,
        "trend_1h_at_b0": trend_at(j),
    }
    level_rows.append(row)
    print(f"  L2 {e['tid']} match={row['real_match']}/{row['inst_match']} "
          f"touches={row['level_touches']} last_age={row['last_touch_age_bars']} "
          f"width_atr={row['band_width_atr']} pct={row['band_width_pct123']} "
          f"lag={e['lag']} depth={row['pullback_depth_atr']} beyond={row['beyond_band_atr']} "
          f"trend={row['trend_1h_at_b0']}", flush=True)

with open(f"{OUT}/level_check.csv", "w", newline="") as fh:
    wr = csv.DictWriter(fh, fieldnames=list(level_rows[0].keys()))
    wr.writeheader()
    wr.writerows(level_rows)

# ---------- Task 3: execution recheck ----------
FEE = 0.0005
STOP_SLIP = 0.0005
TIER_PEN = {"T0": 0.0, "T1": 0.0005, "T2": 0.001}


def stop_scan(e, tier):
    """Replicate simulate_exit stop scan for one tier; return trigger 5m idx or None,
    plus the containing 15m idx. Exit determination (stop vs EMA) still via simulate_exit."""
    d, stop = e["dir"], e["stop"]
    pen = TIER_PEN[tier]
    thr = stop * (1 - pen) if d == "long" else stop * (1 + pen)
    f_open = int(t5[e["fill_idx"]])
    cont_open = f_open - (f_open % 900_000)
    k0 = int(np.searchsorted(t15, cont_open, side="left"))
    for k in range(k0 + 1, len(t15)):
        mk = int(np.searchsorted(t5, int(t15[k]), side="left"))
        for m in range(mk, min(mk + 3, len(t5))):
            if d == "long" and float(o5[m][2]) <= thr:
                return m, k, thr
            if d == "short" and float(o5[m][1]) >= thr:
                return m, k, thr
    return None, None, thr


def net_of(e, exit_px, exit_close_ms):
    d, entry, stop, risk = e["dir"], e["entry"], e["stop"], e["risk"]
    sd = risk / entry
    gross = (exit_px - entry) / risk if d == "long" else (entry - exit_px) / risk
    fee_r = 2 * FEE / sd
    fsum = D.funding_sum(e["fill_open_ms"], exit_close_ms)
    fund = fsum / sd if d == "long" else -fsum / sd
    return gross - fee_r - fund, gross, fee_r, fund


exec_rows = []
for e in picked:
    d = e["dir"]
    base = e["base"]
    # (a) fill-bar free pass: 5m bars of fill's 15m bar after the fill bar
    f_open = int(t5[e["fill_idx"]])
    cont_open = f_open - (f_open % 900_000)
    k0 = int(np.searchsorted(t15, cont_open, side="left"))
    mk0 = int(np.searchsorted(t5, int(t15[k0]), side="left"))
    stop = e["stop"]
    thr0 = stop if d == "long" else stop
    breach_fill_bar = None
    breach_later = None
    for m in range(mk0, min(mk0 + 3, len(t5))):
        hit = (float(o5[m][2]) <= stop) if d == "long" else (float(o5[m][1]) >= stop)
        if m == e["fill_idx"]:
            breach_fill_bar = hit
        elif m > e["fill_idx"] and hit and breach_later is None:
            breach_later = m
    # counterfactual net if the later-bar breach had exited at stop fill
    cf_net = ""
    if breach_later is not None:
        ex_px = stop * (1 - STOP_SLIP) if d == "long" else stop * (1 + STOP_SLIP)
        cf_net, _, _, _ = net_of(e, ex_px, int(t5[breach_later]) + 300_000)
        cf_net = round(cf_net, 4)
    # (b) same-15m stop+EMA coincidence: for stop exits, does exit bar close cross EMA?
    ema_cross_same_bar = ""
    if base["reason"] == "stop":
        # exit bar (15m) containing the stop trigger 5m bar
        m_trig, k_trig, _ = stop_scan(e, "T0")
        if k_trig is not None:
            ref = float(D.ema50[k_trig])
            ck = float(c15[k_trig])
            ema_cross_same_bar = (ck < ref) if d == "long" else (ck > ref)
    # (c) stop tiers
    tier_info = {}
    for tier in ("T0", "T1", "T2"):
        m_trig, k_trig, thr = stop_scan(e, tier)
        out = simulate_exit(D, e, tier, "EMA50")
        ex_px_formula = stop * (1 - STOP_SLIP) if d == "long" else stop * (1 + STOP_SLIP)
        tier_info[tier] = {
            "trig_5m": iso(int(t5[m_trig])) if m_trig is not None else "",
            "exit_px": out["exit_px"] if out else "",
            "reason": out["reason"] if out else "unresolved",
            "formula_px": ex_px_formula,
            "thr": thr,
        }
    t0_px_csv = float(e["csv"]["base_exit_px"])
    t0_match = (base["reason"] == "stop" and
                abs(tier_info["T0"]["exit_px"] - t0_px_csv) < 1e-9) if base["reason"] == "stop" else ""
    # T2 fill vs trigger inversion (long: fill > thr; short: fill < thr)
    t2_thr = tier_info["T2"]["thr"]
    t2_fill = tier_info["T2"]["formula_px"]
    t2_inversion = (t2_fill > t2_thr) if d == "long" else (t2_fill < t2_thr)
    # (d) EMA exit next-open comparison
    ema_next_open = ""
    ema_next_net = ""
    ema_delta = ""
    if base["reason"] == "EMA50":
        k_exit = int(np.searchsorted(t15, base["exit_close_ms"], side="right")) - 1
        if k_exit + 1 < len(t15):
            nxt = float(o15[k_exit + 1][0])
            ema_next_open = nxt
            nn, _, _, _ = net_of(e, nxt, int(t15[k_exit + 1]) + 900_000)
            ema_next_net = round(nn, 4)
            ema_delta = round(nn - e["net"], 4)
    # (e) fee + funding recompute
    sd = e["risk"] / e["entry"]
    fee_re = 2 * FEE / sd
    fee_csv = float(e["csv"]["base_fee"])
    fsum = D.funding_sum(e["fill_open_ms"], base["exit_close_ms"])
    fund_re = fsum / sd if d == "long" else -fsum / sd
    fund_csv = float(e["csv"]["base_funding"])
    # funding boundary settlements
    fund_ts = D.fund_ts
    b_fill = bisect.bisect_right(fund_ts, e["fill_open_ms"])
    b_exit = bisect.bisect_right(fund_ts, base["exit_close_ms"])
    on_fill = (b_fill > 0 and fund_ts[b_fill - 1] == e["fill_open_ms"])
    on_exit = (b_exit > 0 and fund_ts[b_exit - 1] == base["exit_close_ms"])
    row = {
        "trade_id": e["tid"], "dir": d, "base_reason": base["reason"],
        "fill_15m_idx": k0, "fill_5m_idx": e["fill_idx"],
        "breach_in_fill_5m_bar": breach_fill_bar,
        "breach_in_later_5m_of_fill_15m": breach_later is not None,
        "breach_later_5m_time": iso(int(t5[breach_later])) if breach_later is not None else "",
        "counterfactual_stop_net_if_exited": cf_net,
        "actual_net_T0_EMA50": round(e["net"], 4),
        "ema_cross_in_stop_exit_bar": ema_cross_same_bar,
        "T0_trig_5m": tier_info["T0"]["trig_5m"],
        "T0_exit_px_recomputed": tier_info["T0"]["exit_px"],
        "T0_exit_px_csv": t0_px_csv if base["reason"] == "stop" else "",
        "T0_px_match_csv": t0_match,
        "T1_reason": tier_info["T1"]["reason"],
        "T1_trig_5m": tier_info["T1"]["trig_5m"],
        "T2_reason": tier_info["T2"]["reason"],
        "T2_trig_5m": tier_info["T2"]["trig_5m"],
        "T2_fill_better_than_trigger": t2_inversion,
        "ema_exit_next_open": ema_next_open,
        "ema_exit_net_at_next_open": ema_next_net,
        "ema_next_open_delta_R": ema_delta,
        "fee_recomputed": round(fee_re, 6),
        "fee_csv": fee_csv,
        "fee_match": abs(fee_re - fee_csv) < 1e-9,
        "funding_recomputed_R": round(fund_re, 6),
        "funding_csv_R": fund_csv,
        "funding_match": abs(fund_re - fund_csv) < 1e-9,
        "funding_settlement_on_fill_open": on_fill,
        "funding_settlement_on_exit_close": on_exit,
    }
    exec_rows.append(row)
    print(f"  X3 {e['tid']} reason={base['reason']} fillbreach={breach_fill_bar} "
          f"laterbreach={breach_later is not None} cf={cf_net} "
          f"ema_same_bar={ema_cross_same_bar} T0match={t0_match} "
          f"ema_delta={ema_delta} fee_ok={row['fee_match']} fund_ok={row['funding_match']}",
          flush=True)

with open(f"{OUT}/exec_check.csv", "w", newline="") as fh:
    wr = csv.DictWriter(fh, fieldnames=list(exec_rows[0].keys()))
    wr.writeheader()
    wr.writerows(exec_rows)

json.dump({"widths123": widths_sorted,
           "n_level_match": sum(1 for r in level_rows if r["real_match"]),
           "n_inst_match": sum(1 for r in level_rows if r["inst_match"])},
          open(f"{OUT}/audit_run.json", "w"), indent=1)
print("DONE audit_main", flush=True)
