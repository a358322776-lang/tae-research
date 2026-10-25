"""Fetch Binance ETHUSDT perpetual klines + funding rates from the public mirror.

Source: https://www.binance.com/fapi/v1/klines (same endpoint the original
backtest scripts used) and .../fapi/v1/fundingRate. Closed-bar history is
immutable, so re-fetching reproduces identical inputs.

Windows (UTC, ms):
  OOS      : 2020-01-01T00:00Z .. 2025-10-17T02:00Z   (before ANY design data)
  INSAMPLE : 2025-10-17T02:00Z .. 2026-10-22T02:00Z   (v4.x 370-day window)
OOS end == in-sample start: no shared signal bar, no shared lookback window.
Early launch-week bars (2019-11-27, flat 146 prints) are excluded by the
2020-01-01 start.

Usage: python3 fetch_data.py --out /tmp/robustness-v41
Writes: oos.npz, insample.npz, funding_oos.csv, funding_insample.csv,
        manifest.json (exact ranges, counts, gap report).
"""
import argparse, json, os, sys, time, urllib.request
import numpy as np
from datetime import datetime, timezone

BASE = "https://www.binance.com/fapi/v1"
STEP = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000}
MS = lambda y, mo, d, h=0, mi=0: int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)

WINDOWS = {
    "oos": (MS(2020, 1, 1), MS(2025, 10, 17, 2, 0)),
    "insample": (MS(2025, 10, 17, 2, 0), MS(2026, 10, 22, 2, 0)),
}

def get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(5):
        try:
            return json.load(urllib.request.urlopen(req, timeout=timeout))
        except Exception as e:
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))

def fetch_klines(sym, iv, start_ms, end_ms):
    out, cur = {}, start_ms
    while cur < end_ms:
        url = (f"{BASE}/klines?symbol={sym}&interval={iv}&limit=1500"
               f"&startTime={cur}&endTime={end_ms}")
        raw = get_json(url)
        if not raw:
            break
        for r in raw:
            out[r[0]] = (float(r[1]), float(r[2]), float(r[3]), float(r[4]))
        cur = raw[-1][0] + STEP[iv]
        time.sleep(0.05)
    ts = sorted(out)
    arr = np.array([out[t] for t in ts], dtype=np.float64)
    return np.array(ts, dtype=np.int64), arr  # cols: o,h,l,c

def fetch_funding(sym, start_ms, end_ms):
    out, cur = [], start_ms
    while cur < end_ms:
        url = (f"{BASE}/fundingRate?symbol={sym}&limit=1000"
               f"&startTime={cur}&endTime={end_ms}")
        raw = get_json(url)
        if not raw:
            break
        for r in raw:
            out.append((r["fundingTime"], float(r["fundingRate"])))
        cur = raw[-1]["fundingTime"] + 1
        time.sleep(0.05)
    return out

def gap_report(ts, step):
    d = np.diff(ts)
    bad = np.where(d != step)[0]
    return {"n_gaps": int(len(bad)),
            "examples": [(int(ts[i]), int(ts[i + 1])) for i in bad[:5]]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", choices=["oos", "insample", "both"], default="both")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    manifest = {}
    wins = WINDOWS if a.only == "both" else {a.only: WINDOWS[a.only]}
    for name, (s, e) in wins.items():
        print(f"[{name}] fetching...", flush=True)
        data = {"t_start": s, "t_end": e}
        for iv in ("15m", "1h", "5m"):
            ts, arr = fetch_klines("ETHUSDT", iv, s, e)
            np.savez_compressed(os.path.join(a.out, f"{name}_{iv}.npz"), t=ts, ohlc=arr)
            data[iv] = {"n": int(len(ts)),
                        "first": datetime.fromtimestamp(ts[0] / 1000, timezone.utc).isoformat(),
                        "last": datetime.fromtimestamp(ts[-1] / 1000, timezone.utc).isoformat(),
                        "gaps": gap_report(ts, STEP[iv])}
            print(f"  {iv}: n={len(ts)} {data[iv]['first']} .. {data[iv]['last']} gaps={data[iv]['gaps']['n_gaps']}", flush=True)
        fr = fetch_funding("ETHUSDT", s, e)
        with open(os.path.join(a.out, f"funding_{name}.csv"), "w") as f:
            f.write("fundingTime,fundingRate\n")
            for t, r in fr:
                f.write(f"{t},{r}\n")
        data["funding"] = {"n": len(fr)}
        print(f"  funding: n={len(fr)}", flush=True)
        manifest[name] = data
    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
