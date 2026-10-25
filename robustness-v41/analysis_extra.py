"""Extra analysis for the robustness study (runs on exec JSON):
  * per-trade CSV export (in-sample and OOS, kept separate)
  * T0 fill-rate haircut stress (queue uncertainty): keep each T0-filled
    trade with p=0.9 / 0.8, seeds 1..5, report mean/range of net mean and
    net total (filled view and all-signal view where missed = 0R)
  * year / regime tables as CSV
Usage: python3 analysis_extra.py --exec-json X --out-dir Y
"""
import argparse, csv, json, os
import numpy as np

VARS = ("s0", "s005", "s01", "entry_taker", "ema_slip005", "ema_slip01",
        "combined_conservative", "ema_next_open")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exec-json", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    recs = json.load(open(a.exec_json))
    os.makedirs(a.out_dir, exist_ok=True)
    base = os.path.basename(a.exec_json).replace("trades_", "").replace("_exec.json", "")
    # ---- CSV ----
    with open(os.path.join(a.out_dir, f"trades_{base}.csv"), "w", newline="") as f:
        w = csv.writer(f)
        hdr = ["signal_time", "dir", "entry", "sl", "stop_dist_pct", "level_line",
               "year", "regime", "paper_exit_px", "paper_reason", "paper_r"]
        for fk in ("T0", "T1", "T2"):
            hdr += [f"{fk}_status", f"{fk}_exit_px", f"{fk}_reason", f"{fk}_funding_r"]
            hdr += [f"{fk}_{v}" for v in VARS]
        w.writerow(hdr)
        for r in recs:
            row = [r["signal_time"], r["dir"], r["entry"], r["sl"],
                   r["stop_dist_pct"], r["level_line"], r["year"], r["regime"],
                   r["paper_exit_px"], r["paper_reason"], r["paper_r"]]
            for fk in ("T0", "T1", "T2"):
                fl = r["fills"][fk]
                row += [fl["status"], fl.get("exit_px", ""), fl.get("reason", ""),
                        fl.get("funding_r", "")]
                row += [fl.get(v, "") for v in VARS]
            w.writerow(row)
    # ---- haircut ----
    filled = [r["fills"]["T0"]["s0"] for r in recs
              if r["fills"]["T0"]["status"] == "filled"]
    n_sig = len(recs)
    out = {"n_signals": n_sig, "n_t0_filled": len(filled)}
    for p in (0.9, 0.8):
        means, totals, all_totals = [], [], []
        for seed in range(1, 6):
            rng = np.random.default_rng(seed)
            keep = rng.random(len(filled)) < p
            kept = [x for x, k in zip(filled, keep) if k]
            means.append(float(np.mean(kept)) if kept else 0.0)
            totals.append(float(np.sum(kept)))
            all_totals.append(float(np.sum(kept)))  # missed/unresolved = 0R
        out[f"haircut_{int(p*100)}"] = {
            "mean_across_seeds": round(float(np.mean(means)), 4),
            "mean_range": [round(min(means), 4), round(max(means), 4)],
            "total_across_seeds": round(float(np.mean(totals)), 2),
            "total_range": [round(min(totals), 2), round(max(totals), 2)],
            "all_signal_total_across_seeds": round(float(np.mean(all_totals)), 2)}
    print(json.dumps(out, indent=1))
    with open(os.path.join(a.out_dir, f"haircut_{base}.json"), "w") as f:
        json.dump(out, f, indent=1)

if __name__ == "__main__":
    main()
