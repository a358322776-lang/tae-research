"""
TR-3 strict review — TAE-grade checks applied to "60-coin Donchian 20/10".
=========================================================================
PRE-REGISTERED DECISION RULES (written BEFORE running, will not be changed after):
  K1  OOS(2022-01-01 onward) annualised return after 15bp cost <= 0          -> ELIMINATE
  K2  OOS annualised <= same-basket equal-weight buy&hold (cost-adjusted)    -> ELIMINATE
  K3  measured cost >= 50% of gross return                                   -> ELIMINATE
  K4  bootstrap 95% CI of OOS mean daily return contains 0 (P(mean<=0)>=5%)  -> NO EDGE
  K5  real strategy's annualised/Sharpe not above the 90th percentile of     -> NO EDGE
      200 time-shift placebo runs
  K6  OOS max drawdown worse than -50%                                       -> ELIMINATE
Final grade:
  A = passes K1..K6  (worth forward validation)
  B = survives bootstrap but fails placebo / benchmark  (inconclusive)
  C = fails any ELIMINATE rule  (shelve)
Also reported honestly: this test has NO true out-of-sample - the 20/10 params
and the 60-coin universe were both chosen AFTER seeing 2018-2026 results.
FROZEN: universe / data window / timing / cost model / statistic unit below.
"""
import pandas as pd, numpy as np, glob, os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import run_backtest, stats, book_weights

