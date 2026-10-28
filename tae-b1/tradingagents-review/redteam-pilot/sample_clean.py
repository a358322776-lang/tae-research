"""Micro B1-like backtest engine (sandbox pilot only; NOT production B1).

Simplified analogues of B1 mechanics: swing-cluster key bands, single-bar
close breakout, pullback test, EMA50 exit, maker/taker fees, funding accrual.
Synthetic data only. All results are exploratory; nothing here is a signal.

Simplifications vs production B1 (documented, not hidden): trend gate uses
same-timeframe swings instead of a separate 1H series; levels refresh every
20 bars instead of every bar; one generic rejection-bar rule instead of six
signal candles; the loss halt uses cumulative loss because synthetic
timestamps carry no calendar days.
"""
import random

# --- fixed parameter set (no grid search; one declared primary hypothesis) ---
# PRIMARY hypothesis, declared up front: pullback entries after a confirmed
# breakout drift further than random entries over the next 48 bars.
# No parameter grid is run, so no family-wise correction is due.
ATR_LEN = 14
SWING_K = 2
MIN_TOUCH = 3
CLUSTER_TOL = 0.35
TOUCH_TOL = 0.2
STALE_BARS = 96
SEQ_EXPIRE = 48
EMA_LEN = 50
RISK_PCT = 0.02
CAPITAL = 10000.0
LEVERAGE = 5
MAX_LEVERAGE = 20
POSITION_CAP = 0.5
DAILY_LOSS_LIMIT = 0.06
MAKER = 0.0002
TAKER = 0.0005
SLIPPAGE_STOP = 0.0005
FUNDING_RATE = 0.0001
FUNDING_EVERY = 32
MIN_TRADES = 30


def gen_symbol(name, n, seed, trend=0.0, end_early=None, gap_at=None):
    rng = random.Random(seed)
    bars = []
    price = 2000.0
    ts = 0
    for i in range(n):
        if end_early is not None and i >= end_early:
            break
        if gap_at is not None and i == gap_at:
            ts += 4  # timestamp jump: the intervening bars are missing
        o = price
        c = o + trend + rng.uniform(-1, 1) * 6.0
        h = max(o, c) + rng.uniform(0, 3)
        l = min(o, c) - rng.uniform(0, 3)
        bars.append({"ts": ts, "open": o, "high": h, "low": l, "close": c})
        price = c
        ts += 1
    return {"name": name, "bars": bars}


def gen_universe():
    # Every symbol runs, whatever its history length: no completeness filter.
    return [
        gen_symbol("SYM-A", 1200, seed=11, trend=0.02),
        gen_symbol("SYM-B", 1200, seed=23, trend=-0.01, end_early=700),
        gen_symbol("SYM-C", 1200, seed=37, trend=0.0, gap_at=600),
    ]


def atr(bars, j):
    if j < ATR_LEN:
        return None
    trs = []
    for k in range(j - ATR_LEN + 1, j + 1):
        h, l, pc = bars[k]["high"], bars[k]["low"], bars[k - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs)


def ema_series(closes, n):
    # Causal recursion: EMA at index j depends only on closes up to j.
    out = []
    k = 2 / (n + 1)
    e = None
    for c in closes:
        e = c if e is None else c * k + e * (1 - k)
        out.append(e)
    return out


def find_swings(bars, k):
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    sh, sl = [], []
    for i in range(k, len(bars) - k):
        if highs[i] == max(highs[i - k:i + k + 1]) and highs[i] > highs[i - 1]:
            sh.append((i, highs[i]))
        if lows[i] == min(lows[i - k:i + k + 1]) and lows[i] < lows[i - 1]:
            sl.append((i, lows[i]))
    return sh, sl


