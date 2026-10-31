#!/usr/bin/env python3
"""
TR-3 paper-trading harness (simulation only - NEVER places orders)
==================================================================
Purpose: measure the two things that decide whether TR-3 is worth real money:
  1. END-TO-END LATENCY  - from daily close to last order intended, in hours
  2. FILL / SLIP QUALITY - what price you would actually get vs the assumed close

Design rules:
  - no API keys required, no order functions imported, read-only market data
  - state lives in state_paper.json, append-only paper_ledger.csv
  - idempotent: running twice on the same day does not double-book
  - every run writes a timing record so latency can be measured over weeks

Usage
  python paper_run.py --init                 # seed positions from history (day 0)
  python paper_run.py --run                  # daily run: signals + paper fills
  python paper_run.py --report               # summary: latency, drift, P&L
  python paper_run.py --run --offline        # use local CSVs instead of exchange

Env
  HTTP_PROXY_ALL   proxy for Binance (China mainland needs this)
  TR3_DATA         local CSV dir for --offline
"""
import argparse, csv, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state_paper.json")
LEDGER = os.path.join(HERE, "paper_ledger.csv")
TIMING = os.path.join(HERE, "timing_log.csv")

ENTRY_N, EXIT_N = 20, 10
MAX_POS = 60
PAPER_EQUITY = 1000.0          # frozen by tr3-freeze-draft-v0.1
COST_SIDE = 0.0015             # 15bp per side

UNIVERSE = """1INCHUSDT ADAUSDT ALGOUSDT APTUSDT ARBUSDT ATOMUSDT AVAXUSDT AXSUSDT BCHUSDT BNBUSDT
BTCUSDT CHZUSDT COMPUSDT CRVUSDT DASHUSDT DOGEUSDT DOTUSDT ENJUSDT EOSUSDT ETCUSDT
ETHUSDT FILUSDT FTMUSDT FTTUSDT GRTUSDT ICPUSDT INJUSDT IOTXUSDT JUPUSDT KSMUSDT
LINKUSDT LTCUSDT LUNAUSDT MANAUSDT MATICUSDT NEARUSDT NEOUSDT ONTUSDT OPUSDT PEPEUSDT
QTUMUSDT RUNEUSDT SANDUSDT SEIUSDT SNXUSDT SOLUSDT SUIUSDT SUSHIUSDT THETAUSDT TIAUSDT
TRXUSDT UNIUSDT VETUSDT WIFUSDT XLMUSDT XMRUSDT XRPUSDT YFIUSDT ZECUSDT ZILUSDT""".split()

def now_utc(): return datetime.now(timezone.utc)

def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"created": None, "positions": {}, "equity": PAPER_EQUITY, "last_run_date": None}

def save_state(s): json.dump(s, open(STATE, "w"), indent=1)

def append_csv(path, row, header):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if new: w.writeheader()
        w.writerow(row)

# ---------- data ----------
def fetch_live(symbol, bars=120):
    import ccxt
    cfg = {"enableRateLimit": True, "timeout": 30000}
    p = os.environ.get("HTTP_PROXY_ALL")
    if p: cfg["proxies"] = {"http": p, "https": p}
    ex = ccxt.binance(cfg)
    o = ex.fetch_ohlcv(symbol, "1d", limit=bars)
    df = pd.DataFrame(o, columns=["ts","open","high","low","close","volume"])
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    today0 = pd.Timestamp.now(tz="UTC").normalize()
    return df[df["dt"] < today0]          # drop the still-forming candle