SEED = 20261031
rng_global = np.random.default_rng(SEED)
D = os.environ.get("TR3_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))

# ---------- FROZEN SPEC ----------
SPEC = dict(
    universe="60 Binance USDT spot pairs; delisted/renamed coins truncated at last trading day",
    data="Binance daily klines, 2018-01-01 .. 2026-10-30, close only",
    timing="signal on close of day T, executed at close of day T+1 (weights shifted 1 bar)",
    sizing="1/60 equity per open position, max 60 concurrent, long only spot, no leverage, no funding",
    cost_tiers={"low_6bp":0.0006, "base_15bp":0.0015, "high_30bp":0.0030, "extreme_50bp":0.0050},
    benchmark="equal-weight buy&hold of the same 62 symbols (one entry cost), plus BTC buy&hold",
    stat_unit="portfolio-day",
    oos_start="2022-01-01",
    is_window="2018-01-01..2021-12-31",
)
print("=== FROZEN SPEC ===")
for k, v in SPEC.items(): print("  %-12s %s" % (k, v))

def load(s):
    d = pd.read_csv(os.path.join(D, s + "_1d.csv"))
    d["date"] = pd.to_datetime(d["date"])
    return d.set_index("date").sort_index().close.astype(float)

syms = sorted(os.path.basename(p).replace("_1d.csv", "") for p in glob.glob(D + "/*USDT_1d.csv"))
panel = pd.DataFrame({s: load(s) for s in syms}).sort_index()
panel = panel[panel.index >= "2018-01-01"]
NC = panel.shape[1]; T = len(panel); dates = panel.index
print("\npanel: %d symbols, %d days, %s -> %s" % (NC, T, dates[0].date(), dates[-1].date()))
alive_last = panel.iloc[-1].notna().sum()
print("symbols with data on last day: %d / %d  (the 5-gap: delisted/truncated coins)" % (alive_last, NC))
dead = [c for c in panel.columns if panel[c].dropna().index.max() < pd.Timestamp("2026-06-01")]
print("  truncated/delisted:", ", ".join("%s(->%s)" % (c, panel[c].dropna().index.max().date()) for c in dead))

CFG = dict(entry_n=20, exit_n=10, slot=1.0/NC, max_pos=60)
R = panel.pct_change().fillna(0.0).values
R = np.nan_to_num(R, nan=0.0, posinf=0.0, neginf=0.0)

def equity_from_weights(W, cost, lag=1):
    """lag=1: signal on close T, fill at close T+1.  lag=2: one extra day of delay."""
    We = np.vstack([np.zeros((lag, NC)), W[:-lag]])
    gross = (We * R).sum(axis=1)
    turn = np.abs(We - np.vstack([np.zeros((1, NC)), We[:-1]])).sum(axis=1)
    net = gross - turn * cost
    return pd.Series(np.cumprod(1 + net), index=dates), pd.Series(gross, index=dates), pd.Series(net, index=dates), turn

W = book_weights(panel, CFG).values          # target weights (NOT yet shifted)
eq15, gross, net15, turn = equity_from_weights(W, 0.0015, lag=1)
eq_lag2, *_ = equity_from_weights(W, 0.0015, lag=2)

# ---------- benchmarks ----------
ew = (panel.notna().astype(float)).div(panel.notna().sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0).values
eq_ew, *_ = equity_from_weights(ew, 0.0015)
btcW = np.zeros((T, NC)); btcW[:, list(panel.columns).index("BTCUSDT")] = 1.0
eq_btc, *_ = equity_from_weights(btcW, 0.0015)

def window(eq, a, b):
    x = eq[(eq.index >= a) & (eq.index <= b)]
    return x / x.iloc[0]

print("\n=== 1. BASELINE + BENCHMARKS (15bp) ===")
for nm, e in [("TR-3 (Donchian 20/10)", eq15), ("EW basket buy&hold", eq_ew), ("BTC buy&hold", eq_btc)]:
    s = stats(e); soi = stats(window(e, *SPEC["is_window"].split("..")))
    soo = stats(window(e, SPEC["oos_start"], "2026-10-30"))
    print("  %-24s FULL cagr=%6.1f%% mdd=%6.1f%% sh=%.2f | IS cagr=%6.1f%% | OOS cagr=%6.1f%% mdd=%6.1f%% sh=%.2f"
          % (nm, s["cagr"]*100, s["mdd"]*100, s["sharpe"], soi["cagr"]*100, soo["cagr"]*100, soo["mdd"]*100, soo["sharpe"]))

print("\n=== 2. COST TIERS (full / OOS) ===")
for lab, c in SPEC["cost_tiers"].items():
    e, g, n, _ = equity_from_weights(W, c)
    s = stats(e); so = stats(window(e, SPEC["oos_start"], "2026-10-30"))
    print("  %-12s FULL cagr=%6.1f%% sh=%.2f | OOS cagr=%6.1f%% sh=%.2f" % (lab, s["cagr"]*100, s["sharpe"], so["cagr"]*100, so["sharpe"]))

print("\n=== 2b. EXECUTION-LAG SENSITIVITY (how fragile is the edge?) ===")
for lag in (1, 2, 3):
    e, *_ = equity_from_weights(W, 0.0015, lag=lag)
    sf = stats(e); so = stats(window(e, SPEC["oos_start"], "2026-10-30"))
    print("  lag=%d day(s)  FULL cagr=%6.1f%%  OOS cagr=%6.1f%%  OOS sharpe=%.2f  OOS mdd=%6.1f%%"
          % (lag, sf["cagr"]*100, so["cagr"]*100, so["sharpe"], so["mdd"]*100))

# K3: cost share of gross
gross_total = (1 + gross).prod() - 1
net_total = (1 + net15).prod() - 1
cost_share = (gross_total - net_total) / gross_total if gross_total > 0 else float("nan")
print("  K3 cost share of gross return: %.1f%%  (gross %.1fx -> net %.1fx)" % (cost_share*100, 1+gross_total, 1+net_total))

# ---------- K4: bootstrap on OOS portfolio-day returns ----------
print("\n=== 3. BOOTSTRAP (K4): 20000x, IID + block 3/5/10/20, OOS 2022-01-01.. ===")
oos_net = net15[net15.index >= SPEC["oos_start"]].values
oos_net_exmax = oos_net.copy(); oos_net_exmax[np.argmax(oos_net_exmax)] = 0.0
NB = 20000
rows = []
for lab, arr in [("incl max", oos_net), ("excl max", oos_net_exmax)]:
    idx = rng_global.integers(0, len(arr), size=(NB, len(arr)))
    means = arr[idx].mean(axis=1)
    ci = np.percentile(means, [2.5, 97.5]); pneg = float((means <= 0).mean())
    rows.append((lab, "IID", arr.mean(), ci, pneg))
    for L in (3, 5, 10, 20):
        nb = int(np.ceil(len(arr)/L)); starts = rng_global.integers(0, len(arr), size=(NB, nb))
        blocks = (starts[:, :, None] + np.arange(L)[None, None, :]) % len(arr)
        sample = arr[blocks].reshape(NB, -1)[:, :len(arr)]
        m = sample.mean(axis=1)
        ci = np.percentile(m, [2.5, 97.5]); pneg = float((m <= 0).mean())
        rows.append((lab, "block%d" % L, arr.mean(), ci, pneg))
print("  %-9s %-8s %9s %22s %10s" % ("case", "method", "mean", "95% CI", "P(mean<=0)"))
for r in rows:
    print("  %-9s %-8s %+9.5f  [%+8.5f, %+8.5f] %10.4f" % (r[0], r[1], r[2], r[3][0], r[3][1], r[4]))
k4_pass = all(r[4] < 0.05 for r in rows)
print("  K4 ->", "PASS (edge is statistically real)" if k4_pass else "FAIL (cannot reject zero edge)")

# ---------- K5: time-shift placebo ----------
print("\n=== 4. PLACEBO (K5): 200 time-shift runs (same hold-lengths, random start dates) ===")
segs = []
for j in range(NC):
    col = W[:, j] > 0
    d = np.diff(np.concatenate([[0], col.astype(int), [0]]))
    st = np.where(d == 1)[0]; en = np.where(d == -1)[0]
    segs.append(list(zip(st, en - st)))

rng2 = np.random.default_rng(SEED + 1)
pl_ann, pl_sh = [], []
for it in range(200):
    Wp = np.zeros((T, NC))
    for j, sg in enumerate(segs):
        for (s, L) in sg:
            if L >= T: continue
            ns = rng2.integers(0, T - L)
            Wp[ns:ns+L, j] = CFG["slot"]
    e, *_ = equity_from_weights(Wp, 0.0015)
    s = stats(e); pl_ann.append(s["cagr"]); pl_sh.append(s["sharpe"])
pl_ann = np.array(pl_ann); pl_sh = np.array(pl_sh)
real = stats(eq15)
pct_ann = float((pl_ann < real["cagr"]).mean()*100)
pct_sh = float((pl_sh < real["sharpe"]).mean()*100)
print("  placebo annualised: mean=%6.1f%% p50=%6.1f%% p90=%6.1f%% p99=%6.1f%% max=%6.1f%%"
      % (pl_ann.mean()*100, np.percentile(pl_ann,50)*100, np.percentile(pl_ann,90)*100, np.percentile(pl_ann,99)*100, pl_ann.max()*100))
print("  placebo sharpe    : mean=%6.2f  p50=%6.2f  p90=%6.2f  p99=%6.2f  max=%6.2f"
      % (pl_sh.mean(), np.percentile(pl_sh,50), np.percentile(pl_sh,90), np.percentile(pl_sh,99), pl_sh.max()))
print("  REAL: annualised=%6.1f%%  sharpe=%.2f" % (real["cagr"]*100, real["sharpe"]))
print("  percentile of real vs placebo: annualised %.1f%%  sharpe %.1f%%" % (pct_ann, pct_sh))
k5_pass = (pct_ann >= 90) and (pct_sh >= 90)
print("  K5 ->", "PASS" if k5_pass else "FAIL (indistinguishable from random timing)")

# ---------- K1/K2/K6 ----------
e_oos = window(eq15, SPEC["oos_start"], "2026-10-30")
s_oos = stats(e_oos); s_ew_oos = stats(window(eq_ew, SPEC["oos_start"], "2026-10-30"))
k1 = s_oos["cagr"] > 0
k2 = s_oos["cagr"] > s_ew_oos["cagr"]
k6 = s_oos["mdd"] > -0.50
print("\n=== 5. PRE-REGISTERED ELIMINATION RULES ===")
print("  K1 OOS cagr>0            : %6.2f%%  -> %s" % (s_oos["cagr"]*100, "PASS" if k1 else "FAIL"))
print("  K2 beat EW buy&hold      : %6.2f%% vs %6.2f%%  -> %s" % (s_oos["cagr"]*100, s_ew_oos["cagr"]*100, "PASS" if k2 else "FAIL"))
print("  K3 cost share <50%%       : %6.1f%%  -> %s" % (cost_share*100, "PASS" if cost_share < 0.5 else "FAIL"))
print("  K4 bootstrap CI excludes0: %s" % ("PASS" if k4_pass else "FAIL"))
print("  K5 placebo pct >= 90%%    : ann %.1f%% / sh %.1f%%  -> %s" % (pct_ann, pct_sh, "PASS" if k5_pass else "FAIL"))
print("  K6 OOS mdd > -50%%        : %6.1f%%  -> %s" % (s_oos["mdd"]*100, "PASS" if k6 else "FAIL"))

elim = [n for n, ok in [("K1",k1),("K2",k2),("K3",cost_share<0.5),("K6",k6)] if not ok]
noedge = [n for n, ok in [("K4",k4_pass),("K5",k5_pass)] if not ok]
grade = "A" if (not elim and not noedge) else ("C" if elim else "B")
print("\n=== 6. GRADE: %s ===" % grade)
print("  failed ELIMINATE: %s" % (", ".join(elim) if elim else "none"))
print("  failed EDGE     : %s" % (", ".join(noedge) if noedge else "none"))
print("\n  NOTE: no true OOS exists - 20/10 params and the 60-coin universe were both")
print("  chosen after seeing 2018-2026 results. Every number above is in-sample.")

json.dump(dict(grade=grade, failed_eliminate=elim, failed_edge=noedge,
               oos_cagr=s_oos["cagr"], oos_mdd=s_oos["mdd"], oos_sharpe=s_oos["sharpe"],
               ew_oos_cagr=s_ew_oos["cagr"], full_cagr=real["cagr"], full_sharpe=real["sharpe"],
               cost_share=cost_share, placebo_pct_ann=pct_ann, placebo_pct_sharpe=pct_sh,
               placebo_ann_p90=float(np.percentile(pl_ann,90)), k4_rows=[[r[0],r[1],float(r[2]),[float(r[3][0]),float(r[3][1])],float(r[4])] for r in rows],
               spec=SPEC, seed=SEED),
          open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json"), "w"), indent=2, default=str)
print("\nsaved -> <script_dir>/results.json")