"""ETH v4.1 engine for the robustness study — faithful port of
hidden_files/backtest-v4-eth-unified.py (v4.1 unified entry) with numpy
helpers validated against the original modules (see validate_helpers()).

RULES ARE FROZEN. This file changes no parameter: it re-implements the
original signal logic on arrays for speed, with identical semantics:
  * trend: 1H strict version (last 3 swing highs AND last 3 swing lows move
    the same way, each step >= 0.5*ATR(1h)); tf.swings ties-count semantics.
  * levels: key_levels.find_levels on the last 400 15m bars, ATR(15m).
  * entry: trend direction, price back at a key band, >=2nd same-side test
    in the last 96 15m bars (departure >= 0.5*ATR between tests), touching
    now, plus a Teo signal K in the 3 5m bars of the signal 15m bar.
  * stop: band edge +/- 1*ATR(15m), never moves.
  * exit: initial stop (5m intrabar check, stop first) or 15m close crossing
    EMA50(15m) (SMA50 seed, k=2/51), whichever first; entry bar not judged.
  * cooldown: same direction 8 bars (2h) after a close.
  * implied leverage > 20x (0.02 / stop-distance-fraction) -> signal skipped.
  * single position; an exit bar may open an opposite-direction position.

EXEC MODE (post-processing, audit semantics):
  * limit order at the signal-bar close, valid only the next 15m bar.
  * fills T0 (touch) / T1 (penetration 0.05%) / T2 (penetration 0.1%).
  * executor exit correction: an exit inside the fill bar is kept only if
    (stop and its 5m bar is strictly later than the fill 5m bar) — otherwise
    recomputed from the next 5m bar (stop case) / next 15m bar (EMA case,
    entry bar skipped). Exits after the fill bar are unchanged.
  * fees: entry maker 0.02%, exit taker 0.05%; feeR = price*rate / risk_pts.
  * funding: 8h settlements (00/08/16 UTC) inside (fill open, exit close],
    nominal = riskU / stopDistFrac, riskU = 1.1232U (2% of 56.16U).
  * stop slippage: adverse 0 / 0.05% / 0.1% on stop exits only (base grid).
"""
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

WARM = 420
COOL = 8
TEST_WINDOW = 96
DEPART = 0.5
RISK_U = 1.1232

