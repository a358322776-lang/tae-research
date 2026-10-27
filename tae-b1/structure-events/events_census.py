"""TAE 无收益结构特征研究 · 任务一：全量事件普查。

只读复用 B1 口径，不改生产代码、不算盈亏、不找阈值。
口径（与 rules-v0.1-frozen.md + b1_engine.py 一致，差异处注明）：
- 突破候选：data_cache/candidates.jsonl（levels_pass 已算：trailing 400 根
  find_levels + 1H 趋势门 + 单根收盘穿越 P1），只读复用。
- 序列状态机：逐字复制 b1_engine.run_group Phase A（更新已有序列 →
  新突破 P3 每方向每根取最贴近现价的带 → 重叠跳过），并记录全部
  被跳过的候选（P3 同根落选 / 与活跃序列重叠），保证 514 候选全入账。
- 序列结局：reclaimed（收盘收复）/ voided（远沿收盘穿越）/ expired
  （b0 后 48 根未收复）/ unresolved（数据结束时仍活跃）。
- E 阶段（仅作参考字段，不决定序列存在）：复制 resolve_sequence 的
  B 组逻辑（fix_doji=False），记录 e_signal/missed/timeout/
  coincident_void/filled/lev_skip/invalid；filled 只是 Phase A 入场，
  不是 Phase B 接受（不做仓位/冷却过滤，与交易无关）。
- 带元数据：b0 时刻 trailing 400 根窗口重算 find_levels（真实函数，
  只读调用），匹配候选带后取 touches/last_touch_idx；簇跨度用与
  key_levels 逐字相同的 valid-touch 逻辑另行输出 first_touch_idx，
  并对每根 b0 断言两者 (kind, band, touches, last_touch_idx) 一致，
  不一致则 span 置空并记入 meta。
- I2-A 特征（v0.2 词汇）：窗口 [t0, terminal]，terminal = 收复根
  （已收复）或作废/过期根（未收复，窗口截断，字段 window_type 标明）；
  锚点极值 L*（多头窗口最低 low）/ H*（空头最高 high），锚点根 t* 为
  首次达到者；depth = (bhi-L*)/ATR 或 (H*-blo)/ATR，ATR 取 terminal
  根收盘时的 15m ATR(14)；rebound_final = terminal 收盘相对锚点极值
  的 ATR 倍数；rebound_max = 窗口内 j>=t* 的最大 rebound；
  pos_final = terminal 根收盘在振幅中的分位。未触碰序列以上皆空。
  不做擦边分类（D_graze 待拍板，无数值）。
- I2-B 停留：dwell_max_consec = 从 t0 起连续满足"极值与带相交且
  收盘不穿越远沿"的最长根数；dwell_total = 窗口内触碰根数。
- 1H 趋势：b0 门沿用 levels_pass 指针法（收盘 ≤ T，B1 复现用）；
  v0.2 重检用严格早于规则（收盘 < T，摆动点 i+k ≤ 最后可用索引，
  k=2，≥60 根，台阶 ≥0.5×ATR(1H)）。两者分开记录，不得混用。
- I4-A：Θ(T) = max{种子（b0 时最新已确认摆动低）+ 自 b0 起全部
  已确认摆动低}（多头；空头取 min）；确认条件 i+k ≤ 最后可用索引；
  评价在 1H 收盘上做（评价根本身可用）；失效 = 首根 1H 收盘 ≤ Θ
  （多头），吸收态；盘中触及不算。种子解释见 features_observation.md。
- 后续结构结局（只用价格结构，零盈亏）：收复后 N=48/96 根 15m 内，
  fell_back = 任一收盘价回到带内 [blo, bhi]；fell_through = 任一
  收盘穿越远沿；new_swing = 经 k=2 确认的新摆动（15m strict swings）
  且极值超越 b0 根极值（多头摆动高 > high[b0]）；i4a_post =
  I4-A 在收复后窗口内首次失效；trend_gate_end = 窗口末收盘时刻的
  v0.2 趋势门结果。窗口末超出数据者记 truncated，不进分母。
- 窗口：b0 open ≤ 2025-10-17T02:00Z 为 oos，其余为 ins（P9）。
"""
import bisect
import csv
import json
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/hidden_files")
from b1_lib import atr_series, is_signal_bar, swings_strict, swings_tie  # noqa
from key_levels import find_levels  # noqa: E402  只读调用

