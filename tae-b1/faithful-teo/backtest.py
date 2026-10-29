"""Faithful-Teo exploratory backtest. Implements design.md v0.1 EXACTLY
(including the pre-run design fix: area side labels -- longs only touch
support/neutral zones, shorts only resistance/neutral zones; TP only from
opposing-side + neutral zones).
Bar-close execution only; confirmed swings only (index+2 <= bar); no lookahead.
Entry = trigger-bar close (market, taker). Exits from the bar after entry.
Same-bar exit priority: stop > TP > trailing.
Costs: taker 0.05% each leg; slippage tiers 0/0.05%/0.1% adverse on entry+exit;
funding from actual fundingRate history (real timestamps).
R = net P&L / initial risk; risk budget is scale-free (2% of account).
"""
import bisect
import json
import os

import numpy as np

BASE = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/faithful-teo"
DATA = os.path.join(BASE, "data")
ACCOUNT = 56.16
RISK_PCT = 0.02
RISK_USD = ACCOUNT * RISK_PCT  # 1.12
MAX_LEV = 20.0
MIN_NOTIONAL_ETH = 20.0
TAKER = 0.0005
SLIPS = [0.0, 0.0005, 0.001]
SEED = 20261029
N_BOOT = 2000


def load_data():
    kl = json.load(open(os.path.join(DATA, "klines_1h.json"), encoding="utf-8"))
    o = np.array([float(r[1]) for r in kl])
    h = np.array([float(r[2]) for r in kl])
    l = np.array([float(r[3]) for r in kl])
    c = np.array([float(r[4]) for r in kl])
    ct = np.array([int(r[6]) for r in kl])  # bar close time ms
    fd = json.load(open(os.path.join(DATA, "funding_rate.json"), encoding="utf-8"))
    ft = np.array([int(r["fundingTime"]) for r in fd])
    fr = np.array([float(r["fundingRate"]) for r in fd])
    return o, h, l, c, ct, ft, fr


def atr14(h, l, c):
    pc = np.roll(c, 1)
    pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = np.full(len(c), np.nan)
    cs = np.concatenate([[0.0], np.cumsum(tr)])
    for i in range(13, len(c)):
        atr[i] = (cs[i + 1] - cs[i - 13]) / 14.0
    return atr


def sma(c, n):
    out = np.full(len(c), np.nan)
    cs = np.concatenate([[0.0], np.cumsum(c)])
    for i in range(n - 1, len(c)):
        out[i] = (cs[i + 1] - cs[i - n + 1]) / n
    return out


def is_swing_low(l, i):
    return (l[i] < l[i - 1] and l[i] < l[i - 2]
            and l[i] < l[i + 1] and l[i] < l[i + 2])


def is_swing_high(h, i):
    return (h[i] > h[i - 1] and h[i] > h[i - 2]
            and h[i] > h[i + 1] and h[i] > h[i + 2])


def body(o_, c_):
    return abs(c_ - o_)


def patterns_at(o, h, l, c, atr, t):
    """Return (bullish_patterns, bearish_patterns) completing at bar t."""
    bull, bear = [], []
    b = body(o[t], c[t])
    rng = h[t] - l[t]
    up_w = h[t] - max(o[t], c[t])
    lo_w = min(o[t], c[t]) - l[t]
    if c[t] > o[t] and b > 0 and lo_w >= 2 * b and up_w <= b:
        bull.append("hammer")
    if c[t] < o[t] and b > 0 and up_w >= 2 * b and lo_w <= b:
        bear.append("shooting_star")
    if rng > 0 and b <= 0.1 * rng and up_w <= 0.1 * rng and lo_w >= 0.5 * rng:
        bull.append("dragonfly_doji")
    if rng > 0 and b <= 0.1 * rng and lo_w <= 0.1 * rng and up_w >= 0.5 * rng:
        bear.append("gravestone_doji")
    if t >= 1:
        if c[t - 1] < o[t - 1] and c[t] > o[t] and o[t] < c[t - 1] and c[t] > o[t - 1]:
            bull.append("bullish_engulfing")
        if c[t - 1] > o[t - 1] and c[t] < o[t] and o[t] > c[t - 1] and c[t] < o[t - 1]:
            bear.append("bearish_engulfing")
        if abs(l[t] - l[t - 1]) <= 0.2 * atr[t] and c[t] > o[t]:
            bull.append("tweezer_bottom")
        if abs(h[t] - h[t - 1]) <= 0.2 * atr[t] and c[t] < o[t]:
            bear.append("tweezer_top")
    if t >= 2:
        if (c[t - 2] < o[t - 2] and body(o[t - 1], c[t - 1]) <= 0.5 * body(o[t - 2], c[t - 2])
                and c[t] > o[t] and c[t] > (o[t - 2] + c[t - 2]) / 2.0):
            bull.append("morning_star")
        if (c[t - 2] > o[t - 2] and body(o[t - 1], c[t - 1]) <= 0.5 * body(o[t - 2], c[t - 2])
                and c[t] < o[t] and c[t] < (o[t - 2] + c[t - 2]) / 2.0):
            bear.append("evening_star")
    return bull, bear


