"""TAE-L1 分析脚本（描述性，无收益计算）。

输入：普查 events_census.csv + 拼接 15m/5m K 线缓存（只读）。
输出：l1_events.csv（L1-A/B/C 事件表）+ l1_stats.json（描述性统计）。
口径：
- L1-A = 普查中 outcome=voided 的序列（突破后收盘穿越远沿 = 假突破）。
  作废根 v = (b0, b0+48] 内首根收盘穿越远沿的 15m 根；作废时刻 = 该根收盘。
- L1-B = 序列回踩窗口内出现远沿影线穿越但收盘未穿越的根（影线扫掠候选）。
  窗口：首触根（有触碰）或 b0+1（无触碰）→ 收复根（含）/ 作废根（含，收盘条件滤掉作废根本身）/ b0+48。
- L1-C = 作废序列之后、同方向下一序列在作废后 96 根内出现且自身作废/过期。
- 15m bar 时间以 OPEN 计；收盘 = OPEN + 15 分钟。5m 子根 = OPEN、+5、+10 分钟。
- ATR(15m,14) 均值型，与 B1 一致；仅用于描述性深度单位，不参与任何盈亏。
"""
import bisect
import csv
import json
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/hidden_files")
from b1_lib import atr_series  # noqa: E402  只读复用

B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1"
OUT = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/tae-l1"


def ts(ms):
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M")


d15 = np.load(f"{B1}/data_cache/stitched_15m.npz")
t15, o15 = d15["t"], d15["ohlc"]
d5 = np.load(f"{B1}/data_cache/stitched_5m.npz")
t5, o5 = d5["t"], d5["ohlc"]
atr15 = atr_series(o15, 14)
N15 = len(t15)

with open(f"{B1}/structure-events/events_census.csv", encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))
seqs = [r for r in rows if r["outcome"] in ("reclaimed", "voided", "expired")]
by_id = {r["seq_id"]: r for r in rows}


def far_edge(r):
    return float(r["band_lo"]), float(r["band_hi"])


def void_index(r):
    """作废根下标；非作废序列返回 None。"""
    if r["outcome"] != "voided":
        return None
    j = int(r["b0_idx"])
    blo, bhi = far_edge(r)
    for k in range(j + 1, min(j + 49, N15)):
        c = o15[k][3]
        if r["dir"] == "long" and c < blo:
            return k
        if r["dir"] == "short" and c > bhi:
            return k
    return None


def reclaim_index(r):
    if r["reclaimed"] != "1":
        return None
    return int(r["b0_idx"]) + int(r["reclaim_lag_bars"])


def first_touch_index(r):
    if r["touched"] != "1":
        return None
    return int(r["b0_idx"]) + int(r["first_touch_lag_bars"])


def seq_extremes(r, v):
    """[b0, v] 区间极值：long -> (max_high, min_low)；short 镜像返回 (min_low, max_high)。"""
    j = int(r["b0_idx"])
    seg = o15[j:v + 1]
    return float(np.max(seg[:, 1])), float(np.min(seg[:, 2]))


def post_window_stats(r, v, horizon):
    """作废后窗口 (v, v+horizon] 结构结局（只用价格结构量）。
    返回：re_reclaim（收盘回近沿）、resume（极值超突破侧极值）、fade_ext（极值超回撤侧极值）、
    首事件顺序（resume 与 fade_ext 按根下标比，同根记 tie）。"""
    blo, bhi = far_edge(r)
    hi, lo = seq_extremes(r, v)
    out = {"re_reclaim": 0, "resume": 0, "fade_ext": 0, "first_order": ""}
    first_res = first_fade = None
    for k in range(v + 1, min(v + horizon + 1, N15)):
        o, h, l, c = o15[k]
        if r["dir"] == "long":
            if c > bhi:
                out["re_reclaim"] = 1
            if h > hi and first_res is None:
                first_res = k
            if l < lo and first_fade is None:
                first_fade = k
        else:
            if c < blo:
                out["re_reclaim"] = 1
            if l < lo and first_res is None:
                first_res = k
            if h > hi and first_fade is None:
                first_fade = k
        if first_res is not None and first_fade is not None:
            break
    out["resume"] = 1 if first_res is not None else 0
    out["fade_ext"] = 1 if first_fade is not None else 0
    if first_res is None and first_fade is None:
        out["first_order"] = "neither"
    elif first_res is not None and first_fade is None:
        out["first_order"] = "resume_only"
    elif first_fade is not None and first_res is None:
        out["first_order"] = "fade_only"
    elif first_res < first_fade:
        out["first_order"] = "resume_first"
    elif first_fade < first_res:
        out["first_order"] = "fade_first"
    else:
        out["first_order"] = "same_bar_tie"
    return out


