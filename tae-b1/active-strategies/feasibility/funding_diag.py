#!/usr/bin/env python3
"""Funding pagination diagnostic + full-history fetch (NO P&L).
Tests: (a) does startTime with a real 2020 timestamp return old records?
(b) does endTime page backwards? (c) what is the per-request cap?
Then fetches full funding history per symbol with whichever pagination works.
"""
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.binance.com/fapi/v1"
SYMBOLS = ["ETHUSDT", "BTCUSDT", "XAUUSDT", "QQQUSDT"]
OUT = os.path.expanduser(
    "~/workspace/goals/100u-200u/files/tae-b1/active-strategies/feasibility")


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def get(path, params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(
        f"{BASE}{path}?{qs}",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def diff_hist(times):
    from collections import Counter
    d = Counter()
    for a, b in zip(times, times[1:]):
        d[(b - a) // 3600000] += 1
    return dict(sorted(d.items()))


def main():
    print("=== diagnostic ===", flush=True)
    # (c) no time params, limit=1000
    for sym in ("ETHUSDT", "XAUUSDT"):
        page = get("/fundingRate", {"symbol": sym, "limit": 1000})
        ts = [int(r["fundingTime"]) for r in page]
        print(f"{sym} limit=1000 no-time: n={len(page)} "
              f"first={iso(ts[0])} last={iso(ts[-1])} "
              f"diff_hours={diff_hist(ts)}", flush=True)
    # (a) startTime=2020-01-01, limit=5
    page = get("/fundingRate", {"symbol": "ETHUSDT",
                                "startTime": 1577836800000, "limit": 5})
    ts = [int(r["fundingTime"]) for r in page]
    print(f"ETH startTime=2020 limit=5: n={len(page)} "
          f"first={iso(ts[0]) if ts else None} "
          f"last={iso(ts[-1]) if ts else None}", flush=True)
    # (b) endTime just before 2026-05-15T16:00Z, limit=5
    end_ms = int(datetime(2026, 5, 15, 16, tzinfo=timezone.utc).timestamp()
                 * 1000) - 1
    page = get("/fundingRate", {"symbol": "ETHUSDT",
                                "endTime": end_ms, "limit": 5})
    ts = [int(r["fundingTime"]) for r in page]
    print(f"ETH endTime=2026-05-15T16:00Z-1ms limit=5: n={len(page)} "
          f"first={iso(ts[0]) if ts else None} "
          f"last={iso(ts[-1]) if ts else None}", flush=True)

    print("=== full-history fetch (forward from 2020, advancing startTime) ===",
          flush=True)
    allf = {}
    for sym in SYMBOLS:
        recs = []
        start = 1577836800000  # 2020-01-01
        prev_last = -1
        for _ in range(200):
            page = get("/fundingRate", {"symbol": sym,
                                        "startTime": start, "limit": 1000})
            if isinstance(page, dict) or not page:
                break
            for r in page:
                recs.append((int(r["fundingTime"]), float(r["fundingRate"])))
            last = int(page[-1]["fundingTime"])
            if last <= prev_last:
                break
            prev_last = last
            # stop once the last record is within the current 8h window
            if last >= int(time.time() * 1000) - 8 * 3600 * 1000:
                # one more fetch to confirm nothing beyond
                nxt = get("/fundingRate", {"symbol": sym,
                                           "startTime": last + 1,
                                           "limit": 1000})
                if isinstance(nxt, dict) or not nxt:
                    break
                for r in nxt:
                    recs.append((int(r["fundingTime"]),
                                 float(r["fundingRate"])))
                break
            start = last + 1
        recs.sort()
        allf[sym] = recs
        print(f"{sym}: full count={len(recs)} "
              f"first={iso(recs[0][0]) if recs else None} "
              f"last={iso(recs[-1][0]) if recs else None}", flush=True)

    # stats incl. extremes per calendar year (count only, no P&L)
    stats = {}
    now_ms = int(time.time() * 1000)
    y365 = now_ms - 365 * 24 * 3600 * 1000
    for sym, recs in allf.items():
        rates = [r for (_, r) in recs]
        by_year = {}
        for (t, r) in recs:
            y = datetime.fromtimestamp(t / 1000, tz=timezone.utc).year
            e = by_year.setdefault(y, {"n": 0, "pos_ext": 0, "neg_ext": 0})
            e["n"] += 1
            if r >= 0.0005:
                e["pos_ext"] += 1
            if r <= -0.0005:
                e["neg_ext"] += 1
        r365 = [r for (t, r) in recs if t >= y365]
        stats[sym] = {
            "count": len(recs),
            "earliest": iso(recs[0][0]) if recs else None,
            "latest": iso(recs[-1][0]) if recs else None,
            "mean_pct": statistics.mean(rates) * 100 if rates else None,
            "median_pct": statistics.median(rates) * 100 if rates else None,
            "abs_mean_pct": (statistics.mean([abs(r) for r in rates]) * 100
                             if rates else None),
            "extreme_pos_365d": sum(1 for r in r365 if r >= 0.0005),
            "extreme_neg_365d": sum(1 for r in r365 if r <= -0.0005),
            "extreme_total_365d": sum(1 for r in r365 if abs(r) >= 0.0005),
            "records_365d": len(r365),
            "by_year": by_year,
        }
        print(f"{sym} stats: {json.dumps(stats[sym], ensure_ascii=False)}",
              flush=True)
    # merge into measurements.json
    mpath = os.path.join(OUT, "measurements.json")
    m = json.load(open(mpath, encoding="utf-8"))
    m["funding"] = stats
    m["funding_full_fetch"] = True
    json.dump(m, open(mpath, "w", encoding="utf-8"), indent=1,
              ensure_ascii=False)
    print("MERGED funding stats into measurements.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