# ---------------------------------------------------------------- helpers
def tr_array(h, l, c):
    tr = np.empty(len(h))
    tr[0] = np.nan
    tr[1:] = np.maximum(h[1:] - l[1:],
                        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return tr

def atr_series(h, l, c, n=14):
    """atr[i] = mean of last 14 TRs ending at i (== tf.atr(window) for a
    window ending at i). Valid for i >= 14."""
    tr = tr_array(h, l, c)
    out = np.full(len(h), np.nan)
    cs = np.nancumsum(np.where(np.isnan(tr), 0.0, tr))
    idx = np.arange(len(h))
    # sum of tr[i-13..i] = cs[i] - cs[i-14] (tr[0] is nan->0, harmless: any
    # window ending at i>=14 never includes tr[0])
    out[14:] = (cs[14:] - cs[:-14]) / n
    return out

def ema50_series(c):
    e = np.full(len(c), np.nan)
    if len(c) < 50:
        return e
    v = float(np.mean(c[:50]))
    e[49] = v
    for i in range(50, len(c)):
        v = c[i] * 2 / 51 + v * (1 - 2 / 51)
        e[i] = v
    return e

def swings_tf(h, l, k=2):
    """tf.swings semantics (ties count): h[i]==max of h[i-k..i+k]."""
    n = len(h)
    hi, lo = [], []
    if n < 2 * k + 1:
        return hi, lo
    wh = sliding_window_view(h, 2 * k + 1)
    wl = sliding_window_view(l, 2 * k + 1)
    for i in range(k, n - k):
        w = wh[i - k]
        if h[i] == w.max():
            hi.append((i, float(h[i])))
        w = wl[i - k]
        if l[i] == w.min():
            lo.append((i, float(l[i])))
    return hi, lo

def swings_strict(h, l, k=2):
    """key_levels.swings semantics (strict > / < vs all neighbours)."""
    n = len(h)
    hi, lo = [], []
    if n < 2 * k + 1:
        return hi, lo
    wh = sliding_window_view(h, 2 * k + 1)
    wl = sliding_window_view(l, 2 * k + 1)
    for i in range(k, n - k):
        w = wh[i - k]
        if h[i] == w.max() and int(np.sum(w == h[i])) == 1:
            hi.append((i, float(h[i])))
        w = wl[i - k]
        if l[i] == w.min() and int(np.sum(w == l[i])) == 1:
            lo.append((i, float(l[i])))
    return hi, lo

def strict_dir(hi, lo, a):
    """_strict_dir on already-computed swings (last 3 each)."""
    if len(hi) < 3 or len(lo) < 3:
        return None
    hv = [v for _, v in hi[-3:]]
    lv = [v for _, v in lo[-3:]]
    thr = 0.5 * a
    hs = [hv[i + 1] - hv[i] for i in range(2)]
    ls = [lv[i + 1] - lv[i] for i in range(2)]
    if all(x >= thr for x in hs) and all(x >= thr for x in ls):
        return "long"
    if all(x <= -thr for x in hs) and all(x <= -thr for x in ls):
        return "short"
    return None

def _held_res(h, l, c, idx, price, band_top, a):
    after = slice(idx + 1, idx + 9)
    if idx + 1 >= len(h):
        return False
    if np.any(c[idx + 1:idx + 5] > band_top):
        return False
    return price - np.min(l[after]) >= 1.0 * a

def _held_sup(h, l, c, idx, price, band_bottom, a):
    if idx + 1 >= len(h):
        return False
    if np.any(c[idx + 1:idx + 5] < band_bottom):
        return False
    return np.max(h[idx + 1:idx + 9]) - price >= 1.0 * a

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

def find_levels_np(h, l, c, a):
    """Exact port of key_levels.find_levels on raw arrays."""
    hi, lo = swings_strict(h, l)
    res = []
    if hi:
        for cl in _clusters(hi, 0.35 * a):
            band = (min(v for _, v in cl), max(v for _, v in cl))
            valid = [(i, v) for i, v in cl if _held_res(h, l, c, i, v, band[1], a)]
            if len(valid) < 3:
                continue
            valid = valid[-9:]
            vals = [v for _, v in valid]
            last_i = max(i for i, _ in valid)
            if len(h) - 1 - last_i > 96:
                continue
            res.append({"kind": "resistance", "line": min(vals),
                        "band": (min(vals), max(vals)), "touches": len(valid),
                        "last_touch_idx": last_i})
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
        members.sort(key=lambda x: (abs(x[1] - best_line), remaining.index(x)))
        members = members[:12]
        band = (min(v for _, v in members), max(v for _, v in members))
        valid = [(i, v) for i, v in members if _held_sup(h, l, c, i, v, band[0], a)]
        used = set(id(p) for p in members)
        remaining = [p for p in remaining if id(p) not in used]
        if len(valid) < 3:
            continue
        valid = valid[-9:]
        vals = [v for _, v in valid]
        last_i = max(i for i, _ in valid)
        if len(h) - 1 - last_i > 96:
            continue
        res.append({"kind": "support", "line": best_line,
                    "band": (min(vals), max(vals)), "touches": len(valid),
                    "last_touch_idx": last_i})
    # dedup: sort by -touches (stable: resistances first on ties), drop
    # levels whose band overlaps >= 50% of the smaller band width.
    lv = sorted(res, key=lambda x: -x["touches"])
    kept = []
    for L in lv:
        dup = False
        for K in kept:
            olo = max(L["band"][0], K["band"][0])
            ohi = min(L["band"][1], K["band"][1])
            if ohi > olo and (ohi - olo) >= 0.5 * min(
                    L["band"][1] - L["band"][0], K["band"][1] - K["band"][0]):
                dup = True
                break
        if not dup:
            kept.append(L)
    kept.sort(key=lambda x: x["line"])
    return kept

def contacts_sided(hw, lw, blo, bhi, a):
    """Port of _contacts_sided over a window (arrays). Returns list of
    (relative_index, 'above'|'below')."""
    out, in_c, away, prev_above = [], False, True, True
    for i in range(len(hw)):
        hit = lw[i] <= bhi and hw[i] >= blo
        if hit and not in_c and away:
            out.append((i, "above" if prev_above else "below"))
            in_c, away = True, False
        elif not hit:
            in_c = False
            if lw[i] >= bhi + DEPART * a:
                away, prev_above = True, True
            elif hw[i] <= blo - DEPART * a:
                away, prev_above = True, False
    return out

# ---------------------------------------------------------------- engine
class Data:
    def __init__(self, d15, d1h, d5):
        self.t15, self.o15, self.h15, self.l15, self.c15 = d15
        self.t1h, self.o1h, self.h1h, self.l1h, self.c1h = d1h
        self.t5, self.o5, self.h5, self.l5, self.c5 = d5
        self.ema = ema50_series(self.c15)
        self.atr15 = atr_series(self.h15, self.l15, self.c15)
        self.atr1h = atr_series(self.h1h, self.l1h, self.c1h)
        self.m5 = {int(t): i for i, t in enumerate(self.t5)}
        # last qualifying 1h index per 15m bar: h.t+3600000 <= bar.t+900000
        self.q1h = np.searchsorted(self.t1h + 3_600_000, self.t15 + 900_000,
                                   side="right") - 1

    def m5_bars(self, t15):
        """The 3 5m bars composing a 15m bar (or None if any missing)."""
        idx = [self.m5.get(int(t15 + k * 300_000)) for k in range(3)]
        if any(v is None for v in idx):
            return None
        return idx

    def signal_5m_dicts(self, t15):
        """The original w5: last 100 5m bars ending at the signal 15m bar's
        third constituent 5m bar. _e_signal checks only the last 3, but
        morning/evening star look back 2 bars, so the full window matters:
        a bare 3-bar window would corrupt star patterns at constituents 0-1
        (negative-index wraparound / i<2 guard)."""
        idx3 = self.m5.get(int(t15 + 600_000))
        if idx3 is None:
            return None
        idxs = list(range(max(0, idx3 - 99), idx3 + 1))
        if any(self.t5[j + 1] - self.t5[j] != 300_000 for j in idxs[:-1]):
            return None
        return [{"o": float(self.o5[j]), "h": float(self.h5[j]),
                 "l": float(self.l5[j]), "c": float(self.c5[j])} for j in idxs]

def run_paper(D, is_signal_bar):
    """Unified-semantics paper run. Returns (trades, skipped_lev). Each
    trade: dict with i (signal bar idx), t (ms), dir, entry, sl, risk,
    level_line, exit_i, exit_px, reason, r (gross, unrounded), hold_h."""
    n = len(D.t15)
    trades, pos = [], None
    cool_until = {"long": -1, "short": -1}
    skipped_lev = 0
    for i in range(WARM, n):
        bar_t = int(D.t15[i])
        # ---- exit (entry bar not judged) ----
        if pos is not None and i > pos["i"]:
            trio = D.m5_bars(bar_t)
            res = None
            if trio is not None:
                for j in trio:
                    if (pos["dir"] == "long" and D.l5[j] <= pos["sl"]) or \
                       (pos["dir"] == "short" and D.h5[j] >= pos["sl"]):
                        res = ("stop", pos["sl"])
                        break
            if res is None and not np.isnan(D.ema[i]):
                cp, em = D.c15[i], D.ema[i]
                if (pos["dir"] == "long" and cp < em) or \
                   (pos["dir"] == "short" and cp > em):
                    res = ("ema50_close", cp)
            if res:
                reason, px = res
                rr = -1.0 if reason == "stop" else (
                    (px - pos["entry"]) if pos["dir"] == "long"
                    else (pos["entry"] - px)) / pos["risk"]
                trades.append({**pos, "exit_i": i, "exit_px": float(px),
                               "reason": reason, "r": float(rr),
                               "hold_h": round((i - pos["i"]) * 0.25, 1)})
                cool_until[pos["dir"]] = i + COOL
                pos = None
        # ---- entry ----
        if pos is None:
            q = int(D.q1h[i])
            if q < 59:
                continue
            w1h = slice(q - 99, q + 1)
            a = D.atr15[i]
            a1h = D.atr1h[q]
            if np.isnan(a) or np.isnan(a1h):
                continue
            hi, lo = swings_tf(D.h1h[w1h], D.l1h[w1h])
            big_dir = strict_dir(hi, lo, a1h)
            if big_dir is None:
                continue
            h15w = D.h15[i - 399:i + 1]
            l15w = D.l15[i - 399:i + 1]
            c15w = D.c15[i - 399:i + 1]
            levels = find_levels_np(h15w, l15w, c15w, a)
            sig = None
            price = D.c15[i]
            hw = h15w[-TEST_WINDOW:]
            lw = l15w[-TEST_WINDOW:]
            m5d = None
            for lv in levels:
                blo, bhi = lv["band"]
                if big_dir == "long":
                    if price < blo:
                        continue
                    ct = [s for _, s in contacts_sided(hw, lw, blo, bhi, a)
                          if s == "above"]
                    if len(ct) < 2:
                        continue
                    if not (lw[-1] <= bhi and hw[-1] >= blo):
                        continue
                    d = "long"
                else:
                    if price > bhi:
                        continue
                    ct = [s for _, s in contacts_sided(hw, lw, blo, bhi, a)
                          if s == "below"]
                    if len(ct) < 2:
                        continue
                    if not (lw[-1] <= bhi and hw[-1] >= blo):
                        continue
                    d = "short"
                if m5d is None:
                    m5d = D.signal_5m_dicts(bar_t)
                    if m5d is None:
                        break
                if any(is_signal_bar(m5d, j, d)
                       for j in range(len(m5d) - 3, len(m5d))):
                    sig = {"direction": d, "level": lv,
                           "stop": blo - a if d == "long" else bhi + a}
                    break
            if sig:
                d = sig["direction"]
                if i <= cool_until[d]:
                    continue
                entry, sl = float(price), float(sig["stop"])
                risk = abs(entry - sl)
                if risk <= 0:
                    continue
                if 0.02 / (risk / entry) > 20:
                    skipped_lev += 1
                    continue
                pos = {"i": i, "t": bar_t, "dir": d, "entry": entry,
                       "sl": sl, "risk": risk, "level_line": float(sig["level"]["line"]),
                       "level_band": [float(sig["level"]["band"][0]),
                                      float(sig["level"]["band"][1])],
                       "tests": None}
    return trades, skipped_lev, (None if pos is None else pos["dir"])

# ---------------------------------------------------------------- exec post-processing
def scan_exit_from(D, pos, start_bar, start_5m=None):
    """Scan bars from start_bar (inclusive) with per-bar stop-then-EMA
    order. If start_5m is given (list of 5m indices within start_bar),
    check those 5m bars for stop first, then continue with later bars.
    Returns (exit_bar, exit_px, reason) or None."""
    if start_5m is not None:
        for j in start_5m:
            if (pos["dir"] == "long" and D.l5[j] <= pos["sl"]) or \
               (pos["dir"] == "short" and D.h5[j] >= pos["sl"]):
                return (start_bar, pos["sl"], "stop")
        start_bar += 1
    n = len(D.t15)
    for j in range(start_bar, n):
        trio = D.m5_bars(int(D.t15[j]))
        if trio is not None:
            for k in trio:
                if (pos["dir"] == "long" and D.l5[k] <= pos["sl"]) or \
                   (pos["dir"] == "short" and D.h5[k] >= pos["sl"]):
                    return (j, pos["sl"], "stop")
        if not np.isnan(D.ema[j]):
            cp, em = D.c15[j], D.ema[j]
            if (pos["dir"] == "long" and cp < em) or \
               (pos["dir"] == "short" and cp > em):
                return (j, float(cp), "ema50_close")
    return None

def exec_trade(D, tr, fill_kind, fund_series):
    """Apply fill model + executor exit correction + fees + funding.
    fill_kind in ('T0','T1','T2'). fund_series: sorted (ms, rate) list.
    Returns dict with status ('filled'|'missed'|'unresolved'), exit info,
    gross/exit R components. All R unrounded (rounding only at print)."""
    i, f = tr["i"], tr["i"] + 1
    out = {"signal_i": i, "fill_kind": fill_kind, "dir": tr["dir"],
           "entry": tr["entry"], "sl": tr["sl"], "risk": tr["risk"]}
    if f >= len(D.t15):
        out["status"] = "unresolved"
        return out
    limit = tr["entry"]
    pen = {"T0": 0.0, "T1": 0.0005, "T2": 0.001}[fill_kind]
    if tr["dir"] == "long":
        filled = D.l15[f] <= limit * (1 - pen)
    else:
        filled = D.h15[f] >= limit * (1 + pen)
    if not filled:
        out["status"] = "missed"
        return out
    out["status"] = "filled"
    out["fill_i"] = f
    # paper exit (unified semantics) for this trade
    pe_i, pe_px, pe_reason = tr["exit_i"], tr["exit_px"], tr["reason"]
    if pe_i == f:
        # exit inside fill bar: executor correction
        trio = D.m5_bars(int(D.t15[f]))
        if pe_reason == "stop":
            # fill 5m bar: first 5m bar touching the limit
            fill5 = None
            stop5 = None
            for k, j in enumerate(trio):
                if fill5 is None and ((tr["dir"] == "long" and D.l5[j] <= limit) or
                                      (tr["dir"] == "short" and D.h5[j] >= limit)):
                    fill5 = k
                if stop5 is None and ((tr["dir"] == "long" and D.l5[j] <= tr["sl"]) or
                                      (tr["dir"] == "short" and D.h5[j] >= tr["sl"])):
                    stop5 = k
            if stop5 is not None and fill5 is not None and stop5 > fill5:
                ex = (f, tr["sl"], "stop")
            else:
                rest = trio[fill5 + 1:] if fill5 is not None else trio
                ex = scan_exit_from(D, tr, f, start_5m=rest)
        else:  # ema exit in fill bar: entry bar skipped -> from f+1
            ex = scan_exit_from(D, tr, f + 1)
    elif pe_i > f:
        ex = (pe_i, pe_px, pe_reason)
    else:
        ex = None  # cannot happen (paper exit bar >= signal+1 = f)
    if ex is None:
        out["status"] = "unresolved"
        return out
    e_i, e_px, e_reason = ex
    out.update({"exit_i": int(e_i), "exit_px": float(e_px), "reason": e_reason})
    # funding: settlements in (fill bar open, exit bar close]
    t0 = int(D.t15[f])
    t1 = int(D.t15[e_i]) + 900_000
    sd = tr["risk"] / tr["entry"]
    fsum = 0.0
    for ts, rate in fund_series:
        if t0 < ts <= t1:
            fsum += rate
    fund_r = (-fsum / sd) if tr["dir"] == "long" else (fsum / sd)
    out["funding_r"] = fund_r
    out["stop_dist_pct"] = sd * 100
    return out

def net_r(tr, exit_px, reason, stop_slip=0.0, ema_slip=0.0, entry_fee=0.0002):
    """Net R for a filled trade given exit price/reason and stress knobs.
    stop_slip / ema_slip: adverse fraction applied to the exit price."""
    entry, sl, risk = tr["entry"], tr["sl"], tr["risk"]
    px = exit_px
    if reason == "stop" and stop_slip:
        px = sl * (1 - stop_slip) if tr["dir"] == "long" else sl * (1 + stop_slip)
    if reason == "ema50_close" and ema_slip:
        px = px * (1 - ema_slip) if tr["dir"] == "long" else px * (1 + ema_slip)
    gross = -1.0 if reason == "stop" else (
        (px - entry) if tr["dir"] == "long" else (entry - px)) / risk
    if reason == "stop":
        # gross is exactly -1 by construction when slip==0; with slip it is
        # worse than -1; keep formula general:
        gross = ((px - entry) if tr["dir"] == "long" else (entry - px)) / risk
    fee_r = (entry * entry_fee + px * 0.0005) / risk
    return gross, fee_r