def entry_bar_check(r, v):
    """L1-A 入场变体 (ii) 止损入场：触发价 = 作废根极值（long 取作废根 low，short 取作废根 high）；
    止损 = [b0, v] 突破侧极值（long 取 max high，short 取 min low），缓冲 0（测量用，草案中缓冲待定）。
    入场窗 (v, v+48]。返回入场根、15m 歧义类、5m 歧义类、开盘跳穿止损与否。"""
    j = int(r["b0_idx"])
    hi, lo = seq_extremes(r, v)
    vo, vh, vl, vc = o15[v]
    if r["dir"] == "long":
        trigger, stop = float(vl), float(hi)
    else:
        trigger, stop = float(vh), float(lo)
    for k in range(v + 1, min(v + 49, N15)):
        o, h, l, c = o15[k]
        touched_trigger = (l <= trigger) if r["dir"] == "long" else (h >= trigger)
        if not touched_trigger:
            continue
        touches_stop_15m = (h >= stop) if r["dir"] == "long" else (l <= stop)
        if not touches_stop_15m:
            return {"entry_idx": k, "class15": "clean", "class5": "clean",
                    "open_gap_stop": 1 if ((o >= stop) if r["dir"] == "long" else (o <= stop)) else 0}
        base = bisect.bisect_left(t5, t15[k])
        e5 = s5 = None
        for m in range(3):
            so, sh, sl, sc = o5[base + m]
            if r["dir"] == "long":
                if e5 is None and sl <= trigger:
                    e5 = m
                if s5 is None and sh >= stop:
                    s5 = m
            else:
                if e5 is None and sh >= trigger:
                    e5 = m
                if s5 is None and sl <= stop:
                    s5 = m
        if e5 is None or s5 is None:
            cls5 = "unresolved_5m"
        elif e5 < s5:
            cls5 = "entry_first"
        elif s5 < e5:
            cls5 = "stop_first"
        else:
            cls5 = "same_5m_bar"
        return {"entry_idx": k, "class15": "ambiguous", "class5": cls5,
                "open_gap_stop": 1 if ((o >= stop) if r["dir"] == "long" else (o <= stop)) else 0}
    return {"entry_idx": None, "class15": "no_entry_48", "class5": "no_entry_48",
            "open_gap_stop": 0}


def sweep_scan(r):
    """L1-B：回踩窗口内远沿影线穿越但收盘未穿越的根。返回（扫掠根数，首扫掠根下标，最大穿透 ATR）。"""
    blo, bhi = far_edge(r)
    j = int(r["b0_idx"])
    ft = first_touch_index(r)
    start = ft if ft is not None else j + 1
    if r["outcome"] == "reclaimed":
        end = reclaim_index(r)
    elif r["outcome"] == "voided":
        end = void_index(r)
    else:
        end = j + 48
    if end is None:
        return 0, None, 0.0
    n = 0
    first = None
    maxdep = 0.0
    for k in range(start, min(end + 1, N15)):
        o, h, l, c = o15[k]
        a = atr15[k]
        if r["dir"] == "long":
            if l < blo and c >= blo:
                n += 1
                if first is None:
                    first = k
                if a and not np.isnan(a):
                    maxdep = max(maxdep, (blo - l) / a)
        else:
            if h > bhi and c <= bhi:
                n += 1
                if first is None:
                    first = k
                if a and not np.isnan(a):
                    maxdep = max(maxdep, (h - bhi) / a)
    return n, first, maxdep


