"""Driver for the ETH v4.1 robustness study.

Usage:
  python3 run_study.py --window insample --out /tmp/robustness-v41
  python3 run_study.py --window oos --out /tmp/robustness-v41

Reads <window>_{15m,1h,5m}.npz + funding_<window>.csv from --out (see
fetch_data.py), runs the frozen v4.1 paper engine, then applies the
audit's exec post-processing (T0/T1/T2 fills, executor exit correction,
fees, funding) and the Phase-2 stress tests. Writes:
  trades_<window>_paper.json  (paper trades, unified semantics)
  trades_<window>_exec.json   (per-trade exec records incl. all variants)
  stats_<window>.json         (headline stats, year/regime splits, stress)
"""
import argparse, csv, importlib.util, json, os, sys
import numpy as np
sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/hidden_files")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v41_engine as E
from datetime import datetime, timezone

HID = "/home/hatch/workspace/goals/100u-200u/hidden_files"
spec = importlib.util.spec_from_file_location("tf", f"{HID}/tae-scanner-tradfi.py")
tf = importlib.util.module_from_spec(spec); spec.loader.exec_module(tf)

def load(out, window):
    d = {}
    for iv in ("15m", "1h", "5m"):
        z = np.load(os.path.join(out, f"{window}_{iv}.npz"))
        d[iv] = (z["t"], z["ohlc"])
    fund = []
    with open(os.path.join(out, f"funding_{window}.csv")) as f:
        r = csv.DictReader(f)
        for row in r:
            fund.append((int(row["fundingTime"]), float(row["fundingRate"])))
    fund.sort()
    return d, fund

def regime_90d(c15, i):
    """Primary regime: 90-day return at signal bar (8640 15m bars).
    up > +15%, down < -15%, else range; None if not enough history."""
    if i < 8640:
        return None
    r = c15[i] / c15[i - 8640] - 1
    if r > 0.15:
        return "up"
    if r < -0.15:
        return "down"
    return "range"

