"""TAE-B1 audit charts (read-only): one 3-panel PNG per sampled trade (1H/15m/5m)."""
import csv
import json
import os
import sys
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
from b1_engine import Data  # noqa: E402

B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1"
OUT = f"{B1}/audit-v0.1/charts"
os.makedirs(OUT, exist_ok=True)

D = Data()
t15, o15, t5, o5 = D.t15, D.o15, D.t5, D.o5
d1h = np.load(f"{B1}/data_cache/stitched_1h.npz")
t1h, o1h = d1h["t"], d1h["ohlc"]

picked = json.load(open("/tmp/audit_picked.json"))
level = {r["trade_id"]: r for r in csv.DictReader(open(f"{B1}/audit-v0.1/level_check.csv"))}


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def candles(ax, t, o, x0, x1, width=0.7):
    o, h, l, c = o[:, 0], o[:, 1], o[:, 2], o[:, 3]
    xs = np.arange(x0, x1 + 1)
    up = c >= o
    for x, uu in zip(xs, up):
        col = "#26a69a" if uu else "#ef5350"
        ax.vlines(x, l[x - x0], h[x - x0], color=col, linewidth=0.9)
        lo_, hi_ = min(o[x - x0], c[x - x0]), max(o[x - x0], c[x - x0])
        ax.add_patch(plt.Rectangle((x - width / 2, lo_), width, max(hi_ - lo_, 1e-9),
                                   facecolor=col, edgecolor=col))


for e in picked:
    tid = e["tid"]
    d = e["dir"]
    j, r = e["b0"], e["reclaim_idx"]
    blo, bhi, stop, entry = e["blo"], e["bhi"], e["stop"], e["entry"]
    # first touch bar
    touch = None
    for k in range(j + 1, r + 1):
        if float(o15[k][2]) <= bhi and float(o15[k][1]) >= blo:
            touch = k
            break
    # exit 15m bar
    k_exit = int(np.searchsorted(t15, e["base"]["exit_close_ms"], side="right")) - 1
    # 1h bar containing b0
    p = int(np.searchsorted(t1h, int(t15[j]), side="right")) - 1
    trend = level[tid]["trend_1h_at_b0"]
    fig, axes = plt.subplots(3, 1, figsize=(15, 11), sharex=False,
                             gridspec_kw={"height_ratios": [1, 1.5, 1]})
    fig.suptitle(f"{tid} {d} | b0 {iso(int(t15[j]))} | band {blo:.2f}-{bhi:.2f} | "
                 f"entry {entry:.2f} stop {stop:.2f} | net {float(e['csv']['net_T0_EMA50']):.2f}R "
                 f"({e['base']['reason']}) | 1H trend {trend}", fontsize=11)
    # --- 1H ---
    ax = axes[0]
    a0, a1 = max(0, p - 40), min(len(t1h) - 1, p + 10)
    candles(ax, t1h, o1h[a0:a1 + 1], a0, a1)
    ax.axhline(blo, color="orange", linestyle="--", linewidth=1)
    ax.axhline(bhi, color="orange", linestyle="--", linewidth=1)
    ax.axvline(p, color="blue", linestyle=":", linewidth=1)
    ax.set_title(f"1H (bar {p} = b0's hour, blue dotted) | band orange dashed")
    ax.grid(True, alpha=0.3)
    # --- 15m ---
    ax = axes[1]
    b0x, b1x = max(0, j - 20), min(len(t15) - 1, k_exit + 5)
    candles(ax, t15, o15[b0x:b1x + 1], b0x, b1x)
    ax.axhspan(blo, bhi, color="orange", alpha=0.15)
    ax.axhline(blo, color="orange", linestyle="--", linewidth=1)
    ax.axhline(bhi, color="orange", linestyle="--", linewidth=1)
    ax.axhline(entry, color="green", linestyle="-", linewidth=1)
    ax.axhline(stop, color="red", linestyle="-", linewidth=1)
    ax.axvline(j, color="blue", linestyle=":", linewidth=1.2)
    if touch is not None:
        ax.axvline(touch, color="purple", linestyle=":", linewidth=1.2)
    ax.axvline(r, color="brown", linestyle=":", linewidth=1.2)
    ax.axvline(k_exit, color="black", linestyle=":", linewidth=1.2)
    ax.set_title("15m: blue=b0 breakout | purple=first touch | brown=reclaim | "
                 "black=exit | green=entry red=stop")
    ax.grid(True, alpha=0.3)
    # --- 5m ---
    ax = axes[2]
    m_start = int(np.searchsorted(t5, int(t15[r]), side="left"))
    m_end = min(len(t5) - 1, e["fill_idx"] + 15)
    candles(ax, t5, o5[m_start:m_end + 1], m_start, m_end)
    ax.axhline(entry, color="green", linestyle="-", linewidth=1)
    ax.axhline(stop, color="red", linestyle="-", linewidth=1)
    ax.axvline(e["e_idx"], color="purple", linestyle=":", linewidth=1.5)
    ax.axvline(e["fill_idx"], color="green", linestyle=":", linewidth=1.5)
    ax.set_title("5m: purple=E signal bar | green dotted=fill bar | "
                 "green=trigger/entry red=stop")
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(f"{OUT}/{tid}.png", dpi=100)
    plt.close(fig)
    print(f"chart {tid}.png", flush=True)
print("DONE charts", flush=True)
