#!/usr/bin/env python3
"""Round-2 feasibility data check (NO backtests, NO P&L, NO trades).
Fetches public data via the www.binance.com fapi mirror (same source as the
forward observer and the M1/M3 rounds):
- klines (30m, 1h) for ETHUSDT, BTCUSDT, XAUUSDT, QQQUSDT: full-history walk
  (earliest/latest/total/gaps) + trailing-730d bars retained for ATR medians
  and no-P&L event counts.
- fundingRate full history per symbol.
- exchangeInfo filters for the 4 symbols.
Outputs measurements.json into the feasibility dir and prints a summary.
Counting conventions (a priori round values, NOT optimized):
- ATR(14) = 14-bar rolling mean of True Range; ATR% = ATR/close*100.
- D2 leader-breakout event (count only): 1h close beyond prior 20-bar high/low.
- D3 session drive (count only): 1h bars opening 14:00-20:00 UTC; drive =
  (close of 16:00 bar - open of 14:00 bar)/open; clear if |drive| >= 1h ATR%
  median. QQQ/XAU sessions counted on weekdays only (weekend bars excluded).
- D1 funding extreme (count only): |fundingRate| >= 0.05% per 8h print.
On HTTP 429/418 the run stops globally (hard stop) and saves partial results.
"""
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

BASE = "https://www.binance.com/fapi/v1"
SYMBOLS = ["ETHUSDT", "BTCUSDT", "XAUUSDT", "QQQUSDT"]
INTERVALS = {"30m": 30 * 60 * 1000, "1h": 60 * 60 * 1000}
OUT_DIR = os.path.expanduser(
    "~/workspace/goals/100u-200u/files/tae-b1/active-strategies/feasibility")
