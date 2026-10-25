"""TAE-B1 v0.1 执行：B/C 两组回测 + 统计 + 报告。

用法：python3 run_b1.py
前置：data_cache/stitched_*.npz 与 candidates.jsonl 已就绪（levels_pass.py）。
输出：trades_{b,c}_{oos,ins}.csv、stats_b1.json、report-b1-v0.1.md
"""
import csv
import json
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
from b1_engine import Data, run_group, trade_numbers, stats_for, COMBOS, BOUNDARY_MS  # noqa: E402

B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1"
ROB = "/home/hatch/workspace/goals/100u-200u/files/robustness-v41"


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M")


def main():
    D = Data()
    cand = {}
    with open(f"{B1}/data_cache/candidates.jsonl") as fh:
        for line in fh:
            try:
                c = json.loads(line)
            except Exception:
                continue
            cand.setdefault(c["j"], []).append((c["dir"], c["blo"], c["bhi"]))
    print(f"candidates bars: {len(cand)}, events: {sum(len(v) for v in cand.values())}")

    all_out = {}
    for grp, fix in (("B", False), ("C", True)):
        trades, counts, seq_counts = run_group(D, cand, fix)
        print(f"group {grp}: accepted={len(trades)} counts={counts}")
        # 逐笔 + 统计
        rows = {"oos": [], "ins": []}
        for e in trades:
            w = "oos" if e["fill_open_ms"] <= BOUNDARY_MS else "ins"
            nums = {}
            for combo in COMBOS:
                out = e["outs"][combo]
                nums[combo] = trade_numbers(D, e, out) if out is not None else None
            base = e["base"]
            row = {
                "seq_b0": iso(e["b0_open_ms"]), "window": w, "dir": e["dir"],
                "band_lo": e["blo"], "band_hi": e["bhi"],
                "touch_extreme": e["touch_extreme"],
                "reclaim": iso(int(D.t15[e["reclaim_idx"]]) + 900_000),
                "trigger": e["trigger"], "fill_time": iso(e["fill_close_ms"]),
                "entry": e["entry"], "stop": e["stop"], "risk_pts": e["risk"],
                "base_exit_time": iso(base["exit_close_ms"]),
                "base_exit_px": base["exit_px"], "base_reason": base["reason"],
            }
            for (t, x) in COMBOS:
                n = nums[(t, x)]
                row[f"net_{t}_{x}"] = n["net"] if n else ""
                row[f"reason_{t}_{x}"] = e["outs"][(t, x)]["reason"] if e["outs"][(t, x)] else "unresolved"
            bn = nums[("T0", "EMA50")]
            row["base_gross"] = bn["gross"]
            row["base_fee"] = bn["fee"]
            row["base_funding"] = bn["funding"]
            rows[w].append(row)
        stats = {}
        for w in ("oos", "ins"):
            stats[w] = {}
            for combo in COMBOS:
                nets, gross = [], []
                for e in trades:
                    if ("oos" if e["fill_open_ms"] <= BOUNDARY_MS else "ins") != w:
                        continue
                    out = e["outs"][combo]
                    if out is None:
                        continue
                    nn = trade_numbers(D, e, out)
                    nets.append(nn["net"])
                    gross.append(nn["gross"])
                s = stats_for(nets)
                s["avg_gross"] = float(np.mean(gross)) if gross else 0.0
                s["total_gross"] = float(sum(gross))
                stats[w][f"{combo[0]}_{combo[1]}"] = s
            # 逐年（基线 T0×EMA50）
            yearly = {}
            for e in trades:
                if ("oos" if e["fill_open_ms"] <= BOUNDARY_MS else "ins") != w:
                    continue
                out = e["outs"][("T0", "EMA50")]
                if out is None:
                    continue
                y = datetime.fromtimestamp(e["fill_open_ms"] / 1000, timezone.utc).year
                yearly.setdefault(y, []).append(trade_numbers(D, e, out)["net"])
            stats[w]["yearly_baseline"] = {
                str(y): {"n": len(v), "total_net": float(sum(v)),
                         "avg_net": float(np.mean(v))} for y, v in sorted(yearly.items())}
        all_out[grp] = {"counts": counts, "seq_counts": seq_counts, "stats": stats}
        for w in ("oos", "ins"):
            with open(f"{B1}/trades_{grp.lower()}_{w}.csv", "w", newline="") as fh:
                wr = csv.DictWriter(fh, fieldnames=list(rows[w][0].keys()) if rows[w] else [])
                wr.writeheader()
                wr.writerows(rows[w])
            print(f"  {grp}/{w}: {len(rows[w])} rows")
    with open(f"{B1}/stats_b1.json", "w") as fh:
        json.dump(all_out, fh, indent=1, ensure_ascii=False, default=float)
    print("stats written")


if __name__ == "__main__":
    main()
