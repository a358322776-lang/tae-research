"""Audit step 1 (read-only): reproduce B-group engine output from candidates.jsonl,
verify against trades_b_oos.csv, dump full entry dicts for the audit."""
import json
import sys

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
from b1_engine import Data, run_group, trade_numbers, BOUNDARY_MS  # noqa: E402

B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1"

D = Data()
cand = {}
with open(f"{B1}/data_cache/candidates.jsonl") as fh:
    for line in fh:
        try:
            c = json.loads(line)
        except Exception:
            continue
        cand.setdefault(c["j"], []).append((c["dir"], c["blo"], c["bhi"]))
print(f"candidates bars: {len(cand)}, events: {sum(len(v) for v in cand.values())}", flush=True)
trades, counts, seq_counts = run_group(D, cand, False)
print(f"accepted={len(trades)} counts={counts}", flush=True)

# OOS subset (fill open <= boundary)
oos = [e for e in trades if e["fill_open_ms"] <= BOUNDARY_MS]
print(f"oos={len(oos)} ins={len(trades) - len(oos)}", flush=True)

# Verify against CSV
import csv
rows = list(csv.DictReader(open(f"{B1}/trades_b_oos.csv")))
assert len(rows) == len(oos) == 123, (len(rows), len(oos))
oos_sorted = sorted(oos, key=lambda e: e["fill_close_ms"])
mism = 0
for e, r in zip(oos_sorted, rows):
    bn = trade_numbers(D, e, e["outs"][("T0", "EMA50")])
    for key, ev, rv in [
        ("entry", e["entry"], float(r["entry"])),
        ("stop", e["stop"], float(r["stop"])),
        ("blo", e["blo"], float(r["band_lo"])),
        ("bhi", e["bhi"], float(r["band_hi"])),
        ("net_T0_EMA50", bn["net"], float(r["net_T0_EMA50"])),
        ("base_exit_px", e["base"]["exit_px"], float(r["base_exit_px"])),
    ]:
        if abs(ev - rv) > 1e-9:
            mism += 1
            print(f"MISMATCH fill={r['fill_time']} {key}: engine={ev} csv={rv}")
print(f"csv mismatches: {mism}", flush=True)

# Dump entry dicts (JSON-serializable subset + all outs)
out = []
for e in oos_sorted:
    d = {k: v for k, v in e.items() if k not in ("outs", "base")}
    d["outs"] = {f"{t}_{x}": o for (t, x), o in e["outs"].items()}
    d["base"] = e["base"]
    out.append(d)
with open("/tmp/audit_b_oos_entries.json", "w") as fh:
    json.dump(out, fh)
print("dumped /tmp/audit_b_oos_entries.json", flush=True)
