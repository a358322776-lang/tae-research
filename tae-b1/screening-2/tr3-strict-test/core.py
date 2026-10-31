"""
core.py - Crypto multi-coin Donchian trend following
Shared by backtest and live signal generation. No look-ahead by construction:
signal computed on CLOSED daily bars, executed on the NEXT bar.
"""
import numpy as np, pandas as pd

# ---------------- config ----------------
DEFAULT = dict(
    entry_n=20,        # breakout lookback (Donchian upper: highest CLOSE of last N bars)
    exit_n=10,         # trailing exit (lowest CLOSE of last M bars)
    slot=0.05,         # weight per open position (1/20 of equity)
    max_pos=20,        # max concurrent positions
    fee=0.0010,        # taker fee per side
    slip=0.0005,       # assumed slippage per side
)

def donchian_levels(close: pd.Series, entry_n: int, exit_n: int):
    """Upper/lower channel built ONLY from bars BEFORE the current one -> no look-ahead."""
    return close.rolling(entry_n).max().shift(1), close.rolling(exit_n).min().shift(1)

def signals_stateful(close: pd.Series, entry_n=20, exit_n=10):
    """State machine: flat -> long when close > upper; long -> flat when close < lower.
    Returns 0/1 position series aligned to close.index (state AFTER bar t's close)."""
    upper, lower = donchian_levels(close, entry_n, exit_n)
    c = close.values; u = upper.values; l = lower.values
    out = np.zeros(len(c)); st = 0
    for i in range(len(c)):
        if np.isnan(u[i]) or np.isnan(l[i]):
            out[i] = 0; st = 0; continue
        if st == 0 and c[i] > u[i]:
            st = 1
        elif st == 1 and c[i] < l[i]:
            st = 0
        out[i] = st
    return pd.Series(out, index=close.index, dtype=float), upper, lower

def book_weights(panel: pd.DataFrame, cfg=None):
    """panel: DataFrame of closes (columns = symbols, NaN where not listed).
    Returns weight matrix; each open position gets cfg['slot'], capped at max_pos names."""
    cfg = {**DEFAULT, **(cfg or {})}
    N = panel.shape[1]; T = panel.shape[0]
    W = np.zeros((T, N)); state = np.zeros(N, dtype=np.int8)
    A = panel.notna().values; C = panel.values.astype(float)
    up = pd.DataFrame(C).rolling(cfg["entry_n"]).max().shift(1).values
    dn = pd.DataFrame(C).rolling(cfg["exit_n"]).min().shift(1).values
    for t in range(T):
        live = []
        for j in range(N):
            if not A[t, j]:
                state[j] = 0; continue
            u, l = up[t, j], dn[t, j]
            if u != u or l != l: continue
            c = C[t, j]
            if state[j] == 0:
                if c > u: state[j] = 1
            elif c < l:
                state[j] = 0
            if state[j] == 1: live.append(j)
        if cfg["max_pos"]: live = live[:cfg["max_pos"]]
        for j in live: W[t, j] = cfg["slot"]
    return pd.DataFrame(W, index=panel.index, columns=panel.columns)

def run_backtest(panel: pd.DataFrame, cfg=None, cost=None):
    cfg = {**DEFAULT, **(cfg or {})}
    cost = cost if cost is not None else (cfg["fee"] + cfg["slip"])
    W = book_weights(panel, cfg)
    R = panel.pct_change().fillna(0.0).values
    We = np.vstack([np.zeros((1, W.shape[1])), W.values[:-1]])   # execute next bar
    gross = (We * R).sum(axis=1)
    turn = np.abs(We - np.vstack([np.zeros((1, W.shape[1])), We[:-1]])).sum(axis=1)
    net = gross - turn * cost
    eq = pd.Series(np.cumprod(1 + net), index=panel.index)
    return dict(equity=eq, net=net, weights=pd.DataFrame(We, index=panel.index, columns=panel.columns),
                turnover=turn, cost=cost)

def stats(eq: pd.Series, ppy=365):
    eq = eq.dropna()
    yrs = max((eq.index[-1] - eq.index[0]).days / 365.25, 0.05)
    tot = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (1 + tot) ** (1 / yrs) - 1
    r = eq.pct_change().dropna()
    mdd = (eq / eq.cummax() - 1).min()
    return dict(total=tot, cagr=cagr, mdd=mdd,
                sharpe=(r.mean() / r.std() * np.sqrt(ppy)) if r.std() > 0 else 0.0,
                calmar=(cagr / abs(mdd)) if mdd < 0 else float("nan"), years=yrs)

if __name__ == "__main__":
    import glob, os
    D = "D:/QuantLab/data"
    syms = sorted(os.path.basename(p).replace("_1d.csv", "") for p in glob.glob(D + "/*USDT_1d.csv"))
    panel = pd.DataFrame({s: pd.read_csv(D + "/" + s + "_1d.csv", parse_dates=["date"]).set_index("date").close
                          for s in syms}).sort_index()
    panel = panel[panel.index >= "2018-01-01"]
    r = run_backtest(panel, dict(slot=1.0/len(syms)))
    print("coins:", len(syms), "bars:", len(panel))
    print(stats(r["equity"]))