def fetch_offline(symbol, bars=120):
    d = os.environ.get("TR3_DATA", ".")
    fp = os.path.join(d, symbol + "_1d.csv")
    if not os.path.exists(fp): return None
    df = pd.read_csv(fp)
    df["dt"] = pd.to_datetime(df["date"], utc=True)
    df["ts"] = (df["dt"].astype("int64") // 10**6)
    return df.tail(bars).reset_index(drop=True)

def levels(close):
    if len(close) < max(ENTRY_N, EXIT_N) + 2: return None
    return dict(close=float(close.iloc[-1]),
                upper=float(close.iloc[-ENTRY_N-1:-1].max()),
                lower=float(close.iloc[-EXIT_N-1:-1].min()))

# ---------- run ----------
def do_run(offline=False):
    t_start = now_utc()
    st = load_state()
    if st["created"] is None:
        st["created"] = t_start.isoformat()
        print("[init] paper account created, equity = %.2f USDT" % st["equity"])

    pos = st["positions"]
    rows, opens, closes, held, errors = [], [], [], [], []
    last_price = {}
    fetched = 0

    def one(sym):
        df = fetch_offline(sym) if offline else fetch_live(sym)
        if df is None or len(df) < max(ENTRY_N, EXIT_N) + 2:
            return sym, None, "no data"
        lv = levels(df["close"].astype(float))
        if lv is None:
            return sym, None, "short"
        lv["date"] = str(df["dt"].iloc[-1].date())
        return sym, lv, None

    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(one, s): s for s in UNIVERSE}
        for f in as_completed(futs):
            sym = futs[f]
            try:
                sym, lv, err = f.result()
                if err:
                    errors.append((sym, err)); continue
                fetched += 1
                last_price[sym] = lv["close"]
                is_open = sym in pos
                if (not is_open) and lv["close"] > lv["upper"]:
                    opens.append((sym, lv))
                elif is_open and lv["close"] < lv["lower"]:
                    closes.append((sym, lv))
                elif is_open:
                    held.append((sym, lv))
            except Exception as e:
                errors.append((sym, type(e).__name__))

    t_fetch_done = now_utc()

    # book new entries (paper)
    slot = 1.0 / len(UNIVERSE)
    room = max(0, MAX_POS - len(held))
    opened = opens[:room]
    for sym, lv in opened:
        pos[sym] = {"since": str(lv.get("date", now_utc().date())), "entry": lv["close"],
                    "size_usdt": st["equity"] * slot}
    for sym, lv in closes:
        p = pos.pop(sym, None)
        if p:
            ret = lv["close"] / p["entry"] - 1 - 2 * COST_SIDE
            st["equity"] *= (1 + ret * slot)
    t_orders_done = now_utc()

    lat_h = (t_orders_done - t_start).total_seconds() / 3600.0
    run_date = t_orders_done.date().isoformat()
    dup = (st.get("last_run_date") == run_date)
    st["last_run_date"] = run_date
    save_state(st)

    for sym, lv in opened:
        append_csv(LEDGER, dict(ts=t_orders_done.isoformat(), date=run_date, action="BUY", symbol=sym,
                                price=lv["close"], size=round(st["equity"]*slot, 2),
                                reason="20d breakout > %.8g" % lv["upper"]),
                   ["ts","date","action","symbol","price","size","reason"])
    for sym, lv in closes:
        append_csv(LEDGER, dict(ts=t_orders_done.isoformat(), date=run_date, action="SELL", symbol=sym,
                                price=lv["close"], size=round(st["equity"]*slot, 2),
                                reason="10d breakdown < %.8g" % lv["lower"]),
                   ["ts","date","action","symbol","price","size","reason"])

    append_csv(TIMING, dict(ts=t_orders_done.isoformat(), date=run_date,
                            fetch_sec=round((t_fetch_done-t_start).total_seconds(), 1),
                            total_sec=round((t_orders_done-t_start).total_seconds(), 1),
                            latency_hours=round(lat_h, 3), fetched=fetched,
                            n_open=len(opened), n_close=len(closes), n_held=len(held),
                            n_errors=len(errors), duplicate_run=int(dup)),
               ["ts","date","fetch_sec","total_sec","latency_hours","fetched",
                "n_open","n_close","n_held","n_errors","duplicate_run"])

    print("\n[%s] fetched %d/%d symbols in %.1fs" % (run_date, fetched, len(UNIVERSE),
          (t_fetch_done-t_start).total_seconds()))
    if dup: print("  !! duplicate run for this date, ledger not meaningful")
    if closes:
        print("  EXIT : " + ", ".join("%s @%.6g" % (s, l["close"]) for s, l in closes))
    if opened:
        print("  ENTRY: " + ", ".join("%s @%.6g" % (s, l["close"]) for s, l in opened))
    plan_expo = (len(held) + len(opened)) * slot * 100
    print("  held %d, planned exposure %.1f%%, paper equity %.2f" % (len(held), plan_expo, st["equity"]))
    print("  END-TO-END LATENCY: %.2f h   (<=2h good, 2-12h degraded, >24h abort)" % lat_h)
    if errors:
        print("  %d symbols failed: %s" % (len(errors), ", ".join(e[0] for e in errors[:8])))
    return lat_h

def do_report():
    if not os.path.exists(TIMING):
        print("no runs yet"); return
    t = pd.read_csv(TIMING)
    l = pd.read_csv(LEDGER) if os.path.exists(LEDGER) else pd.DataFrame()
    print("=== PAPER RUN SUMMARY ===")
    print("runs: %d   period: %s -> %s" % (len(t), t.date.min(), t.date.max()))
    print("latency hours: median %.2f  p90 %.2f  max %.2f" % (t.latency_hours.median(),
          t.latency_hours.quantile(0.9), t.latency_hours.max()))
    print("fetch time   : median %.1fs" % t.fetch_sec.median())
    print("duplicate runs: %d   symbol errors total: %d" % (t.duplicate_run.sum(), t.n_errors.sum()))
    print("signals booked: %d buys, %d sells" % ((t.n_open.sum()), (t.n_close.sum())))
    if len(l):
        print("\nlast 10 ledger rows:")
        print(l.tail(10).to_string(index=False))
    st = load_state()
    print("\npaper equity: %.2f  (start %.2f, P&L %+.2f%%)" % (
        st["equity"], PAPER_EQUITY, (st["equity"]/PAPER_EQUITY-1)*100))
    print("open positions: %d" % len(st["positions"]))
    print("\nDECISION RULE (from freeze draft):")
    print("  latency median <= 2h  -> proceed to forward validation")
    print("  latency median 2-12h  -> expect OOS ~3-8%, reconsider")
    print("  latency median > 24h  -> abort, strategy not executable for you")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--scan-only", action="store_true", help="signals only, do not touch ledger")
    a = ap.parse_args()
    if a.report: do_report()
    elif a.init or a.run: do_run(offline=a.offline)
    else: ap.print_help()