B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1"
OUT = f"{B1}/structure-events"
BOUNDARY_MS = 1760666400000  # 2025-10-17T02:00Z
STEP15 = 900_000


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M")


# ---------- 与 key_levels 逐字相同的 valid-touch 逻辑，仅多输出首触索引 ----------
def _held_res(candles, idx, price, band_top, a):
    after = candles[idx + 1: idx + 9]
    if not after:
        return False
    if any(c["c"] > band_top for c in candles[idx + 1: idx + 5]):
        return False
    return price - min(c["l"] for c in after) >= 1.0 * a


def _held_sup(candles, idx, price, band_bottom, a):
    after = candles[idx + 1: idx + 9]
    if not after:
        return False
    if any(c["c"] < band_bottom for c in candles[idx + 1: idx + 5]):
        return False
    return max(c["h"] for c in after) - price >= 1.0 * a


def _clusters(points, tol):
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


def _swings(candles, k=2):
    hi, lo = [], []
    for i in range(k, len(candles) - k):
        h = candles[i]["h"]
        l = candles[i]["l"]
        if all(h > candles[j]["h"] for j in range(i - k, i + k + 1) if j != i):
            hi.append((i, h))
        if all(l < candles[j]["l"] for j in range(i - k, i + k + 1) if j != i):
            lo.append((i, l))
    return hi, lo


def find_levels_meta(candles, a):
    """返回 list[dict]，字段同 find_levels，另加 first_touch_idx 与 touch_idx。"""
    hi, lo = _swings(candles)
    out = []
    for cl in _clusters(hi, 0.35 * a):
        band = (min(v for _, v in cl), max(v for _, v in cl))
        valid = [(i, v) for i, v in cl if _held_res(candles, i, v, band[1], a)]
        if len(valid) < 3:
            continue
        valid = valid[-9:]
        vals = [v for _, v in valid]
        last_i = max(i for i, _ in valid)
        if len(candles) - 1 - last_i > 96:
            continue
        out.append({"kind": "resistance", "line": min(vals),
                    "band": (min(vals), max(vals)), "touches": len(valid),
                    "last_touch_idx": last_i, "first_touch_idx": min(i for i, _ in valid),
                    "touch_idx": [i for i, _ in valid]})
    remaining = list(lo)
    while remaining:
        best_line, best_touch = None, []
        for _, cand in remaining:
            touch = [p for p in remaining if abs(p[1] - cand) <= 0.2 * a]
            if len(touch) > len(best_touch):
                best_line, best_touch = cand, touch
        if len(best_touch) < 3:
            break
        members = [p for p in remaining if abs(p[1] - best_line) <= 0.6 * a]
        members.sort(key=lambda x: abs(x[1] - best_line))
        members = members[:12]
        band = (min(v for _, v in members), max(v for _, v in members))
        valid = [(i, v) for i, v in members if _held_sup(candles, i, v, band[0], a)]
        used = set(id(p) for p in members)
        remaining = [p for p in remaining if id(p) not in used]
        if len(valid) < 3:
            continue
        valid = valid[-9:]
        vals = [v for _, v in valid]
        last_i = max(i for i, _ in valid)
        if len(candles) - 1 - last_i > 96:
            continue
        out.append({"kind": "support", "line": best_line,
                    "band": (min(vals), max(vals)), "touches": len(valid),
                    "last_touch_idx": last_i, "first_touch_idx": min(i for i, _ in valid),
                    "touch_idx": [i for i, _ in valid]})
    # 去重（同 find_levels）：支撑/阻力大面积重叠只留触碰多的那个
    out.sort(key=lambda x: -x["touches"])
    kept = []
    for L in out:
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