def find_levels(bars, a):
    # Cluster swing extremes within CLUSTER_TOL * ATR; band = (min, max).
    # A swing at index i is confirmed only once bar i + k has closed, and the
    # caller only passes bars up to the current bar, so only confirmed
    # swings can appear here.
    sh, sl = find_swings(bars, SWING_K)
    bands = []
    window = bars[-400:]
    for swings, side in ((sh, "res"), (sl, "sup")):
        pts = sorted(swings, key=lambda x: x[1])
        clusters = []
        for idx, price in pts:
            if clusters and abs(price - clusters[-1][-1][1]) <= CLUSTER_TOL * a:
                clusters[-1].append((idx, price))
            else:
                clusters.append([(idx, price)])
        for cl in clusters:
            lo = min(p for _, p in cl)
            hi = max(p for _, p in cl)
            touches = 0
            for b in window:
                ext = b["high"] if side == "res" else b["low"]
                if lo - TOUCH_TOL * a <= ext <= hi + TOUCH_TOL * a:
                    touches += 1
            if touches >= MIN_TOUCH:
                bands.append({"side": side, "lo": lo, "hi": hi,
                             "last_idx": max(i for i, _ in cl), "touches": touches})
    return bands


def trend_gate(bars, a):
    # Simplified analogue of the 1H strict trend gate: last three swing
    # highs and lows each step in one direction by at least 0.5 * ATR.
    sh, sl = find_swings(bars, SWING_K)
    if len(sh) >= 3 and len(sl) >= 3:
        h3 = [p for _, p in sh[-3:]]
        l3 = [p for _, p in sl[-3:]]
        if h3[0] < h3[1] < h3[2] and l3[0] < l3[1] < l3[2] and \
           (h3[1] - h3[0]) >= 0.5 * a and (h3[2] - h3[1]) >= 0.5 * a:
            return 1
        if h3[0] > h3[1] > h3[2] and l3[0] > l3[1] > l3[2] and \
           (h3[0] - h3[1]) >= 0.5 * a and (h3[1] - h3[2]) >= 0.5 * a:
            return -1
    return None


def apply_funding(tr, periods):
    # Longs pay when the rate is positive; shorts receive.
    signed = -tr["side"] * tr["notional"] * FUNDING_RATE * periods
    tr["funding"] += signed
    return signed


def close_trade(pos, bar, reason):
    if reason == "stop":
        if pos["side"] == 1:
            fill = pos["stop"] * (1 - SLIPPAGE_STOP)
        else:
            fill = pos["stop"] * (1 + SLIPPAGE_STOP)
        fee = pos["notional"] * TAKER
    elif reason == "ema":
        fill = bar["close"]
        fee = pos["notional"] * MAKER
    else:
        raise ValueError(reason)
    pnl = pos["side"] * (fill - pos["entry"]) * pos["size"] - pos["fee_in"] - fee + pos["funding"]
    return {"side": pos["side"], "entry": pos["entry"], "stop": pos["stop"],
            "exit": fill, "reason": reason, "pnl": pnl, "funding": pos["funding"]}


def resolve_same_bar(bar, pending):
    # stop first (conservative): when one bar covers both the entry trigger
    # and the stop, the stop wins and no entry is taken.
    side = pending["side"]
    trig, stop = pending["trigger"], pending["stop"]
    if side == 1:
        covers_trigger = bar["high"] >= trig
        covers_stop = bar["low"] <= stop
    else:
        covers_trigger = bar["low"] <= trig
        covers_stop = bar["high"] >= stop
    if covers_trigger and covers_stop:
        return "stop_first"
    if covers_trigger:
        return "enter"
    return "wait"