def stats(rs):
    if not rs:
        return {"n": 0}
    rs = list(rs)
    wins = [r for r in rs if r > 0]
    eq, peak, dd = 0.0, 0.0, 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); dd = min(dd, eq - peak)
    return {"n": len(rs), "win_pct": round(100 * len(wins) / len(rs), 1),
            "mean": round(sum(rs) / len(rs), 4), "total": round(sum(rs), 2),
            "maxDD": round(dd, 2), "best": round(max(rs), 2),
            "worst": round(min(rs), 2),
            "tail_gt3": sum(1 for r in rs if r > 3)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", required=True, choices=["oos", "insample"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    d, fund = load(a.out, a.window)
    t15, o15 = d["15m"]; t1h, o1h = d["1h"]; t5, o5 = d["5m"]
    D = E.Data((t15, o15[:, 0], o15[:, 1], o15[:, 2], o15[:, 3]),
               (t1h, o1h[:, 0], o1h[:, 1], o1h[:, 2], o1h[:, 3]),
               (t5, o5[:, 0], o5[:, 1], o5[:, 2], o5[:, 3]))
    print(f"[{a.window}] bars 15m={len(t15)} 1h={len(t1h)} 5m={len(t5)}", flush=True)
    trades, skipped_lev, open_end = E.run_paper(D, tf._is_signal_bar)
    print(f"[{a.window}] paper trades={len(trades)} skipped_lev={skipped_lev} open_at_end={open_end}", flush=True)
    with open(os.path.join(a.out, f"trades_{a.window}_paper.json"), "w") as f:
        json.dump({"trades": trades, "skipped_lev": skipped_lev,
                   "open_at_end": open_end}, f, indent=1)

    # ---- exec post-processing ----
    exec_recs = []
    for tr in trades:
        rec = {"signal_time": datetime.fromtimestamp(tr["t"] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
               "signal_i": tr["i"], "dir": tr["dir"], "entry": tr["entry"],
               "sl": tr["sl"], "risk": tr["risk"],
               "stop_dist_pct": round(tr["risk"] / tr["entry"] * 100, 4),
               "level_line": tr["level_line"],
               "paper_exit_i": tr["exit_i"], "paper_exit_px": tr["exit_px"],
               "paper_reason": tr["reason"], "paper_r": round(tr["r"], 4),
               "year": datetime.fromtimestamp(tr["t"] / 1000, timezone.utc).year,
               "regime": regime_90d(D.c15, tr["i"]),
               "fills": {}}
        for fk in ("T0", "T1", "T2"):
            ex = E.exec_trade(D, tr, fk, fund)
            f = {"status": ex["status"]}
            if ex["status"] == "filled":
                f.update({"exit_i": ex["exit_i"], "exit_px": ex["exit_px"],
                          "reason": ex["reason"], "funding_r": round(ex["funding_r"], 4)})
                # base grid: stop-slip 0 / 0.05% / 0.1%, entry maker
                for s, sn in ((0.0, "s0"), (0.0005, "s005"), (0.001, "s01")):
                    g, fee = E.net_r(tr, ex["exit_px"], ex["reason"], stop_slip=s)
                    f[sn] = round(g - fee + ex["funding_r"], 4)
                # stress variants (on top of s0 unless noted)
                g, fee = E.net_r(tr, ex["exit_px"], ex["reason"], entry_fee=0.0005)
                f["entry_taker"] = round(g - fee + ex["funding_r"], 4)
                g, fee = E.net_r(tr, ex["exit_px"], ex["reason"], ema_slip=0.0005)
                f["ema_slip005"] = round(g - fee + ex["funding_r"], 4)
                g, fee = E.net_r(tr, ex["exit_px"], ex["reason"], ema_slip=0.001)
                f["ema_slip01"] = round(g - fee + ex["funding_r"], 4)
                g, fee = E.net_r(tr, ex["exit_px"], ex["reason"], stop_slip=0.001,
                                 ema_slip=0.001, entry_fee=0.0005)
                f["combined_conservative"] = round(g - fee + ex["funding_r"], 4)
                # EMA delay: exit at next bar open (EMA exits only)
                if ex["reason"] == "ema50_close" and ex["exit_i"] + 1 < len(D.t15):
                    g, fee = E.net_r(tr, float(D.o15[ex["exit_i"] + 1]), "ema50_close")
                    f["ema_next_open"] = round(g - fee + ex["funding_r"], 4)
                else:
                    f["ema_next_open"] = f["s0"]
            rec["fills"][fk] = f
        exec_recs.append(rec)
    with open(os.path.join(a.out, f"trades_{a.window}_exec.json"), "w") as f:
        json.dump(exec_recs, f, indent=1)

    # ---- headline stats ----
    out = {"window": a.window, "paper_n": len(trades),
           "skipped_lev": skipped_lev, "open_at_end": open_end}
    for fk in ("T0", "T1", "T2"):
        filled = [r for r in exec_recs if r["fills"][fk]["status"] == "filled"]
        missed = [r for r in exec_recs if r["fills"][fk]["status"] == "missed"]
        unres = [r for r in exec_recs if r["fills"][fk]["status"] == "unresolved"]
        out[fk] = {"filled": len(filled), "missed": len(missed),
                   "unresolved": len(unres),
                   "fill_rate_pct": round(100 * len(filled) / max(1, len(exec_recs)), 1)}
        for var in ("s0", "s005", "s01", "entry_taker", "ema_slip005",
                    "ema_slip01", "combined_conservative", "ema_next_open"):
            rs = [r["fills"][fk][var] for r in filled if var in r["fills"][fk]]
            st = stats(rs)
            # ex-max
            if rs:
                mx = max(rs)
                rs_ex = [x for x in rs if x != mx] if rs.count(mx) == 1 else rs
                st["ex_max_mean"] = round(sum(rs_ex) / len(rs_ex), 4) if rs_ex else None
                st["max_share_pct"] = round(100 * mx / sum(rs), 1) if sum(rs) != 0 else None
            out[fk][var] = st
        # all-signal view (missed/unresolved = 0R)
        rs_all = [r["fills"][fk].get("s0", 0.0) if r["fills"][fk]["status"] == "filled" else 0.0
                  for r in exec_recs]
        out[fk]["all_signal_s0"] = stats(rs_all)
    # year + regime splits (T0 s0 and T1 s0, filled only)
    for split, key in (("year", "year"), ("regime", "regime")):
        out[split] = {}
        groups = sorted({str(r[key]) for r in exec_recs})
        for g in groups:
            sub = [r for r in exec_recs if str(r[key]) == g]
            row = {"n_signals": len(sub)}
            for fk in ("T0", "T1", "T2"):
                rs = [r["fills"][fk]["s0"] for r in sub
                      if r["fills"][fk]["status"] == "filled"]
                row[fk] = stats(rs)
                row[fk]["fill_rate_pct"] = round(100 * len(rs) / len(sub), 1) if sub else 0
            out[split][g] = row
    with open(os.path.join(a.out, f"stats_{a.window}.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: out[k] for k in ("paper_n", "T0", "T1", "T2")},
                     indent=1)[:1500], flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
