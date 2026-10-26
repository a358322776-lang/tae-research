"""Audit aggregation (read-only): summarize level_check.csv + exec_check.csv,
verify trend==dir, E-window coincident position, and tier details."""
import csv
import json
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1"

picked = json.load(open("/tmp/audit_picked.json"))
by_tid = {e["tid"]: e for e in picked}
lv = list(csv.DictReader(open(f"{B1}/audit-v0.1/level_check.csv")))
ex = list(csv.DictReader(open(f"{B1}/audit-v0.1/exec_check.csv")))

print("=== Task2 aggregates (n=30) ===")
print("real match:", sum(1 for r in lv if r["real_match"] == "True"),
      "inst match:", sum(1 for r in lv if r["inst_match"] == "True"))
touches = [int(r["level_touches"]) for r in lv]
print("touches: min", min(touches), "max", max(touches), "dist", dict(sorted(Counter(touches).items())))
ages = [int(r["last_touch_age_bars"]) for r in lv]
print("last_touch_age: median", float(np.median(ages)), "max", max(ages),
      ">80:", sum(1 for a in ages if a > 80), "==96:", sum(1 for a in ages if a == 96))
spans = [int(r["cluster_span_bars"]) for r in lv]
print("cluster_span: median", float(np.median(spans)), "max", max(spans))
widths = [float(r["band_width_atr"]) for r in lv]
print("width_atr: min", min(widths), "median", round(float(np.median(widths)), 4),
      "max", max(widths))
print("width <0.25 ATR:", [r["trade_id"] for r in lv if float(r["band_width_atr"]) < 0.25])
print("width >1.0 ATR:", [r["trade_id"] for r in lv if float(r["band_width_atr"]) > 1.0])
depths = [float(r["pullback_depth_atr"]) for r in lv]
print("pullback depth ATR: <0.1:", sum(1 for d in depths if d < 0.1),
      [r["trade_id"] for r in lv if float(r["pullback_depth_atr"]) < 0.1],
      "median", round(float(np.median(depths)), 4), "max", round(max(depths), 4))
print("beyond far edge (>0):", sum(1 for r in lv if float(r["beyond_band_atr"]) > 0),
      [r["trade_id"] for r in lv if float(r["beyond_band_atr"]) > 0])
print("extreme inside band:", sum(1 for r in lv if r["extreme_inside_band"] == "True"))
print("trend==dir:", sum(1 for r in lv if r["trend_1h_at_b0"] == by_tid[r["trade_id"]]["dir"]),
      "/30; mismatches:", [r["trade_id"] for r in lv
                           if r["trend_1h_at_b0"] != by_tid[r["trade_id"]]["dir"]])
print("first_touch offsets:", dict(sorted(Counter(r["first_touch_bar_offset"] for r in lv).items())))
print("n_touch_bars dist:", dict(sorted(Counter(r["n_touch_bars"] for r in lv).items())))

print()
print("=== Task3 aggregates (n=30) ===")
print("base reasons:", dict(Counter(r["base_reason"] for r in ex)))
print("breach in fill 5m bar:", sum(1 for r in ex if r["breach_in_fill_5m_bar"] == "True"))
print("breach in later 5m of fill 15m:", sum(1 for r in ex if r["breach_in_later_5m_of_fill_15m"] == "True"))
stops = [r for r in ex if r["base_reason"] == "stop"]
print("stop exits:", len(stops), "ema_cross_in_stop_exit_bar:",
      sum(1 for r in stops if r["ema_cross_in_stop_exit_bar"] == "True"),
      [r["trade_id"] for r in stops if r["ema_cross_in_stop_exit_bar"] == "True"])
print("T0 px match (stop trades):", sum(1 for r in stops if r["T0_px_match_csv"] == "True"),
      "/", len(stops))
print("T1 reasons:", dict(Counter(r["T1_reason"] for r in ex)))
print("T2 reasons:", dict(Counter(r["T2_reason"] for r in ex)))
print("T2 fill better than trigger (all rows, structural):",
      sum(1 for r in ex if r["T2_fill_better_than_trigger"] == "True"), "/30")
t2_stop = [r for r in ex if r["T2_reason"] == "stop"]
print("T2 stop exits in sample:", len(t2_stop))
emas = [r for r in ex if r["base_reason"] == "EMA50"]
deltas = [float(r["ema_next_open_delta_R"]) for r in emas if r["ema_next_open_delta_R"] != ""]
print(f"EMA exits: {len(emas)}, next-open deltas: n={len(deltas)} mean={np.mean(deltas):.4f} "
      f"sum={sum(deltas):.4f} pos={sum(1 for d in deltas if d > 0)} neg={sum(1 for d in deltas if d < 0)} "
      f"min={min(deltas):.4f} max={max(deltas):.4f}")
print("fee match:", sum(1 for r in ex if r["fee_match"] == "True"), "/30",
      "funding match:", sum(1 for r in ex if r["funding_match"] == "True"), "/30")
print("funding settlement on fill_open:", sum(1 for r in ex if r["funding_settlement_on_fill_open"] == "True"),
      "on exit_close:", sum(1 for r in ex if r["funding_settlement_on_exit_close"] == "True"))

print()
print("=== E-window coincident check ===")
# m0 = first 5m bar of 15m bar r+1; E position k = e_idx - m0
from b1_engine import Data  # noqa
D = Data()
t15, t5 = D.t15, D.t5
for e in picked:
    r = e["reclaim_idx"]
    m0 = int(np.searchsorted(t5, int(t15[r]) + 900_000, side="left"))
    k = e["e_idx"] - m0
    flag = " <-- k==2 coincident rule exercised" if k == 2 else ""
    print(f"{e['tid']} E position k={k}{flag}")
