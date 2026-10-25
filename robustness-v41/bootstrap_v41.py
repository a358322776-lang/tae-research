"""Bootstrap + concentration analysis for ETH v4.1 net-R series.

Reads trades_<window>_exec.json, extracts the filled net-R series for a
given fill model (T0/T1/T2) and variant (s0/s005/s01/...), and reports:
  * IID bootstrap (n=20000, seed 20261025): mean 95% CI, P(mean < 0)
  * same with the max trade removed
  * moving-block bootstrap (wrap-around) for block lengths 3/5/10/20
    (sensitivity: trades cluster in regimes, so IID overstates precision)
  * concentration: max share, top-5 share, trades needed for 50%/90% of
    total positive R, share of trades that are winners
Usage:
  python3 bootstrap_v41.py --exec-json trades_oos_exec.json --fill T0 --var s0
"""
import argparse, json, sys
import numpy as np

def iid_boot(x, n=20000, seed=20261025):
    rng = np.random.default_rng(seed)
    m = np.empty(n)
    for i in range(n):
        m[i] = rng.choice(x, size=len(x), replace=True).mean()
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)), \
        float(np.mean(m < 0)), float(m.mean()), float(m.std())

def block_boot(x, L, n=20000, seed=20261025):
    rng = np.random.default_rng(seed)
    N = len(x)
    ext = np.concatenate([x, x])  # wrap-around
    m = np.empty(n)
    nblocks = int(np.ceil(N / L))
    for i in range(n):
        starts = rng.integers(0, N, size=nblocks)
        sample = np.concatenate([ext[s:s + L] for s in starts])[:N]
        m[i] = sample.mean()
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)), \
        float(np.mean(m < 0)), float(m.mean()), float(m.std())

def concentration(x):
    x = np.asarray(x, dtype=float)
    pos = np.sort(x[x > 0])[::-1]
    tot = x.sum()
    out = {"n": int(len(x)), "mean": round(float(x.mean()), 4),
           "total": round(float(tot), 2),
           "max": round(float(x.max()), 2),
           "max_share_pct": round(100 * x.max() / tot, 1) if tot != 0 else None,
           "top5_share_pct": round(100 * pos[:5].sum() / tot, 1) if tot != 0 and len(pos) else None,
           "n_winners": int(len(pos)), "win_pct": round(100 * len(pos) / len(x), 1)}
    if len(pos):
        c = np.cumsum(pos)
        out["trades_for_50pct_pos"] = int(np.searchsorted(c, 0.5 * pos.sum()) + 1)
        out["trades_for_90pct_pos"] = int(np.searchsorted(c, 0.9 * pos.sum()) + 1)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exec-json", required=True)
    ap.add_argument("--fill", default="T0")
    ap.add_argument("--var", default="s0")
    a = ap.parse_args()
    recs = json.load(open(a.exec_json))
    x = [r["fills"][a.fill][a.var] for r in recs
         if r["fills"][a.fill]["status"] == "filled"]
    x = np.array(x, dtype=float)
    print(f"series: n={len(x)} fill={a.fill} var={a.var}")
    out = {"n": len(x), "concentration": concentration(x)}
    lo, hi, pneg, mmean, mstd = iid_boot(x)
    out["iid"] = {"ci95": [round(lo, 4), round(hi, 4)], "p_neg": round(pneg, 4),
                  "boot_mean": round(mmean, 4), "boot_sd": round(mstd, 4)}
    # ex-max
    j = int(np.argmax(x))
    xe = np.delete(x, j)
    lo, hi, pneg, mmean, mstd = iid_boot(xe)
    out["iid_ex_max"] = {"ci95": [round(lo, 4), round(hi, 4)], "p_neg": round(pneg, 4),
                         "boot_mean": round(mmean, 4), "boot_sd": round(mstd, 4),
                         "ex_max_mean": round(float(xe.mean()), 4)}
    out["blocks"] = {}
    for L in (3, 5, 10, 20):
        lo, hi, pneg, mmean, mstd = block_boot(x, L)
        out["blocks"][L] = {"ci95": [round(lo, 4), round(hi, 4)],
                            "p_neg": round(pneg, 4), "boot_mean": round(mmean, 4)}
        lo, hi, pneg, mmean, mstd = block_boot(xe, L)
        out["blocks"][L]["ex_max"] = {"ci95": [round(lo, 4), round(hi, 4)],
                                      "p_neg": round(pneg, 4)}
    print(json.dumps(out, indent=1))
    with open(a.exec_json.replace("trades_", "bootstrap_").replace("_exec.json", f"_{a.fill}_{a.var}.json"), "w") as f:
        json.dump(out, f, indent=1)

if __name__ == "__main__":
    main()