# ---------- L1-A ----------
l1a = []
for r in seqs:
    if r["outcome"] != "voided":
        continue
    v = void_index(r)
    assert v is not None, f"no void bar for {r['seq_id']}"
    assert ts(int(t15[v]) + 900000) == r["outcome_time_utc"], r["seq_id"]
    hi, lo = seq_extremes(r, v)
    p48 = post_window_stats(r, v, 48)
    p96 = post_window_stats(r, v, 96)
    eb = entry_bar_check(r, v)
    a = atr15[v]
    l1a.append({
        "candidate": "L1-A", "seq_id": r["seq_id"], "window": r["window"], "dir": r["dir"],
        "b0_time_utc": r["b0_time_utc"], "band_lo": r["band_lo"], "band_hi": r["band_hi"],
        "band_width_atr": r["band_width_atr"], "band_touches": r["band_touches"],
        "trend_v02_at_b0": r["trend_v02_at_b0"], "touched_before_void": r["touched"],
        "void_lag_bars": v - int(r["b0_idx"]), "void_time_utc": ts(int(t15[v]) + 900000),
        "seq_breakout_extreme": hi if r["dir"] == "long" else lo,
        "seq_fade_extreme": lo if r["dir"] == "long" else hi,
        "post48_re_reclaim": p48["re_reclaim"], "post48_resume": p48["resume"],
        "post48_fade_ext": p48["fade_ext"], "post48_first_order": p48["first_order"],
        "post96_re_reclaim": p96["re_reclaim"], "post96_resume": p96["resume"],
        "post96_fade_ext": p96["fade_ext"], "post96_first_order": p96["first_order"],
        "entry_found_48": 1 if eb["entry_idx"] is not None else 0,
        "entry_time_utc": ts(int(t15[eb["entry_idx"]])) if eb["entry_idx"] is not None else "",
        "entry_class_15m": eb["class15"], "entry_class_5m": eb["class5"],
        "entry_open_gap_stop": eb["open_gap_stop"],
        "void_depth_atr": (round(abs(float(r["extreme_value"]) - (float(r["band_lo"]) if r["dir"] == "long" else float(r["band_hi"]))) / a, 3) if (a and not np.isnan(a) and r["extreme_value"] != "") else ""),
    })

# ---------- L1-B ----------
l1b = []
for r in seqs:
    n, first, maxdep = sweep_scan(r)
    if n == 0:
        continue
    l1b.append({
        "candidate": "L1-B", "seq_id": r["seq_id"], "window": r["window"], "dir": r["dir"],
        "b0_time_utc": r["b0_time_utc"], "band_lo": r["band_lo"], "band_hi": r["band_hi"],
        "band_width_atr": r["band_width_atr"], "band_touches": r["band_touches"],
        "trend_v02_at_b0": r["trend_v02_at_b0"], "seq_outcome": r["outcome"],
        "sweep_bars": n, "first_sweep_time_utc": ts(int(t15[first])) if first is not None else "",
        "max_sweep_depth_atr": round(maxdep, 3),
    })

# ---------- L1-C ----------
ordered = sorted(seqs, key=lambda r: int(r["b0_idx"]))
idx_of = {r["seq_id"]: i for i, r in enumerate(ordered)}
l1c = []
for r in ordered:
    if r["outcome"] != "voided":
        continue
    v = void_index(r)
    for nxt in ordered[idx_of[r["seq_id"]] + 1:]:
        if nxt["dir"] != r["dir"]:
            continue
        gap = int(nxt["b0_idx"]) - v
        if gap > 96:
            break
        l1c.append({
            "candidate": "L1-C", "seq_id": r["seq_id"], "window": r["window"], "dir": r["dir"],
            "b0_time_utc": r["b0_time_utc"], "band_lo": r["band_lo"], "band_hi": r["band_hi"],
            "first_void_time_utc": ts(int(t15[v]) + 900000),
            "second_seq_id": nxt["seq_id"], "second_b0_time_utc": nxt["b0_time_utc"],
            "gap_bars": gap, "gap_band": "le48" if gap <= 48 else "49_96",
            "second_outcome": nxt["outcome"],
            "second_failed": 1 if nxt["outcome"] in ("voided", "expired") else 0,
        })
        break

