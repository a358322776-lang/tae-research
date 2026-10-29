"""Fetch ETHUSDT 1h klines + fundingRate history via the www.binance.com
mirror (public endpoints only). Caches to faithful-teo/data/.
Known mirror quirk (feasibility study): no time params -> only latest 500
funding rows; startTime=0 is treated as absent -> always paginate with real
timestamps.
"""
import json
import time
import urllib.request
import urllib.error

BASE = "https://www.binance.com/fapi/v1"
SYMBOL = "ETHUSDT"
START_MS = 1577836800000  # 2020-01-01T00:00:00Z
END_MS = 1793222400000    # 2026-10-29T00:00:00Z (exclusive upper bound)
OUT_DIR = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/faithful-teo/data"


def get(url, tries=5):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001 - retry then raise
            last = e
            time.sleep(2 * (i + 1))
    raise last


def fetch_klines():
    out = []
    start = START_MS
    while True:
        url = (f"{BASE}/klines?symbol={SYMBOL}&interval=1h&startTime={start}"
               f"&endTime={END_MS}&limit=1500")
        rows = get(url)
        if not rows:
            break
        out.extend(rows)
        nxt = rows[-1][0] + 3600000
        if nxt >= END_MS or len(rows) < 1500:
            break
        start = nxt
    # dedupe + sort by open time
    seen = {}
    for r in out:
        seen[r[0]] = r
    rows = [seen[k] for k in sorted(seen)]
    return rows


def fetch_funding():
    out = []
    start = START_MS
    while True:
        url = (f"{BASE}/fundingRate?symbol={SYMBOL}&startTime={start}"
               f"&endTime={END_MS}&limit=1000")
        rows = get(url)
        if not rows:
            break
        out.extend(rows)
        nxt = rows[-1]["fundingTime"] + 1
        if nxt >= END_MS or len(rows) < 1000:
            break
        start = nxt
    seen = {}
    for r in out:
        seen[r["fundingTime"]] = r
    return [seen[k] for k in sorted(seen)]


def main():
    import os
    os.makedirs(OUT_DIR, exist_ok=True)
    kl = fetch_klines()
    print(f"klines: {len(kl)} rows, first={kl[0][0]}, last={kl[-1][0]}")
    # gap check on 1h grid
    gaps = 0
    for a, b in zip(kl, kl[1:]):
        gaps += (b[0] - a[0]) // 3600000 - 1
    print(f"klines gap_missing_bars: {gaps}")
    with open(f"{OUT_DIR}/klines_1h.json", "w", encoding="utf-8") as f:
        json.dump(kl, f)
    fd = fetch_funding()
    print(f"funding: {len(fd)} rows, first={fd[0]['fundingTime']}, "
          f"last={fd[-1]['fundingTime']}")
    with open(f"{OUT_DIR}/funding_rate.json", "w", encoding="utf-8") as f:
        json.dump(fd, f)


if __name__ == "__main__":
    main()