def main():
    d15 = np.load(f"{B1}/data_cache/stitched_15m.npz")
    d5 = np.load(f"{B1}/data_cache/stitched_5m.npz")
    d1h = np.load(f"{B1}/data_cache/stitched_1h.npz")
    t15, o15 = d15["t"], d15["ohlc"]
    t5, o5 = d5["t"], d5["ohlc"]
    t1h, o1h = d1h["t"], d1h["ohlc"]
    c15, h15, l15 = o15[:, 3], o15[:, 1], o15[:, 2]
    atr15 = atr_series(o15)
    n15 = len(t15)
    # 1H ATR(14) 与 tie 摆动点（全序列一次算出）
    tr1 = np.full(len(o1h), np.nan)
    for i in range(1, len(o1h)):
        tr1[i] = max(o1h[i][1] - o1h[i][2], abs(o1h[i][1] - o1h[i - 1][3]),
                     abs(o1h[i][2] - o1h[i - 1][3]))
    atr1 = np.full(len(o1h), np.nan)
    for i in range(13, len(o1h)):
        atr1[i] = float(np.nanmean(tr1[i - 13:i + 1]))
    hi_all, lo_all = swings_tie(o1h)
    hi_idx = np.array([i for i, _ in hi_all])
    hi_val = np.array([v for _, v in hi_all])
    lo_idx = np.array([i for i, _ in lo_all])
    lo_val = np.array([v for _, v in lo_all])
    t1h_close = t1h + 3_600_000
    t15_close = t15 + STEP15
    # 15m strict 摆动点（后续新摆动判定用）
    shi, slo = swings_strict(o15)
    shi_idx = set(i for i, _ in shi)
    shi_val = dict(shi)
    slo_idx = set(i for i, _ in slo)
    slo_val = dict(slo)

    def trend_gate_v02(T):
        """v0.2 严格早于规则：可用 1H = 收盘 < T；摆动点 i+2 ≤ 最后可用索引。
        返回 (结果, high_steps_atr, low_steps_atr, atr1h)，结果 ∈
        {long, short, None, na}。"""
        cnt = int(np.searchsorted(t1h_close, T, side="left"))
        if cnt < 60:
            return "na", None, None, None
        last = cnt - 1
        if np.isnan(atr1[last]):
            return "na", None, None, None
        a = float(atr1[last])
        hi = [v for idx, v in zip(hi_idx, hi_val) if idx <= last - 2][-3:]
        lo = [v for idx, v in zip(lo_idx, lo_val) if idx <= last - 2][-3:]
        if len(hi) < 3 or len(lo) < 3:
            return "na", None, None, None
        hs = [(hi[i + 1] - hi[i]) / a for i in range(2)]
        ls = [(lo[i + 1] - lo[i]) / a for i in range(2)]
        if all(x >= 0.5 for x in hs) and all(x >= 0.5 for x in ls):
            return "long", hs, ls, a
        if all(x <= -0.5 for x in hs) and all(x <= -0.5 for x in ls):
            return "short", hs, ls, a
        return None, hs, ls, a

    def trend_gate_b1(T):
        """levels_pass 指针法（收盘 ≤ T，确认 idx ≤ p-3），B1 复现用。"""
        p = int(np.searchsorted(t1h_close, T, side="right"))
        if p < 60 or np.isnan(atr1[p - 1]):
            return "na", None, None, None
        a = float(atr1[p - 1])
        hi = [v for idx, v in zip(hi_idx, hi_val) if idx <= p - 3][-3:]
        lo = [v for idx, v in zip(lo_idx, lo_val) if idx <= p - 3][-3:]
        if len(hi) < 3 or len(lo) < 3:
            return "na", None, None, None
        hs = [(hi[i + 1] - hi[i]) / a for i in range(2)]
        ls = [(lo[i + 1] - lo[i]) / a for i in range(2)]
        if all(x >= 0.5 for x in hs) and all(x >= 0.5 for x in ls):
            return "long", hs, ls, a
        if all(x <= -0.5 for x in hs) and all(x <= -0.5 for x in ls):
            return "short", hs, ls, a
        return None, hs, ls, a

    
    def tg_label(g, d):
        """趋势门结果转统一标签：na / fail / pass_same / pass_opp。"""
        if g == "na":
            return "na"
        if g is None:
            return "fail"
        return "pass_same" if g == d else "pass_opp"


