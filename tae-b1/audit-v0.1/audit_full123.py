"""Audit full-population scan (read-only, 123 OOS): fill-bar free pass,
EMA next-open delta, stop+EMA coincidence, T2 inversion. No rule changes."""
import json
import sys

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
from b1_engine import Data, simulate_exit  # noqa: E402

D = Data()
t15, o15, t5, o5 = D.t15, D.o15, D.t5, D.o5
c15 = o15[:, 3]
entries = json.load(open("/tmp/audit_b_oos_entries.json"))
FEE, SLIP = 0.0005, 0.0005


def net_of(e, exit_px, exit_close_ms):
    d, entry, stop, risk = e["dir"], e["entry"], e["stop"], e["risk"]
    sd = risk / entry
    gross = (exit_px - entry) / risk if d == "long" else (entry - exit_px) / risk
    fsum = D.funding_sum(e["fill_open_ms"], exit_close_ms)
    fund = fsum / sd if d == "long" else -fsum / sd
    return gross - 2 * FEE / sd - fund


n_fill_breach = n_later_breach = 0
fill_breach_ids = []
ema_deltas = []
n_stop = n_coinc = 0
coinc_ids = []
n_t2_stop = 0
for i, e in enumerate(entries):
    tid = f"B{i+1:03d}"
    d, stop = e["dir"], e["stop"]
    f_open = int(t5[e["fill_idx"]])
    cont_open = f_open - (f_open % 900_000)
    k0 = int(np.searchsorted(t15, cont_open, side="left"))
    mk0 = int(np.searchsorted(t5, int(t15[k0]), side="left"))
    for m in range(mk0, min(mk0 + 3, len(t5))):
        hit = (float(o5[m][2]) <= stop) if d == "long" else (float(o5[m][1]) >= stop)
        if hit:
            if m == e["fill_idx"]:
                n_fill_breach += 1
                fill_breach_ids.append((tid, "fill_bar"))
            elif m > e["fill_idx"]:
                n_later_breach += 1
                fill_breach_ids.append((tid, "later_bar"))
    base = e["base"]
    if base["reason"] == "stop":
        n_stop += 1
        # exit 15m bar: 5m trigger bar -> containing 15m
        m_trig = None
        for k in range(k0 + 1, len(t15)):
            mk = int(np.searchsorted(t5, int(t15[k]), side="left"))
            found = False
            for m in range(mk, min(mk + 3, len(t5))):
                if d == "long" and float(o5[m][2]) <= stop:
                    m_trig, k_trig = m, k
                    found = True
                    break
                if d == "short" and float(o5[m][1]) >= stop:
                    m_trig, k_trig = m, k
                    found = True
                    break
            if found:
                break
        if m_trig is not None:
            ref = float(D.ema50[k_trig])
            ck = float(c15[k_trig])
            cross = (ck < ref) if d == "long" else (ck > ref)
            if cross:
                n_coinc += 1
                coinc_ids.append(tid)
        out2 = simulate_exit(D, e, "T2", "EMA50")
        if out2 and out2["reason"] == "stop":
            n_t2_stop += 1
    elif base["reason"] == "EMA50":
        k_exit = int(np.searchsorted(t15, base["exit_close_ms"], side="right")) - 1
        if k_exit + 1 < len(t15):
            nxt = float(o15[k_exit + 1][0])
            nn = net_of(e, nxt, int(t15[k_exit + 1]) + 900_000)
            base_net = None
            import csv as _csv
            rows = list(_csv.DictReader(open("/home/hatch/workspace/goals/100u-200u/files/tae-b1/trades_b_oos.csv")))
            base_net = float(rows[i]["net_T0_EMA50"])
            ema_deltas.append(nn - base_net)
ema_deltas = np.array(ema_deltas)
print(f"fill-bar breach: fill_bar={n_fill_breach} later_5m={n_later_breach} ids={fill_breach_ids}")
print(f"stop trades: {n_stop}, ema_cross_in_stop_exit_bar: {n_coinc} {coinc_ids}")
print(f"T2 stop trades (full 123): {n_t2_stop}")
print(f"EMA exits: n={len(ema_deltas)} mean={ema_deltas.mean():.4f} sum={ema_deltas.sum():.4f} "
      f"pos={int((ema_deltas > 0).sum())} neg={int((ema_deltas < 0).sum())} "
      f"min={ema_deltas.min():.4f} max={ema_deltas.max():.4f}")