# ---------- 写出 ----------
all_rows = l1a + l1b + l1c
fields = sorted({k for row in all_rows for k in row})
with open(f"{OUT}/l1_events.csv", "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=fields)
    w.writeheader()
    w.writerows(all_rows)

# ---------- 描述性统计 ----------
import collections


def rate(rows, key):
    n = len(rows)
    return round(sum(1 for r in rows if r[key] == 1) / n, 4) if n else None


stats = {
    "l1a_n": len(l1a),
    "l1a_dir": dict(collections.Counter(r["dir"] for r in l1a)),
    "l1a_window": dict(collections.Counter(r["window"] for r in l1a)),
    "l1a_trend_v02": dict(collections.Counter(r["trend_v02_at_b0"] for r in l1a)),
    "l1a_touched": dict(collections.Counter(r["touched_before_void"] for r in l1a)),
    "l1a_void_lag_median": float(np.median([r["void_lag_bars"] for r in l1a])),
    "l1a_void_lag_max": max(r["void_lag_bars"] for r in l1a),
    "l1a_post48": {k: rate(l1a, k) for k in
                   ("post48_re_reclaim", "post48_resume", "post48_fade_ext")},
    "l1a_post48_first_order": dict(collections.Counter(r["post48_first_order"] for r in l1a)),
    "l1a_post96": {k: rate(l1a, k) for k in
                   ("post96_re_reclaim", "post96_resume", "post96_fade_ext")},
    "l1a_post96_first_order": dict(collections.Counter(r["post96_first_order"] for r in l1a)),
    "l1a_entry_found_48": rate(l1a, "entry_found_48"),
    "l1a_entry_class_15m": dict(collections.Counter(r["entry_class_15m"] for r in l1a)),
    "l1a_entry_class_5m": dict(collections.Counter(r["entry_class_5m"] for r in l1a)),
    "l1a_entry_open_gap_stop": sum(r["entry_open_gap_stop"] for r in l1a),
    "l1b_n_seq": len(l1b),
    "l1b_by_outcome": dict(collections.Counter(r["seq_outcome"] for r in l1b)),
    "l1b_by_dir": dict(collections.Counter(r["dir"] for r in l1b)),
    "l1b_total_sweep_bars": sum(r["sweep_bars"] for r in l1b),
    "l1c_n_pairs": len(l1c),
    "l1c_by_band": dict(collections.Counter(r["gap_band"] for r in l1c)),
    "l1c_second_failed_rate": rate(l1c, "second_failed"),
    "l1c_second_failed_rate_le48": rate([r for r in l1c if r["gap_band"] == "le48"], "second_failed"),
    "base_first_attempt_fail_rate": round((140 + 25) / 497, 4),
}
# 聚集性：作废序列按 b0 排序的同向连发（不设间隔上限；另计 b0 间隔 ≤96 根的连发）
voided_sorted = sorted([r for r in seqs if r["outcome"] == "voided"], key=lambda r: int(r["b0_idx"]))
runs, cur, cur_dir = [], 0, None
for r in voided_sorted:
    if r["dir"] == cur_dir:
        cur += 1
    else:
        if cur:
            runs.append(cur)
        cur, cur_dir = 1, r["dir"]
if cur:
    runs.append(cur)
stats["l1a_runs_max"] = max(runs)
stats["l1a_runs_ge2"] = sum(1 for x in runs if x >= 2)
stats["l1a_runs_ge3"] = sum(1 for x in runs if x >= 3)
runs96, cur, cur_dir, prev_b0 = [], 0, None, None
for r in voided_sorted:
    b = int(r["b0_idx"])
    if r["dir"] == cur_dir and prev_b0 is not None and b - prev_b0 <= 96:
        cur += 1
    else:
        if cur:
            runs96.append(cur)
        cur, cur_dir = 1, r["dir"]
    prev_b0 = b
if cur:
    runs96.append(cur)
stats["l1a_runs96_max"] = max(runs96)
stats["l1a_runs96_ge2"] = sum(1 for x in runs96 if x >= 2)
stats["l1a_runs96_ge3"] = sum(1 for x in runs96 if x >= 3)
#  trailing 96 根内同向作废计数分布
trail = []
for i, r in enumerate(voided_sorted):
    b = int(r["b0_idx"])
    c = sum(1 for q in voided_sorted[:i]
            if q["dir"] == r["dir"] and b - int(q["b0_idx"]) <= 96)
    trail.append(c)
stats["l1a_trailing96_same_dir"] = dict(collections.Counter(trail))
# 方向 × 作废后结构（48）
for d in ("long", "short"):
    sub = [r for r in l1a if r["dir"] == d]
    stats[f"l1a_post48_dir_{d}"] = {k: rate(sub, k) for k in
                                    ("post48_re_reclaim", "post48_resume", "post48_fade_ext")}
with open(f"{OUT}/l1_stats.json", "w", encoding="utf-8") as fh:
    json.dump(stats, fh, indent=1, ensure_ascii=False)
print(json.dumps(stats, indent=1, ensure_ascii=False))
