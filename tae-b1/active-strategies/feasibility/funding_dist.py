#!/usr/bin/env python3
"""Funding distribution facts (NO P&L, NO trades).
Full-history funding per symbol via the mirror (forward pagination from 2020).
Reports: interval-diff histogram, rate percentiles, counts at the 0.03%
sensitivity level by year (the primary 0.05% counts are already in
measurements.json), and 2025/2026 means. Percentiles describe the funding
distribution; they are NOT a trading threshold pick.
"""
import json
import os
import statistics
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone

BASE = "https://www.binance.com/fapi/v1"
SYMBOLS = ["ETHUSDT", "BTCUSDT", "XAUUSDT", "QQQUSDT"]
OUT = os.path.expanduser(
    "~/workspace/goals/100u-200u/files/tae-b1/active-strategies/feasibility")


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def get(params_sym):
    sym, params = params_sym
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(
        f"{BASE}/fundingRate?{qs}",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def pct(data, q):
    if not data:
        return None
    s = sorted(data)
    i = min(len(s) - 1, max(0, int(q * len(s))))
    return s[i] * 100


def main():
    out = {}
    now_ms = int(time.time() * 1000)
    y365 = now_ms - 365 * 24 * 3600 * 1000
    for sym in SYMBOLS:
        recs = []
        start = 1577836800000
        prev_last = -1
        for _ in range(200):
            page = get((sym, {"symbol": sym, "startTime": start,
                              "limit": 1000}))
            if isinstance(page, dict) or not page:
                break
            for r in page:
                recs.append((int(r["fundingTime"]), float(r["fundingRate"])))
            last = int(page[-1]["fundingTime"])
            if last <= prev_last:
                break
            prev_last = last
            if last >= now_ms - 8 * 3600 * 1000:
                nxt = get((sym, {"symbol": sym, "startTime": last + 1,
                                 "limit": 1000}))
                if isinstance(nxt, dict) or not nxt:
                    break
                for r in nxt:
                    recs.append((int(r["fundingTime"]),
                                 float(r["fundingRate"])))
                break
            start = last + 1
        recs.sort()
        times = [t for (t, _) in recs]
        rates = [r for (_, r) in recs]
        diffs = Counter((b - a) // 3600000 for a, b in zip(times, times[1:]))
        by_year_003 = {}
        for (t, r) in recs:
            y = datetime.fromtimestamp(t / 1000, tz=timezone.utc).year
            e = by_year_003.setdefault(y, {"n": 0, "pos": 0, "neg": 0})
            e["n"] += 1
            if r >= 0.0003:
                e["pos"] += 1
            if r <= -0.0003:
                e["neg"] += 1
        r365 = [r for (t, r) in recs if t >= y365]
        m25 = [r for (t, r) in recs
               if datetime.fromtimestamp(t / 1000, tz=timezone.utc).year
               == 2025]
        m26 = [r for (t, r) in recs
               if datetime.fromtimestamp(t / 1000, tz=timezone.utc).year
               == 2026]
        out[sym] = {
            "count": len(recs),
            "interval_diff_hours": dict(sorted(diffs.items())),
            "pct": {"p50": pct(rates, 0.50), "p90": pct(rates, 0.90),
                    "p95": pct(rates, 0.95), "p99": pct(rates, 0.99),
                    "max": max(rates) * 100 if rates else None,
                    "min": min(rates) * 100 if rates else None},
            "counts_003_by_year": by_year_003,
            "counts_003_365d": {
                "pos": sum(1 for r in r365 if r >= 0.0003),
                "neg": sum(1 for r in r365 if r <= -0.0003),
                "n": len(r365)},
            "mean_2025_pct": (statistics.mean(m25) * 100 if m25 else None),
            "mean_2026_pct": (statistics.mean(m26) * 100 if m26 else None),
        }
        print(f"{sym}: n={len(recs)} diffs={dict(sorted(diffs.items()))} "
              f"p50={out[sym]['pct']['p50']} p99={out[sym]['pct']['p99']} "
              f"max={out[sym]['pct']['max']} "
              f"003_365d={out[sym]['counts_003_365d']} "
              f"mean25={out[sym]['mean_2025_pct']} "
              f"mean26={out[sym]['mean_2026_pct']}", flush=True)
    mpath = os.path.join(OUT, "measurements.json")
    m = json.load(open(mpath, encoding="utf-8"))
    m["funding_dist"] = out
    json.dump(m, open(mpath, "w", encoding="utf-8"), indent=1,
              ensure_ascii=False)
    print("MERGED funding_dist", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