def run_symbol(sym):
    bars = sym["bars"]
    emas = ema_series([b["close"] for b in bars], EMA_LEN)
    trades = []
    gap_manifest = []
    seq = None
    pending = None
    pos = None
    halted = False
    net_pnl = 0.0
    voided = expired = same_bar_skips = 0
    risk_budget = RISK_PCT * CAPITAL
    levels_cache = []
    cache_j = -100
    for j, bar in enumerate(bars):
        is_gap = False
        if j > 0 and bar["ts"] - bars[j - 1]["ts"] > 1:
            gap_manifest.append((bars[j - 1]["ts"], bar["ts"]))
            is_gap = True
        a = atr(bars, j)
        if a is None:
            continue
        if pos is not None:
            pos["held"] += 1
            if pos["held"] % FUNDING_EVERY == 0:
                apply_funding(pos, 1)
            done = None
            if pos["side"] == 1:
                if bar["low"] <= pos["stop"]:
                    done = close_trade(pos, bar, "stop")
                elif bar["close"] < emas[j]:
                    done = close_trade(pos, bar, "ema")
            else:
                if bar["high"] >= pos["stop"]:
                    done = close_trade(pos, bar, "stop")
                elif bar["close"] > emas[j]:
                    done = close_trade(pos, bar, "ema")
            if done is not None:
                done["R"] = done["pnl"] / risk_budget
                trades.append(done)
                net_pnl += done["pnl"]
                if net_pnl < -DAILY_LOSS_LIMIT * CAPITAL:
                    halted = True
                pos = None
            continue
        if pending is not None:
            outcome = resolve_same_bar(bar, pending)
            if outcome == "stop_first":
                pending = None
                same_bar_skips += 1
                continue
            if outcome == "enter":
                side = pending["side"]
                trig = pending["trigger"]
                stop = pending["stop"]
                if side == 1:
                    fill = trig * (1 + SLIPPAGE_STOP)
                else:
                    fill = trig * (1 - SLIPPAGE_STOP)
                stop_dist = abs(fill - stop)
                if stop_dist <= 0:
                    pending = None
                    continue
                size = risk_budget / stop_dist
                notional = size * fill
                if notional > POSITION_CAP * CAPITAL:
                    size = POSITION_CAP * CAPITAL / fill
                    notional = size * fill
                pos = {"side": side, "entry": fill, "stop": stop, "size": size,
                       "notional": notional, "fee_in": notional * TAKER,
                       "funding": 0.0, "held": 0}
                pending = None
                continue
            if j - pending["since"] > 3:
                pending = None
            continue
        if seq is not None:
            band = seq["band"]
            if j - seq["b0"] > SEQ_EXPIRE:
                seq = None
                expired += 1
                continue
            if seq["side"] == 1 and bar["close"] < band["lo"]:
                seq = None
                voided += 1
                continue
            if seq["side"] == -1 and bar["close"] > band["hi"]:
                seq = None
                voided += 1
                continue
            ext = bar["low"] if seq["side"] == 1 else bar["high"]
            if band["lo"] - TOUCH_TOL * a <= ext <= band["hi"] + TOUCH_TOL * a:
                seq["touches"] += 1
            if seq["touches"] >= 2 and not is_gap:
                if seq["side"] == 1 and bar["close"] >= band["lo"]:
                    pending = {"side": 1, "trigger": bar["high"],
                               "stop": band["lo"] - a, "since": j}
                    seq = None
                elif seq["side"] == -1 and bar["close"] <= band["hi"]:
                    pending = {"side": -1, "trigger": bar["low"],
                               "stop": band["hi"] + a, "since": j}
                    seq = None
            continue
        if halted or is_gap:
            continue
        if j - cache_j >= 20 or not levels_cache:
            levels_cache = find_levels(bars[:j + 1], a)
            cache_j = j
        tr = trend_gate(bars[:j + 1], a)
        for band in levels_cache:
            band_age = j - band["last_idx"]
            if band_age > STALE_BARS:
                continue
            if tr == 1 and bar["close"] > band["hi"]:
                seq = {"side": 1, "band": band, "b0": j, "touches": 0}
                break
            if tr == -1 and bar["close"] < band["lo"]:
                seq = {"side": -1, "band": band, "b0": j, "touches": 0}
                break
    return {"name": sym["name"], "trades": trades, "net_pnl": net_pnl,
            "net_R": net_pnl / risk_budget, "voided": voided, "expired": expired,
            "same_bar_skips": same_bar_skips, "gaps": gap_manifest}


def main():
    # Full available range, every symbol: no window picking, no filtering.
    total_R = 0.0
    total_n = 0
    for sym in gen_universe():
        r = run_symbol(sym)
        total_R += r["net_R"]
        total_n += len(r["trades"])
        print(f'{r["name"]}: trades={len(r["trades"])} net_R={r["net_R"]:.2f} '
              f'voided={r["voided"]} expired={r["expired"]} '
              f'same_bar_skips={r["same_bar_skips"]} gaps={len(r["gaps"])}')
    print(f"TOTAL: trades={total_n} net_R={total_R:.2f}")
    if total_n < MIN_TRADES:
        print("NOTE: sample below MIN_TRADES; results are exploratory only.")


if __name__ == "__main__":
    main()
