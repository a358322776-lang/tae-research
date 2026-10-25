"""Validate numpy helpers in v41_engine against the ORIGINAL modules.

Compares, on real in-sample windows:
  * atr_series   vs tf.atr
  * swings_tf    vs tf.swings (ties-count semantics)
  * strict_dir   vs _strict_dir (transcribed from backtest-v4-eth-unified.py)
  * find_levels_np vs key_levels.find_levels (exact dict equality)
  * contacts_sided vs a literal transcription of _contacts_sided
Exits non-zero on any mismatch. Run after fetching in-sample data.
"""
import importlib.util, random, sys
import numpy as np
sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/hidden_files")
sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/robustness-v41")
import v41_engine as E

HID = "/home/hatch/workspace/goals/100u-200u/hidden_files"
spec = importlib.util.spec_from_file_location("tf", f"{HID}/tae-scanner-tradfi.py")
tf = importlib.util.module_from_spec(spec); spec.loader.exec_module(tf)
from key_levels import find_levels

import os
DATA_DIR = os.environ.get("ROBUST_DATA",
    "/home/hatch/workspace/goals/100u-200u/files/robustness-v41/data_cache")

def load(name):
    d = {}
    for iv in ("15m", "1h"):
        z = np.load(f"{DATA_DIR}/{name}_{iv}.npz")
        d[iv] = (z["t"], z["ohlc"])
    return d

def dicts(t, ohlc, sl):
    return [{"t": int(t[i]), "o": float(ohlc[i][0]), "h": float(ohlc[i][1]),
             "l": float(ohlc[i][2]), "c": float(ohlc[i][3])} for i in sl]

def strict_dir_ref(candles, a, k=2):
    hi, lo = tf.swings(candles, k=k)
    if len(hi) < 3 or len(lo) < 3:
        return None
    thr = 0.5 * a
    hv = [v for _, v in hi][-3:]; lv = [v for _, v in lo][-3:]
    hs = [hv[i + 1] - hv[i] for i in range(2)]; ls = [lv[i + 1] - lv[i] for i in range(2)]
    if all(x >= thr for x in hs) and all(x >= thr for x in ls):
        return "long"
    if all(x <= -thr for x in hs) and all(x <= -thr for x in ls):
        return "short"
    return None

def contacts_ref(c15, level, a):
    from key_signals import DEPART
    blo, bhi = level["band"]
    out, in_c, away, prev_above = [], False, True, True
    for i, cd in enumerate(c15):
        hit = cd["l"] <= bhi and cd["h"] >= blo
        if hit and not in_c and away:
            out.append((i, "above" if prev_above else "below"))
            in_c, away = True, False
        elif not hit:
            in_c = False
            if cd["l"] >= bhi + DEPART * a:
                away, prev_above = True, True
            elif cd["h"] <= blo - DEPART * a:
                away, prev_above = True, False
    return out

def main():
    d = load("insample")
    t15, o15 = d["15m"]
    t1h, o1h = d["1h"]
    h15, l15, c15 = o15[:, 1], o15[:, 2], o15[:, 3]
    h1h, l1h, c1h = o1h[:, 1], o1h[:, 2], o1h[:, 3]
    atr15 = E.atr_series(h15, l15, c15)
    atr1h = E.atr_series(h1h, l1h, c1h)
    rng = random.Random(20261025)
    fails = 0

    # ATR: 200 random windows
    for _ in range(200):
        i = rng.randrange(400, len(t15))
        ref = tf.atr(dicts(t15, o15, range(i - 399, i + 1)))
        if abs(ref - atr15[i]) > 1e-9:
            print("ATR15 MISMATCH", i, ref, atr15[i]); fails += 1
    for _ in range(100):
        i = rng.randrange(100, len(t1h))
        ref = tf.atr(dicts(t1h, o1h, range(i - 99, i + 1)))
        if abs(ref - atr1h[i]) > 1e-9:
            print("ATR1H MISMATCH", i, ref, atr1h[i]); fails += 1
    print("ATR checks done, fails =", fails)

    # swings_tf + strict_dir: 200 random 1h windows
    for _ in range(200):
        i = rng.randrange(100, len(t1h))
        sl = range(i - 99, i + 1)
        hi_r, lo_r = tf.swings(dicts(t1h, o1h, sl))
        hi_n, lo_n = E.swings_tf(h1h[i - 99:i + 1], l1h[i - 99:i + 1])
        if hi_r != hi_n or lo_r != lo_n:
            print("SWINGS MISMATCH", i); fails += 1; continue
        a = atr1h[i]
        if strict_dir_ref(dicts(t1h, o1h, sl), a) != E.strict_dir(hi_n, lo_n, a):
            print("STRICT_DIR MISMATCH", i); fails += 1
    print("swings/strict_dir checks done, fails =", fails)

    # find_levels: 150 random 400-bar windows (exact dict equality)
    for k in range(150):
        i = rng.randrange(400, len(t15))
        sl = range(i - 399, i + 1)
        a = atr15[i]
        ref = find_levels(dicts(t15, o15, sl), a)
        got = E.find_levels_np(h15[i - 399:i + 1], l15[i - 399:i + 1],
                               c15[i - 399:i + 1], a)
        if len(ref) != len(got):
            print("LEVELS COUNT MISMATCH", k, i, len(ref), len(got)); fails += 1; continue
        for r, g in zip(ref, got):
            if (r["kind"] != g["kind"] or abs(r["line"] - g["line"]) > 1e-9
                    or abs(r["band"][0] - g["band"][0]) > 1e-9
                    or abs(r["band"][1] - g["band"][1]) > 1e-9
                    or r["touches"] != g["touches"]
                    or r["last_touch_idx"] != g["last_touch_idx"]):
                print("LEVEL MISMATCH", k, i, r, g); fails += 1; break
    print("find_levels checks done, fails =", fails)

    # contacts_sided: 100 random (window, level) pairs
    for _ in range(100):
        i = rng.randrange(400, len(t15))
        a = atr15[i]
        lv = E.find_levels_np(h15[i - 399:i + 1], l15[i - 399:i + 1],
                              c15[i - 399:i + 1], a)
        if not lv:
            continue
        L = lv[rng.randrange(len(lv))]
        ref = contacts_ref(dicts(t15, o15, range(i - 95, i + 1)), L, a)
        got = E.contacts_sided(h15[i - 95:i + 1], l15[i - 95:i + 1],
                               L["band"][0], L["band"][1], a)
        if ref != got:
            print("CONTACTS MISMATCH", i, L, ref, got); fails += 1
    print("contacts checks done, fails =", fails)
    print("TOTAL FAILS:", fails)
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