STOP = threading.Event()


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def http_get(path, params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}{path}?{qs}"
    for attempt in range(4):
        if STOP.is_set():
            raise RuntimeError("stopped (rate-limit flag set)")
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0",
                          "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 418):
                STOP.set()
                raise RuntimeError(f"HTTP {e.code} rate limit on {path}")
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except Exception:
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def fetch_klines(symbol, interval):
    step = INTERVALS[interval]
    now_ms = int(time.time() * 1000)
    cutoff = now_ms - 730 * 24 * 3600 * 1000
    bars = []  # retained trailing-730d closed bars: (ot, o, h, l, c)
    total = 0
    gaps = 0
    gap_events = []
    earliest = None
    latest = None
    prev_open = None
    start = 0
    pages = 0
    while pages < 400:
        if STOP.is_set():
            break
        page = http_get("/klines", {"symbol": symbol, "interval": interval,
                                    "startTime": start, "limit": 1500})
        pages += 1
        if isinstance(page, dict):
            return {"symbol": symbol, "interval": interval,
                    "error": f"API error {page.get('code')}: {page.get('msg')}"}
        if not page:
            break
        closed = []
        saw_unclosed = False
        for b in page:
            if int(b[6]) <= now_ms:
                closed.append(b)
            else:
                saw_unclosed = True
        for b in closed:
            ot = int(b[0])
            if earliest is None:
                earliest = ot
            latest = ot
            if prev_open is not None:
                exp = prev_open + step
                if ot != exp:
                    miss = (ot - exp) // step
                    gaps += max(miss, 0)
                    if len(gap_events) < 20:
                        gap_events.append({"from": iso(exp), "to": iso(ot),
                                           "missing": miss})
            prev_open = ot
            total += 1
            if ot >= cutoff:
                bars.append((ot, float(b[1]), float(b[2]),
                             float(b[3]), float(b[4])))
        if saw_unclosed or len(page) < 1500:
            break
        start = int(page[-1][0]) + step
    # --- analysis on retained bars (no P&L anywhere) ---
    out = {"symbol": symbol, "interval": interval, "pages": pages,
           "earliest": iso(earliest) if earliest else None,
           "latest_closed": iso(latest) if latest else None,
           "total_bars": total, "gap_missing_bars": gaps,
           "gap_events": gap_events, "retained_bars": len(bars)}
    if not bars:
        return out
    # ATR(14)% series aligned to bars
    trs = []
    for i in range(1, len(bars)):
        o, h, l, c = bars[i][1], bars[i][2], bars[i][3], bars[i][4]
        pc = bars[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atrp = []  # (ot, atrpct)
    for i in range(13, len(trs)):
        atr = sum(trs[i - 13:i + 1]) / 14
        atrp.append((bars[i + 1][0], atr / bars[i + 1][4] * 100))
    y365 = now_ms - 365 * 24 * 3600 * 1000
    vals365 = [v for (ot, v) in atrp if ot >= y365]
    out["atr_pct_median_365d"] = statistics.median(vals365) if vals365 else None
    out["atr_pct_median_all_retained"] = (
        statistics.median([v for (_, v) in atrp]) if atrp else None)
    if interval == "1h":
        # D2 leader-breakout event counts (count only), trailing 365d
        win = [(ot, o, h, l, c) for (ot, o, h, l, c) in bars if ot >= y365]
        # need 20 prior bars: use retained series with index lookup
        idx = {ot: k for k, (ot, _, _, _, _) in enumerate(bars)}
        up = down = 0
        for (ot, o, h, l, c) in win:
            k = idx[ot]
            if k < 20:
                continue
            prior = bars[k - 20:k]
            if c > max(p[2] for p in prior):
                up += 1
            elif c < min(p[3] for p in prior):
                down += 1
        out["breakout_events_365d"] = {"up": up, "down": down,
                                       "total": up + down}
        # D3 session-drive counts (count only)
        med = out["atr_pct_median_365d"]
        by_day = {}
        for (ot, o, h, l, c) in bars:
            if ot < y365:
                continue
            dt = datetime.fromtimestamp(ot / 1000, tz=timezone.utc)
            by_day.setdefault((dt.year, dt.month, dt.day, dt.weekday()),
                              {})[dt.hour] = (o, c)
        crypto = symbol in ("ETHUSDT", "BTCUSDT")
        sessions = clear = 0
        for (y, m, d, wd), hrs in by_day.items():
            if not crypto and wd >= 5:
                continue
            if not all(h in hrs for h in (14, 15, 16, 17, 18, 19, 20)):
                continue
            sessions += 1
            drive = (hrs[16][1] - hrs[14][0]) / hrs[14][0] * 100
            if med and abs(drive) >= med:
                clear += 1
        out["session_stats_365d"] = {
            "sessions": sessions, "clear_drive_sessions": clear,
            "clear_share_pct": (100.0 * clear / sessions) if sessions else None,
            "note": "sessions counted on weekdays only for XAU/QQQ; "
                    "all days for ETH/BTC. Drive = 16:00 close vs 14:00 open."}
        # weekend flat bars (QQQ/XAU data-quality check)
        wk = [(o, h, l, c) for (ot, o, h, l, c) in bars
              if datetime.fromtimestamp(ot / 1000,
                                        tz=timezone.utc).weekday() >= 5]
        if wk:
            flat = sum(1 for (_, h, l, _) in wk if h == l)
            out["weekend_flat_pct_1h"] = 100.0 * flat / len(wk)
            out["weekend_bars_1h"] = len(wk)
    return out


def fetch_funding(symbol):
    recs = []
    start = 0
    pages = 0
    while pages < 60:
        if STOP.is_set():
            break
        page = http_get("/fundingRate", {"symbol": symbol,
                                         "startTime": start, "limit": 1000})
        pages += 1
        if isinstance(page, dict):
            return {"symbol": symbol,
                    "error": f"API error {page.get('code')}: {page.get('msg')}"}
        if not page:
            break
        for r in page:
            recs.append((int(r["fundingTime"]), float(r["fundingRate"])))
        if len(page) < 1000:
            break
        start = int(page[-1]["fundingTime"]) + 1
    if not recs:
        return {"symbol": symbol, "count": 0, "note": "no funding records"}
    now_ms = int(time.time() * 1000)
    y365 = now_ms - 365 * 24 * 3600 * 1000
    rates = [r for (_, r) in recs]
    rec365 = [r for (t, r) in recs if t >= y365]
    return {"symbol": symbol, "count": len(recs),
            "earliest": iso(recs[0][0]), "latest": iso(recs[-1][0]),
            "mean_pct": statistics.mean(rates) * 100,
            "median_pct": statistics.median(rates) * 100,
            "abs_mean_pct": statistics.mean([abs(r) for r in rates]) * 100,
            "extreme_pos_365d": sum(1 for r in rec365 if r >= 0.0005),
            "extreme_neg_365d": sum(1 for r in rec365 if r <= -0.0005),
            "extreme_total_365d": sum(1 for r in rec365
                                       if abs(r) >= 0.0005),
            "records_365d": len(rec365)}


def fetch_exchange_info():
    data = http_get("/exchangeInfo", {})
    out = {}
    for s in data.get("symbols", []):
        if s["symbol"] in SYMBOLS:
            filts = {f["filterType"]: f for f in s.get("filters", [])}
            out[s["symbol"]] = {
                "status": s.get("status"),
                "baseAsset": s.get("baseAsset"),
                "quoteAsset": s.get("quoteAsset"),
                "pricePrecision": s.get("pricePrecision"),
                "quantityPrecision": s.get("quantityPrecision"),
                "filters": filts}
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    results = {"generated_utc": iso(int(time.time() * 1000)),
               "source": "https://www.binance.com/fapi/v1 mirror (public endpoints)",
               "klines": {}, "funding": {}, "exchangeInfo": {},
               "errors": []}
    tasks = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for sym in SYMBOLS:
            for iv in INTERVALS:
                tasks[ex.submit(fetch_klines, sym, iv)] = ("klines", sym, iv)
        for sym in SYMBOLS:
            tasks[ex.submit(fetch_funding, sym)] = ("funding", sym, None)
        tasks[ex.submit(fetch_exchange_info)] = ("exchangeInfo", None, None)
        for fut in as_completed(tasks):
            kind, sym, iv = tasks[fut]
            try:
                res = fut.result()
            except Exception as e:
                results["errors"].append(f"{kind} {sym} {iv}: {e}")
                print(f"ERROR {kind} {sym} {iv}: {e}", flush=True)
                continue
            if kind == "klines":
                results["klines"].setdefault(sym, {})[iv] = res
                print(f"OK klines {sym} {iv}: total={res.get('total_bars')} "
                      f"gaps={res.get('gap_missing_bars')} "
                      f"atr365={res.get('atr_pct_median_365d')}",
                      flush=True)
            elif kind == "funding":
                results["funding"][sym] = res
                print(f"OK funding {sym}: count={res.get('count')} "
                      f"extreme365={res.get('extreme_total_365d')}",
                      flush=True)
            else:
                results["exchangeInfo"] = res
                print(f"OK exchangeInfo: {sorted(res.keys())}", flush=True)
    if STOP.is_set():
        results["rate_limited"] = True
    with open(os.path.join(OUT_DIR, "measurements.json"), "w") as f:
        json.dump(results, f, indent=1, ensure_ascii=False)
    print("WROTE measurements.json; errors:", results["errors"], flush=True)
    return 0 if not STOP.is_set() else 2


if __name__ == "__main__":
    sys.exit(main())