# ---- 候选 ----
    cand = {}
    with open(f"{B1}/data_cache/candidates.jsonl") as fh:
        for line in fh:
            try:
                c = json.loads(line)
            except Exception:
                continue
            cand.setdefault(c["j"], []).append((c["dir"], c["blo"], c["bhi"]))
    n_cand_events = sum(len(v) for v in cand.values())

    # ---- Phase A 复现（带日志）----
    active = []
    seqs = []          # 全部序列（含未决）
    skipped = []       # 未成序列的候选
    for j in range(399, n15):
        cj, hj, lj = float(c15[j]), float(h15[j]), float(l15[j])
        nxt = []
        for s in active:
            d = s["dir"]
            if d == "long":
                if cj < s["blo"]:
                    s["outcome"] = "voided"
                    s["terminal"] = j
                    seqs.append(s)
                    continue
                if not s["touched"]:
                    if lj <= s["bhi"] and hj >= s["blo"]:
                        s["touched"] = True
                        s["first_touch"] = j
                if s["touched"]:
                    if cj > s["bhi"]:
                        s["outcome"] = "reclaimed"
                        s["terminal"] = j
                        seqs.append(s)
                        continue
                if j >= s["b0"] + 48:
                    s["outcome"] = "expired"
                    s["terminal"] = j
                    seqs.append(s)
                    continue
            else:
                if cj > s["bhi"]:
                    s["outcome"] = "voided"
                    s["terminal"] = j
                    seqs.append(s)
                    continue
                if not s["touched"]:
                    if lj <= s["bhi"] and hj >= s["blo"]:
                        s["touched"] = True
                        s["first_touch"] = j
                if s["touched"]:
                    if cj < s["blo"]:
                        s["outcome"] = "reclaimed"
                        s["terminal"] = j
                        seqs.append(s)
                        continue
                if j >= s["b0"] + 48:
                    s["outcome"] = "expired"
                    s["terminal"] = j
                    seqs.append(s)
                    continue
            nxt.append(s)
        active = nxt
        for d in ("long", "short"):
            cands = [c for c in cand.get(j, []) if c[0] == d]
            if not cands:
                continue
            if d == "long":
                pick = max(cands, key=lambda c: c[2])
            else:
                pick = min(cands, key=lambda c: c[1])
            for c in cands:
                if c is not pick:
                    skipped.append({"j": j, "dir": d, "blo": c[1], "bhi": c[2],
                                    "reason": "p3_shadowed"})
            blo, bhi = pick[1], pick[2]
            overlap = any(s["dir"] == d and not (bhi < s["blo"] or blo > s["bhi"])
                          for s in active)
            if overlap:
                skipped.append({"j": j, "dir": d, "blo": blo, "bhi": bhi,
                                "reason": "overlap_active"})
                continue
            active.append({"dir": d, "blo": blo, "bhi": bhi, "b0": j,
                           "touched": False, "first_touch": None,
                           "outcome": None, "terminal": None})
    for s in active:
        s["outcome"] = "unresolved"
        s["terminal"] = n15 - 1
        seqs.append(s)
    seqs.sort(key=lambda s: (s["b0"], s["dir"]))

    # ---- 带元数据（b0 时刻重算，与候选带匹配）----
    meta_mismatch = 0
    band_meta = {}
    for s in seqs:
        j = s["b0"]
        if j in band_meta:
            continue
        win = [{"o": float(r[0]), "h": float(r[1]), "l": float(r[2]), "c": float(r[3])}
               for r in o15[j - 399:j + 1]]
        lv = find_levels(win, float(atr15[j]))
        lv_meta = find_levels_meta(win, float(atr15[j]))
        band_meta[j] = (lv, lv_meta)
    # ---- E 阶段（B 组参考）----
    def e_stage(s):
        r = s["terminal"]
        if s["outcome"] != "reclaimed":
            return "no_reclaim", None, None, None
        d = s["dir"]
        tr_close = int(t15[r]) + STEP15
        m0 = int(np.searchsorted(t5, tr_close, side="left"))
        sig = None
        status = None
        for k in range(3):
            m = m0 + k
            if m >= len(t5):
                break
            if is_signal_bar(o5, m, d, False):
                if k == 2 and r + 1 < n15:
                    c_next = float(c15[r + 1])
                    if (d == "long" and c_next < s["blo"]) or \
                       (d == "short" and c_next > s["bhi"]):
                        status = "coincident_void"
                        return status, None, None, None
                sig = m
                break
        if sig is None:
            return "e_timeout", None, None, None
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
            return "missed", sig, trig, None
        atr_r = float(atr15[r])
        if np.isnan(atr_r) or atr_r == 0:
            return "invalid", sig, trig, fill
        # 止损：引擎 resolve 时的 extreme = 触碰窗口全部极值（多头最低 low）
        if s["touched"]:
            t0 = s["first_touch"]
            extreme = float(np.min(l15[t0:r + 1])) if d == "long" \
                else float(np.max(h15[t0:r + 1]))
        else:
            return "invalid", sig, trig, fill
        stop = extreme - atr_r if d == "long" else extreme + atr_r
        risk = abs(trig - stop)
        if risk <= 0:
            return "invalid", sig, trig, fill
        lev = 0.02 / (risk / trig)
        if lev > 20:
            return "lev_skip", sig, trig, fill
        return "filled", sig, trig, fill

    # I4-A 扫描：返回首次失效的 1H 收盘时刻（ms）或 None
    def i4a_first_invalid(b0_close_ms, end_close_ms, direction):
        # 1H bar 下标区间：收盘在 (b0_close, end_close] 内
        k0 = int(np.searchsorted(t1h_close, b0_close_ms, side="right"))
        k1 = int(np.searchsorted(t1h_close, end_close_ms, side="right")) - 1
        if k1 < k0:
            return None
        # 种子：b0 时最新已确认摆动低/高（确认 = idx+2 ≤ 最后收盘 ≤ b0 的 bar）
        last_at_b0 = int(np.searchsorted(t1h_close, b0_close_ms, side="right")) - 1
        if direction == "long":
            conf = [v for idx, v in zip(lo_idx, lo_val) if idx <= last_at_b0 - 2]
            theta = max(conf) if conf else None
            for k in range(k0, k1 + 1):
                new = [v for idx, v in zip(lo_idx, lo_val)
                       if idx <= k - 2 and int(t1h[idx]) + 3_600_000 > b0_close_ms]
                if new:
                    cand_theta = max(new)
                    theta = cand_theta if theta is None else max(theta, cand_theta)
                if theta is not None and float(o1h[k][3]) <= theta:
                    return int(t1h_close[k])
            return None
        else:
            conf = [v for idx, v in zip(hi_idx, hi_val) if idx <= last_at_b0 - 2]
            theta = min(conf) if conf else None
            for k in range(k0, k1 + 1):
                new = [v for idx, v in zip(hi_idx, hi_val)
                       if idx <= k - 2 and int(t1h[idx]) + 3_600_000 > b0_close_ms]
                if new:
                    cand_theta = min(new)
                    theta = cand_theta if theta is None else min(theta, cand_theta)
                if theta is not None and float(o1h[k][3]) >= theta:
                    return int(t1h_close[k])
            return None

    rows = []
    for si, s in enumerate(seqs, 1):
        j, d = s["b0"], s["dir"]
        blo, bhi = float(s["blo"]), float(s["bhi"])
        term = s["terminal"]
        atr_b0 = float(atr15[j])
        # 带元数据匹配
        lv, lv_meta = band_meta[j]
        meta = None
        for L in lv:
            if abs(L["band"][0] - blo) < 1e-9 and abs(L["band"][1] - bhi) < 1e-9:
                meta = L
                break
        meta_m = None
        for L in lv_meta:
            if abs(L["band"][0] - blo) < 1e-9 and abs(L["band"][1] - bhi) < 1e-9:
                meta_m = L
                break
        if meta is None or meta_m is None or meta["touches"] != meta_m["touches"] \
                or meta["last_touch_idx"] != meta_m["last_touch_idx"]:
            meta_mismatch += 1
            touches = meta["touches"] if meta else ""
            lag = (399 - meta["last_touch_idx"]) if meta else ""
            span = ""
        else:
            touches = meta["touches"]
            lag = 399 - meta["last_touch_idx"]
            span = meta_m["last_touch_idx"] - meta_m["first_touch_idx"]
        row = {
            "seq_id": f"S{si:04d}",
            "window": "oos" if int(t15[j]) <= BOUNDARY_MS else "ins",
            "dir": d, "b0_idx": j, "b0_time_utc": iso(int(t15[j])),
            "band_lo": blo, "band_hi": bhi,
            "band_width_atr": (bhi - blo) / atr_b0 if atr_b0 else "",
            "band_touches": touches, "band_last_touch_lag": lag,
            "band_span_bars": span,
            "band_line": meta["line"] if meta else "",
            "outcome": s["outcome"],
            "outcome_time_utc": iso(int(t15[term]) + STEP15) if s["outcome"] != "unresolved" else "",
            "touched": int(bool(s["touched"])),
            "first_touch_time_utc": iso(int(t15[s["first_touch"]])) if s["first_touch"] is not None else "",
            "first_touch_lag_bars": (s["first_touch"] - j) if s["first_touch"] is not None else "",
            "reclaimed": int(s["outcome"] == "reclaimed"),
            "reclaim_time_utc": iso(int(t15[term]) + STEP15) if s["outcome"] == "reclaimed" else "",
            "reclaim_lag_bars": (term - j) if s["outcome"] == "reclaimed" else "",
        }
        # b0 趋势状态（B1 指针法 + v0.2 严格早于法）
        Tb0 = int(t15_close[j])
        g_b1, hs_b1, ls_b1, a_b1 = trend_gate_b1(Tb0)
        g_v02, hs_v02, ls_v02, a_v02 = trend_gate_v02(Tb0)
        row["trend_gate_b1"] = tg_label(g_b1, d)
        row["trend_v02_at_b0"] = tg_label(g_v02, d)
        row["trend_step_high_min_atr"] = min(hs_v02) if hs_v02 else ""
        row["trend_step_low_min_atr"] = min(ls_v02) if ls_v02 else ""
        row["atr1h_at_b0"] = a_v02 if a_v02 else ""
        # 触碰窗口量（[t0, terminal]，未触碰则空）
        if s["touched"]:
            t0 = s["first_touch"]
            seg_l = l15[t0:term + 1]
            seg_h = h15[t0:term + 1]
            seg_c = c15[t0:term + 1]
            touch_bars = [i for i in range(t0, term + 1)
                          if l15[i] <= bhi and h15[i] >= blo]
            # I2-B 式连续停留（极值相交且收盘不穿越远沿）
            max_consec = cur = 0
            for i in range(t0, term + 1):
                ok = (l15[i] <= bhi and h15[i] >= blo) and \
                     ((d == "long" and c15[i] >= blo) or (d == "short" and c15[i] <= bhi))
                cur = cur + 1 if ok else 0
                max_consec = max(max_consec, cur)
            atr_term = float(atr15[term])
            if d == "long":
                anchor = float(np.min(seg_l))
                anchor_rel = int(np.argmin(seg_l))
                depth = (bhi - anchor) / atr_term
                reb_final = (float(seg_c[-1]) - anchor) / atr_term
                reb_max = max((float(c) - anchor) / atr_term for c in seg_c[anchor_rel:])
            else:
                anchor = float(np.max(seg_h))
                anchor_rel = int(np.argmax(seg_h))
                depth = (anchor - blo) / atr_term
                reb_final = (anchor - float(seg_c[-1])) / atr_term
                reb_max = max((anchor - float(c)) / atr_term for c in seg_c[anchor_rel:])
            hb, lb, cb = float(h15[term]), float(l15[term]), float(c15[term])
            pos_final = (cb - lb) / (hb - lb) if hb > lb else ""
            row.update({
                "window_type": "reclaim" if s["outcome"] == "reclaimed" else "truncated",
                "touch_count_bars": len(touch_bars),
                "extreme_value": anchor,
                "anchor_time_utc": iso(int(t15[t0 + anchor_rel])),
                "i2a_depth_atr": depth,
                "i2a_rebound_final_atr": reb_final,
                "i2a_rebound_max_atr": reb_max,
                "i2a_pos_final": pos_final,
                "i2b_dwell_max_consec": max_consec,
            })
        else:
            row.update({"window_type": "", "touch_count_bars": 0, "extreme_value": "",
                        "anchor_time_utc": "", "i2a_depth_atr": "", "i2a_rebound_final_atr": "",
                        "i2a_rebound_max_atr": "", "i2a_pos_final": "", "i2b_dwell_max_consec": 0})
        # E 参考（B 组）
        e_out, e_idx, trig, fill = e_stage(s)
        row["e_outcome_b"] = e_out
        row["e_time_utc"] = iso(int(t5[e_idx]) + 300_000) if e_idx is not None else ""
        # I4-A 序列内 + I4-B 重检
        b0_close = int(t15_close[j])
        term_close = int(t15_close[term])
        inv = i4a_first_invalid(b0_close, term_close, d)
        row["i4a_invalidated_during"] = int(inv is not None)
        row["i4a_invalidation_time_utc"] = iso(inv) if inv else ""
        if s["touched"]:
            Tt0 = int(t15_close[s["first_touch"]])
            g_t0, _, _, _ = trend_gate_v02(Tt0)
            row["i4b_recheck_t0"] = tg_label(g_t0, d)
            if s["outcome"] == "reclaimed":
                Tr = int(t15_close[term])
                # t0 与收复根同一 1H bar 内则只做一次（以收复根为准）
                if int(t1h_close[np.searchsorted(t1h_close, Tt0, side="left")]) == \
                   int(t1h_close[np.searchsorted(t1h_close, Tr, side="left")]) \
                   if np.searchsorted(t1h_close, Tt0, side="left") < len(t1h_close) else False:
                    row["i4b_recheck_t0"] = "merged_into_reclaim"
                g_r, _, _, _ = trend_gate_v02(Tr)
                row["i4b_recheck_reclaim"] = tg_label(g_r, d)
            else:
                row["i4b_recheck_reclaim"] = "na_no_reclaim"
        else:
            row["i4b_recheck_t0"] = "na_no_touch"
            row["i4b_recheck_reclaim"] = "na_no_touch"
        # 后续结构结局（仅已收复）
        for N in (48, 96):
            p = f"post{N}"
            if s["outcome"] != "reclaimed" or term + N >= n15:
                row[f"{p}_truncated"] = 1
                for k in ("fell_back", "fell_through", "new_swing",
                          "i4a_invalidated", "trend_gate_end"):
                    row[f"{p}_{k}"] = ""
                continue
            row[f"{p}_truncated"] = 0
            seg_c = c15[term + 1:term + N + 1]
            if d == "long":
                row[f"{p}_fell_back"] = int(np.any((seg_c >= blo) & (seg_c <= bhi)))
                row[f"{p}_fell_through"] = int(np.any(seg_c < blo))
            else:
                row[f"{p}_fell_back"] = int(np.any((seg_c >= blo) & (seg_c <= bhi)))
                row[f"{p}_fell_through"] = int(np.any(seg_c > bhi))
            b0_ext = float(h15[j]) if d == "long" else float(l15[j])
            new_sw = 0
            for i in range(term + 1, term + N + 1):
                if d == "long" and i in shi_idx and i + 2 <= term + N \
                        and shi_val[i] > b0_ext:
                    new_sw = 1
                    break
                if d == "short" and i in slo_idx and i + 2 <= term + N \
                        and slo_val[i] < b0_ext:
                    new_sw = 1
                    break
            row[f"{p}_new_swing"] = new_sw
            inv_post = i4a_first_invalid(b0_close, int(t15_close[term + N]), d)
            row[f"{p}_i4a_invalidated"] = int(inv_post is not None and inv_post > term_close)
            g_end, _, _, _ = trend_gate_v02(int(t15_close[term + N]))
            row[f"{p}_trend_gate_end"] = tg_label(g_end, d)
        rows.append(row)
    # 未成序列候选行
    for si, sk in enumerate(sorted(skipped, key=lambda x: (x["j"], x["dir"])), 1):
        rows.append({
            "seq_id": f"X{si:04d}", "window": "oos" if int(t15[sk["j"]]) <= BOUNDARY_MS else "ins",
            "dir": sk["dir"], "b0_idx": sk["j"], "b0_time_utc": iso(int(t15[sk["j"]])),
            "band_lo": sk["blo"], "band_hi": sk["bhi"], "outcome": "not_sequenced",
            "outcome_time_utc": "", "touched": "", "outcome_reason": sk["reason"],
        })
    fields = ["seq_id", "window", "dir", "b0_idx", "b0_time_utc", "band_lo", "band_hi",
              "band_width_atr", "band_touches", "band_last_touch_lag", "band_span_bars",
              "band_line", "trend_gate_b1", "trend_v02_at_b0", "trend_step_high_min_atr",
              "trend_step_low_min_atr", "atr1h_at_b0", "outcome", "outcome_time_utc",
              "outcome_reason", "touched", "first_touch_time_utc", "first_touch_lag_bars",
              "reclaimed", "reclaim_time_utc", "reclaim_lag_bars", "window_type",
              "touch_count_bars", "extreme_value", "anchor_time_utc", "i2a_depth_atr",
              "i2a_rebound_final_atr", "i2a_rebound_max_atr", "i2a_pos_final",
              "i2b_dwell_max_consec", "e_outcome_b", "e_time_utc",
              "i4a_invalidated_during", "i4a_invalidation_time_utc",
              "i4b_recheck_t0", "i4b_recheck_reclaim",
              "post48_truncated", "post48_fell_back", "post48_fell_through",
              "post48_new_swing", "post48_i4a_invalidated", "post48_trend_gate_end",
              "post96_truncated", "post96_fell_back", "post96_fell_through",
              "post96_new_swing", "post96_i4a_invalidated", "post96_trend_gate_end"]
    with open(f"{OUT}/events_census.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    from collections import Counter
    oc = Counter(r["outcome"] for r in rows if r["seq_id"].startswith("S"))
    ec = Counter(r["e_outcome_b"] for r in rows if r["seq_id"].startswith("S"))
    meta = {
        "window_15m": {"first": iso(int(t15[0])), "last": iso(int(t15[-1]) + STEP15),
                       "n_bars": n15, "gaps": 0},
        "candidates": n_cand_events,
        "sequences": sum(1 for r in rows if r["seq_id"].startswith("S")),
        "skipped_candidates": len(skipped),
        "outcome_counts": dict(oc),
        "e_outcome_counts_b": dict(ec),
        "band_meta_mismatch": meta_mismatch,
        "reconciliation": {
            "candidates_eq_sequences_plus_skipped":
                n_cand_events == sum(1 for r in rows if r["seq_id"].startswith("S")) + len(skipped),
        },
    }
    with open(f"{OUT}/census_meta.json", "w") as fh:
        json.dump(meta, fh, indent=1, ensure_ascii=False, default=str)
    print(json.dumps(meta, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