def pattern_span(pats):
    n = 1
    for p in pats:
        if p in ("tweezer_bottom", "tweezer_top",
                 "bullish_engulfing", "bearish_engulfing"):
            n = max(n, 2)
        if p in ("morning_star", "evening_star"):
            n = max(n, 3)
    return n


def main():
    o, h, l, c, ct, ft, fr = load_data()
    n = len(c)
    atr = atr14(h, l, c)
    ma20 = sma(c, 20)
    ma50 = sma(c, 50)
    ma200 = sma(c, 200)
    sw_lo = [i for i in range(2, n - 2) if is_swing_low(l, i)]
    sw_hi = [i for i in range(2, n - 2) if is_swing_high(h, i)]

    trades = []
    events = {"pattern_bars": 0, "trend_filtered": 0, "area_filtered": 0,
              "overlap_skipped": 0, "lev_skipped": 0, "min_notional_skipped": 0,
              "executed": 0, "open_at_end": 0}
    pattern_counts = {}

    broken_lo = {}   # swing idx -> price (broken support -> resistance)
    broken_hi = {}   # swing idx -> price (broken resistance -> support)
    rise_line = None  # (s1, s2, slope, intercept, broken)
    fall_line = None

    pos = None
    for t in range(200, n):
        hw = 0.25 * atr[t]
        lo_c = sw_lo[bisect.bisect_left(sw_lo, t - 200):
                     bisect.bisect_right(sw_lo, t - 2)]
        hi_c = sw_hi[bisect.bisect_left(sw_hi, t - 200):
                     bisect.bisect_right(sw_hi, t - 2)]
        # Flipped state per design F2(d), verbatim: a broken low stays flipped
        # resistance until a close > low + half-width (full reclaim past the
        # band top); a broken high stays flipped support until a close < high
        # - half-width. Closes inside the band do NOT restore the original band.
        for s in lo_c:
            if s not in broken_lo and c[t] < l[s] - hw:
                broken_lo[s] = l[s]
            elif s in broken_lo and c[t] > l[s] + hw:
                del broken_lo[s]
        for s in hi_c:
            if s not in broken_hi and c[t] > h[s] + hw:
                broken_hi[s] = h[s]
            elif s in broken_hi and c[t] < h[s] - hw:
                del broken_hi[s]
        for d in (broken_lo, broken_hi):
            for s in [s for s in d if s < t - 200]:
                del d[s]
        # trendlines from last two confirmed swings within 200 bars
        new_rise = None
        if len(lo_c) >= 2 and l[lo_c[-1]] > l[lo_c[-2]]:
            s1, s2 = lo_c[-2], lo_c[-1]
            slope = (l[s2] - l[s1]) / (s2 - s1)
            brk = False if rise_line is None or rise_line[:2] != (s1, s2) \
                else rise_line[4]
            if not brk and c[t] < slope * t + (l[s1] - slope * s1) - hw:
                brk = True
            new_rise = (s1, s2, slope, l[s1] - slope * s1, brk)
        rise_line = new_rise
        new_fall = None
        if len(hi_c) >= 2 and h[hi_c[-1]] < h[hi_c[-2]]:
            s1, s2 = hi_c[-2], hi_c[-1]
            slope = (h[s2] - h[s1]) / (s2 - s1)
            brk = False if fall_line is None or fall_line[:2] != (s1, s2) \
                else fall_line[4]
            if not brk and c[t] > slope * t + (h[s1] - slope * s1) + hw:
                brk = True
            new_fall = (s1, s2, slope, h[s1] - slope * s1, brk)
        fall_line = new_fall

        # zones at t: (center, type, side)
        zones = []
        for s in lo_c:
            if s not in broken_lo:
                zones.append((l[s], "swing", "support"))
        for s in hi_c:
            if s not in broken_hi:
                zones.append((h[s], "swing", "resistance"))
        zones.append((ma50[t], "ma50", "neutral"))
        if rise_line is not None and not rise_line[4]:
            zones.append((rise_line[2] * t + rise_line[3], "trendline", "support"))
        if fall_line is not None and not fall_line[4]:
            zones.append((fall_line[2] * t + fall_line[3], "trendline", "resistance"))
        for s, p in broken_lo.items():
            zones.append((p, "flipped", "resistance"))
        for s, p in broken_hi.items():
            zones.append((p, "flipped", "support"))

        had_pos = pos is not None
        # ---- exit evaluation (position opened before t) ----
        if had_pos and pos["entry_idx"] < t:
            side = pos["side"]
            ex = None
            if side == "long":
                if c[t] <= pos["stop"]:
                    ex = "stop"
                elif pos["tp"] is not None and c[t] >= pos["tp"]:
                    ex = "tp"
                elif c[t] < ma20[t] or c[t] < l[t - 1]:
                    ex = "trailing"
            else:
                if c[t] >= pos["stop"]:
                    ex = "stop"
                elif pos["tp"] is not None and c[t] <= pos["tp"]:
                    ex = "tp"
                elif c[t] > ma20[t] or c[t] > h[t - 1]:
                    ex = "trailing"
            if ex is not None:
                pos["exit_idx"] = t
                pos["exit"] = float(c[t])
                pos["exit_reason"] = ex
                trades.append(pos)
                pos = None
        # ---- pattern detection (every bar, for accounting) ----
        bull, bear = patterns_at(o, h, l, c, atr, t)
        if not bull and not bear:
            continue
        for p in bull + bear:
            pattern_counts[p] = pattern_counts.get(p, 0) + 1
        events["pattern_bars"] += 1
        if had_pos:
            # signal bars while a position was open at bar start are ignored
            events["overlap_skipped"] += 1
            continue
        # ---- signal evaluation ----
        if bull:
            side, pats = "long", bull
            if not (c[t] > ma200[t]):
                events["trend_filtered"] += 1
                continue
        else:
            side, pats = "short", bear
            if not (c[t] < ma200[t]):
                events["trend_filtered"] += 1
                continue
        span = pattern_span(pats)
        if side == "long":
            ext = float(np.min(l[t - span + 1:t + 1]))
        else:
            ext = float(np.max(h[t - span + 1:t + 1]))
        # F3 at-area test, only side-matching zones
        touched_types = set()
        touched = False
        for center, typ, sde in zones:
            if side == "long" and sde == "resistance":
                continue
            if side == "short" and sde == "support":
                continue
            zb, zt = center - hw, center + hw
            if side == "long":
                hit = (zb <= ext <= zt) or (ext < zb and c[t] >= zb)
                ok = hit and c[t] >= zb
            else:
                hit = (zb <= ext <= zt) or (ext > zt and c[t] <= zt)
                ok = hit and c[t] <= zt
            if ok:
                touched = True
                touched_types.add(typ)
        if not touched:
            events["area_filtered"] += 1
            continue
        entry = float(c[t])
        if side == "long":
            stop = ext - 0.5 * atr[t]
        else:
            stop = ext + 0.5 * atr[t]
        stop_pct = abs(entry - stop) / entry
        notional = RISK_USD / stop_pct
        if notional / ACCOUNT > MAX_LEV:
            events["lev_skipped"] += 1
            continue
        if notional < MIN_NOTIONAL_ETH:
            events["min_notional_skipped"] += 1
            continue
        # TP from opposing-side + neutral zones at entry (fixed)
        tp = None
        if side == "long":
            cands = [cen - hw for (cen, typ, sde) in zones
                     if sde in ("resistance", "neutral") and cen - hw > entry]
            if cands:
                tp = float(min(cands))
        else:
            cands = [cen + hw for (cen, typ, sde) in zones
                     if sde in ("support", "neutral") and cen + hw < entry]
            if cands:
                tp = float(max(cands))
        pos = {"entry_idx": t, "entry": entry, "stop": float(stop), "tp": tp,
               "side": side, "patterns": pats, "area_types": sorted(touched_types),
               "confluence": len(touched_types) >= 2, "stop_pct": float(stop_pct),
               "notional": float(notional)}
        events["executed"] += 1
    open_pos = None
    if pos is not None:
        events["open_at_end"] += 1
        open_pos = pos

    # ---- per-trade R per variant ----
    for tr in trades:
        e_idx, x_idx = tr["entry_idx"], tr["exit_idx"]
        te, tx = ct[e_idx], ct[x_idx]
        m = (ft > te) & (ft <= tx)
        rates_sum = float(np.sum(fr[m]))
        tr["funding_payments"] = int(np.sum(m))
        tr["funding_sum_rates"] = rates_sum
        tr["holding_bars"] = x_idx - e_idx
        tr["exit_time_ms"] = int(tx)
        tr["entry_time_ms"] = int(te)
        sgn = 1 if tr["side"] == "long" else -1
        sp = tr["stop_pct"]
        for slip in SLIPS:
            if tr["side"] == "long":
                ea = tr["entry"] * (1 + slip)
                xa = tr["exit"] * (1 - slip)
            else:
                ea = tr["entry"] * (1 - slip)
                xa = tr["exit"] * (1 + slip)
            gross = sgn * (xa - ea) / ea / sp
            fee = TAKER * (1 + xa / ea) / sp
            for fon in (True, False):
                fund = (-sgn * rates_sum / sp) if fon else 0.0
                tr[f"net_R_slip{slip}_fund{int(fon)}"] = gross - fee + fund

    window_days = (ct[-1] - ct[200]) / 86400000.0
    variants = {}
    rng = np.random.default_rng(SEED)
    for slip in SLIPS:
        for fon in (True, False):
            key = f"slip_{slip}_fund_{int(fon)}"
            rs = np.array([tr[f"net_R_slip{slip}_fund{int(fon)}"] for tr in trades])
            ntr = len(rs)
            if ntr:
                cum = np.cumsum(rs)
                dd = float(np.max(np.maximum.accumulate(cum) - cum)) if ntr > 1 else 0.0
                boots = [float(np.mean(rng.choice(rs, size=ntr, replace=True)))
                         for _ in range(N_BOOT)]
                lo, hi_ = np.percentile(boots, [2.5, 97.5])
                pos_sum = float(np.sum(rs[rs > 0]))
                neg_sum = float(np.sum(rs[rs < 0]))
                pf = pos_sum / abs(neg_sum) if neg_sum != 0 else float("inf")
                mx = int(np.argmax(rs))
                ex_rs = np.delete(rs, mx)
                variants[key] = {
                    "n": ntr, "per_day": ntr / window_days,
                    "mean_net_R": float(np.mean(rs)), "total_net_R": float(np.sum(rs)),
                    "profit_factor": pf, "max_drawdown_R": dd,
                    "bootstrap_ci_95": [float(lo), float(hi_)],
                    "max_single_R": float(rs[mx]),
                    "ex_max_mean_net_R": float(np.mean(ex_rs)),
                    "ex_max_total_net_R": float(np.sum(ex_rs)),
                    "median_net_R": float(np.median(rs)),
                    "win_count": int(np.sum(rs > 0)), "loss_count": int(np.sum(rs < 0)),
                }
            else:
                variants[key] = {"n": 0}
    central = [tr["net_R_slip0.0005_fund1"] for tr in trades]
    by_reason, by_side, by_conf = {}, {}, {}
    for tr, r in zip(trades, central):
        by_reason.setdefault(tr["exit_reason"], []).append(r)
        by_side.setdefault(tr["side"], []).append(r)
        by_conf.setdefault(str(tr["confluence"]), []).append(r)
    by_area = {}
    for tr, r in zip(trades, central):
        for at in tr["area_types"]:
            by_area.setdefault(at, []).append(r)
    out = {
        "window": {"first_ms": int(ct[200]), "last_ms": int(ct[-1]),
                   "bars": int(n), "days": float(window_days)},
        "events": events, "pattern_counts": pattern_counts,
        "open_position": open_pos,
        "trades_meta": {
            "exit_reasons": {k: {"n": len(v), "avg_net_R": float(np.mean(v))}
                             for k, v in sorted(by_reason.items())},
            "sides": {k: {"n": len(v), "avg_net_R": float(np.mean(v))}
                      for k, v in sorted(by_side.items())},
            "confluence_split": {k: {"n": len(v), "avg_net_R": float(np.mean(v))}
                                 for k, v in sorted(by_conf.items())},
            "area_type_split": {k: {"n": len(v), "avg_net_R": float(np.mean(v))}
                                for k, v in sorted(by_area.items())},
            "holding_bars": {
                "median": float(np.median([t["holding_bars"] for t in trades])) if trades else 0,
                "mean": float(np.mean([t["holding_bars"] for t in trades])) if trades else 0,
                "max": max([t["holding_bars"] for t in trades]) if trades else 0},
        },
        "variants": variants,
        "trades": trades,
    }
    with open(os.path.join(BASE, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(json.dumps({k: out[k] for k in ("window", "events", "pattern_counts",
                                          "trades_meta")}, ensure_ascii=False, indent=1))
    for k, v in variants.items():
        if v["n"]:
            print(k, "mean", round(v["mean_net_R"], 4), "total",
                  round(v["total_net_R"], 2), "PF", round(v["profit_factor"], 3),
                  "CI", [round(x, 4) for x in v["bootstrap_ci_95"]])


if __name__ == "__main__":
    main()
